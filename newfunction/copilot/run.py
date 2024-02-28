## vonage main running application

import azure.functions as func
import os

import json
import logging
import jwt
import base64
from pathlib import Path
import time
from functools import lru_cache
import aiohttp
import asyncio
import requests
from collections import defaultdict

 
# Set up logging
logger = logging.getLogger(__name__)
 
# Vonage and Flowise configuration

VONAGE_MESSAGES_API_URL = "https://api.nexmo.com/v1/messages"
VONAGE_APPLICATION_ID = os.getenv('VONAGE_APPLICATION_ID')

FLOWISE_API_URL = os.getenv('FLOWISE_API_URL')
 
# Path to private key file
PRIVATE_KEY_FILE_PATH = './private.pem'

# Load the Private Key from file
def load_private_key_from_file(file_path):
    with open(file_path, 'r') as pem_file:
        private_key = pem_file.read()
    return private_key

# Vonage client initialization
VONAGE_PRIVATE_KEY = load_private_key_from_file(PRIVATE_KEY_FILE_PATH)



app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# Set up Azure AI configuration
AZURE_AI_ENDPOINT = os.getenv('AZURE_AI_ENDPOINT')
AZURE_AI_KEY = os.getenv('AZURE_AI_KEY')

async def async_post_with_aiohttp(url, json_payload, headers):
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=json_payload) as response:
            response.raise_for_status()
            return await response.json()


async def process_image_with_azure_ai(image_url):
    # Log the image processing step for debugging
    logger.info(f"Processing image with Azure AI: {image_url}")
    
    # Download the image from the provided URL
    async with aiohttp.ClientSession() as session:
        async with session.get(image_url) as image_response:
            image_response.raise_for_status()
            image_content = await image_response.read()

    # Encode the image in base64
    encoded_image = base64.b64encode(image_content).decode('ascii')
    
    # Set up headers with API key
    headers = {
        "Content-Type": "application/json",
        "api-key": AZURE_AI_KEY,
    }
    
    # Create the payload in the expected format
    payload = {
        "messages": [
            {
                "role": "system",
                "content": [{"type": "text", "text": "you are an image analyst expert, your work is to read images and provide the most vivid description it has, make use of the caption/ description to make a sense of the image, the description provided is sent to an AI model that handles interactions between the user and their conversations. provide clear descriptions as this will help the ai model understand what is in the picture, youu will act as the eyes to the model"}]
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{encoded_image}"
                        }
                    }
                ]
            }
            # You can extend the messages list if you need other interactions
        ],
        "temperature": 0.7,
        "top_p": 0.9,
        "max_tokens": 500
    }
    
    # Send POST request to the Azure endpoint and return the analyzed result
    try:
        ai_response_data = await async_post_with_aiohttp(AZURE_AI_ENDPOINT, payload, headers)
        logger.info(f"Azure AI response: {ai_response_data}")
        return ai_response_data
    except Exception as e:
        logger.error(f"Error processing image with Azure AI: {e}")
        return None


def get_image_url_from_data(data):
   
    # Extract the 'image' dictionary from the data and then the 'url' from the 'image' dictionary
    image_info = data['image']
    if image_info and 'url' in image_info:
        return image_info['url']
    else:
        # Log an error if the URL is not found and return None
        logger.error("No image URL found in the inbound data.")
        return None
    
 
 
async def main(req: func.HttpRequest) -> func.HttpResponse:
    logger.info('Python HTTP trigger function processed a request.')
 
    # Log the headers and body of the incoming request for debugging
    logger.info(f"Request headers: {req.headers}")
    
 
    # Check if the request has JSON content
    try:
        request_body = req.get_json()  # Directly get JSON content
    except ValueError:
        return func.HttpResponse("Invalid JSON", status_code=400)
    
    logger.info(f"Request body: {request_body}")
 
    # Handle the '/vonage-inbound' path
    if req.method == 'POST':
        response = await handle_vonage_inbound(request_body)  # Use await here
        return response
 
    # If the request method is not POST, return a not found response
    return func.HttpResponse(status_code=404, body='Not Found')
 
    
# Initialization outside function to ensure it persists across invocations
processed_message_uuids = set()

# Global variable to track the number of messages sent
sent_messages_counter = defaultdict(int)

 


        # Define the handler for vonage-inbound
async def handle_vonage_inbound(data):
    
    logger.info(f"Incoming data: {data}")

    try:
        message_uuid = data.get('message_uuid')
        sender_phone_number = data.get('from')

        if message_uuid in processed_message_uuids:
            logger.info("Duplicate message received, skipping processing.")
            return func.HttpResponse(status_code=200)

        processed_message_uuids.add(message_uuid)

        message_type = data.get('message_type')
        if message_type is None:
            logger.info("Received message with no type, possibly from Flowise.")
            return func.HttpResponse("No action needed for no-type message", status_code=200)
    
        if message_type == 'image':
            image_url = get_image_url_from_data(data)
            if image_url:
                notify_msg = "I received an image and am analyzing it. Please wait..."
                notify_response = await notify_flowise_image_processing(notify_msg, sender_phone_number)

                image_description = await process_image_with_azure_ai(image_url)
                if image_description:
                    analysis_description = f"Here is the description: {image_description}"
                    flowise_response_message = await notify_flowise_image_processing(
                        "I have finished analyzing the image.", sender_phone_number, analysis_description)
                    if flowise_response_message:
                        send_whatsapp_message(sender_phone_number, flowise_response_message)
                    else:
                        logger.error("Failed to get valid response from Flowise.")
                else:
                    logger.error("Failed to get image description from Azure AI.")
            else:
                logger.error("No image URL found in the data.")

        elif message_type == 'text':
            incoming_msg = data.get('text', '')
            flowise_response = await query_flowise(incoming_msg, sender_phone_number)

            if isinstance(flowise_response, dict) and "value" in flowise_response:
                response_message = flowise_response["value"]
            else:
                response_message = flowise_response

            if response_message:
                send_whatsapp_message(sender_phone_number, response_message)
                return func.HttpResponse(
                    json.dumps({"status": "success", "response_from_flowise": response_message}),
                    status_code=200,
                    mimetype="application/json"
                )
            else:
                return func.HttpResponse("Failed to process text message.", status_code=500)

        else:
            logger.error(f"Unhandled message type: {message_type}")
            return func.HttpResponse("Message type not supported.", status_code=400)
   
      
    except Exception as e:
            logger.error(f"Exception in handle_vonage_inbound: {e}")
            error_message = "Due to high demand, you have exceeded your conversational limit. Please try again after some time."
            return func.HttpResponse(error_message, status_code=500)
    
    return func.HttpResponse("Message processed successfully", status_code=200)


async def notify_flowise_image_processing(notification_message, sender_phone_number, image_analysis=None):
    payload = {"chatId": sender_phone_number}
    if image_analysis:
        payload["question"] = notification_message + " " + image_analysis
    else:
        payload["question"] = notification_message

    headers = {"Content-Type": "application/json"}

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(FLOWISE_API_URL, json=payload, headers=headers) as response:
                response.raise_for_status()
                response_data = await response.json()
                logger.info(f"Flowise response: {response_data}")
                return response_data.get("text", "")
        except aiohttp.ClientError as e:
            logger.error(f"Error notifying Flowise: {e}")
            return None

    


def call_mpesa_stkpush(sender_phone_number):
    stk_payload = {
  "phone_number": sender_phone_number
}

    headers = {
        'Content-Type': 'application/json'
    }

    # Use requests for synchronous call
    try:
        response = requests.post(os.getenv('MPESA_API_URL'), headers=headers, json=stk_payload)
        response_data = response.json()
        logger.info(f"STK Push response status: {response.status_code}")
        logger.info(f"STK Push response data: {response_data}")
        return response_data
    except requests.RequestException as e:
        logger.error(f"STK Push request failed: {e}")
        return None
    

def check_mpesa_stkpush_status(invoice_id):
    stk_payload = {
  "invoice_id": invoice_id
}

    headers = {
        'Content-Type': 'application/json'
    }

    # Use requests for synchronous call
    try:
        response = requests.post(os.getenv('MPESA_CHECK_URL'), headers=headers, json=stk_payload)
        response_data = response.json()
        logger.info(f"STK Push response status: {response.status_code}")
        logger.info(f"STK Push response data: {response_data}")
        return response_data
    except requests.RequestException as e:
        logger.error(f"STK Push request failed: {e}")
        return None    




def handle_threshold_exceeded(number):
    global sent_messages_counter
    logger.info(f"Threshold reached for {number}. Triggering Mpesa STK Push.")

    # Call STK Push API
    mpesa_response = call_mpesa_stkpush(number)

    if mpesa_response and 'invoice' in mpesa_response and 'invoice_id' in mpesa_response['invoice']:
        invoice_id = mpesa_response['invoice']['invoice_id']

        max_tries = 3
        count = 0

        # Introducing initial 15-second delay before first status check
        time.sleep(15)

        while count < max_tries:   # Start continuous polling, upto max_tries
            payment_status_response = check_mpesa_stkpush_status(invoice_id)
            state = payment_status_response['invoice']['state']

            if state == 'COMPLETE':  # If payment is complete
                sent_messages_counter[number] = 0  # Reset counter
                return 'Payment completed. You can resume conversation.'
            elif state == 'PENDING':  # If payment is still processing
                count += 1  # Increment the count only after first check

                if count < max_tries:
                    time.sleep(5)  # Pausing execution for 5 seconds for next check
                continue
                
        # If exceeded max_tries and payment is still not complete  
        return 'Your payment attempt is taking longer than usual. Please check your Mpesa messages.'
    else:
        return 'Failed to initiate payment. Please try again.'
    
 
 
# Vonage client initialization
def generate_jwt(application_id, private_key):
    current_time = int(time.time())
    payload = {
        "iat": current_time,
        "jti": f"{current_time}-{os.urandom(64).hex()}",
        "application_id": application_id
    }
    token = jwt.encode(payload, private_key, algorithm='RS256')
    return token

def send_whatsapp_message(to_number, text_message):
    global sent_messages_counter

    vonage_sandbox_number = "254769123018"  # Replace with your Vonage number
    token = generate_jwt(VONAGE_APPLICATION_ID, VONAGE_PRIVATE_KEY)
    
    # Start headers and payload construction here
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {token}',
    }
    
    if sent_messages_counter[to_number] >= 10:  # If user reached threshold
         # Notify user that the threshold is reached
        notification_msg = " You have reached the maximum limit of messages, and you will be required to pay 20 shillings to continue. Now triggering a payment of 50 shillings. an STK will popup shortly /n incase of any problem text/call whatsapp +25472627875"
        payload = {
            "from": vonage_sandbox_number,
            "to": to_number,
            "message_type": "text",
            "text": notification_msg,
            "channel": "whatsapp"
        }
        
        # Send the message
        response = requests.post(VONAGE_MESSAGES_API_URL, headers=headers, json=payload)
        if response.status_code != 202:
            logger.error(f"Failed to send message via Vonage, Status Code: {response.status_code}, Response Body: {response.text}")

        logger.info(f"[send_whatsapp_message] Handling threshold exceeded case for user {to_number}")
        text_message = handle_threshold_exceeded(to_number)

        # Construct payload for the response message
        payload = {
            "from": vonage_sandbox_number,
            "to": to_number,
            "message_type": "text",
            "text": text_message,
            "channel": "whatsapp"
        }

        # Send response message via whatsapp
        response = requests.post(VONAGE_MESSAGES_API_URL, headers=headers, json=payload)
        if response.status_code != 202:
            logger.error(f"Failed to send message via Vonage, Status Code: {response.status_code}, Response Body: {response.text}")
 
        return
             
    payload = {
        "from": vonage_sandbox_number,
        "to": to_number,
        "message_type": "text",
        "text": text_message,
        "channel": "whatsapp"
    }

    # Log the payload for debugging purposes
    logger.info(f"Sending payload to Vonage API: {payload}")
    
    response = requests.post(VONAGE_MESSAGES_API_URL, headers=headers, json=payload)
    
    if response.status_code == 202:
        message_uuid = response.json().get("message_uuid")
        logger.info(f"Message accepted by Vonage, UUID: {message_uuid}")
        
        sent_messages_counter[to_number] += 1
        logger.info(f"Message sent. Incrementing sent_messages_counter to {sent_messages_counter}")
    else:
        logger.error(f"Failed to send message via Vonage, Status Code: {response.status_code}, Response Body: {response.text}")



async def query_flowise(question, chat_id, history=None, overrideConfig=None):
    payload = {
        "question": question,
        "chatId": chat_id
    }
    # Include history and overrideConfig if provided
    if history is not None:
        payload["history"] = history
    if overrideConfig is not None:
        payload["overrideConfig"] = overrideConfig

    headers = {"Content-Type": "application/json"}

    logger.info(f"Payload for Flowise: {payload}")


    try:
        response_data = await async_post_with_aiohttp(FLOWISE_API_URL, payload, headers)
        logger.info(f"Response from Flowise: {response_data}")
        
        messages = response_data.get('assistant', {}).get('messages', [])
        if messages:
            answer_section = messages[0].get('content', [{}])[0].get('text', 'Sorry, I could not process your request.')
            return answer_section
        else:
            return 'Sorry, I could not process your request.' 
    except Exception as e:
        logger.error(f"Error querying Flowise: {e}")
        return "There Was an error processing your request due to high demand, please try again later"
