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
from .countermanager import TableStorageManager


 
# Set up logging
logger = logging.getLogger(__name__)

# Initialize the TableStorageManager
connection_string = os.getenv('AZURE_STORAGE_CONNECTION_STRING')
try:
    table_manager = TableStorageManager(connection_string, "MessageCounter")
    logger.info("Connected to Azure Table Storage successfully.")
except Exception as e:
    logger.error("Failed to initialize Table Storage: ", exc_info=True)


MESSAGE_THRESHOLD = 55 
 
# Vonage and Flowise configuration

VONAGE_MESSAGES_API_URL = "https://api.nexmo.com/v1/messages"
VONAGE_APPLICATION_ID = os.getenv('VONAGE_APPLICATION_ID')

FLOWISE_API_URL = os.getenv('FLOWISE_API_URL')
 
# Path to private key file
PRIVATE_KEY_FILE_PATH = '/home/site/wwwroot/copilot/private.pem'


# Load the Private Key from file
def load_private_key_from_file(file_path):
    # Construct the full path using the current file's directory
    full_path = os.path.abspath(os.path.join(os.path.dirname(__file__), file_path))
    with open(full_path, 'r') as pem_file:
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
            # Check if the message threshold is reached


            # If threshold not reached, handle the text message and update the count
            flowise_response = await query_flowise(incoming_msg, sender_phone_number)
            if isinstance(flowise_response, str): 
# Here is where you should log and send the message
                logger.info(f"Sending Flowise response to WhatsApp: {flowise_response}")
                send_whatsapp_message(sender_phone_number, flowise_response)
                return func.HttpResponse(
                    json.dumps({"status": "success", "response_from_flowise": flowise_response}),
                    status_code=200,
                    mimetype="application/json"
                )
            else:
                logger.error("Failed to process text message.")


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
    logger.info(f"Threshold reached for {number}. Triggering Mpesa STK Push.")

    # Call STK Push API
    mpesa_response = call_mpesa_stkpush(number)

    if mpesa_response and 'invoice' in mpesa_response and 'invoice_id' in mpesa_response['invoice']:
        invoice_id = mpesa_response['invoice']['invoice_id']
        max_tries = 3
        count = 0

        # Initial delay before first status check
        time.sleep(15)

        while count < max_tries:
            payment_status_response = check_mpesa_stkpush_status(invoice_id)
            state = payment_status_response['invoice']['state']

            if state == 'COMPLETE':
                logger.info(f"Payment complete for {number}, resetting message count.")
                if table_manager.reset_message_count(number):
                    send_whatsapp_message(number, "Payment completed. You can resume the conversation.")
                    table_manager.set_notification_sent(number, sent=False)
                    logger.info("Confirmation message sent.")
                    return 'Payment completed. You can resume conversation.'
                else:
                    logger.error("Failed to reset message count.")
                    break

            elif state == 'RETRY' or state == 'FAILED':
                if not table_manager.is_notification_sent(number):
                    send_whatsapp_message(number, "Payment failed. Try sending another message to retry the payment.")
                    table_manager.set_notification_sent(number, sent=True)
                return 'Your payment failed. Please try sending another message to retry the payment.'

            elif state == 'PENDING':
                count += 1
                if count < max_tries:
                    time.sleep(5)  # Pause for next check
            else:
                logger.info("Unhandled payment state.")
        
        if count == max_tries:
            logger.info("Exceeded maximum number of tries for payment status checks.")
            send_whatsapp_message(number, "Your payment attempt is taking longer than usual. Please check your Mpesa messages.")
            table_manager.set_notification_sent(number, sent=True)
        return 'Your payment attempt is taking longer than usual. Please check your Mpesa messages.'
    else:
        logger.error("Failed to initiate payment.")
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
    WHITELIST = set(os.getenv('WHITELIST', '').split(','))

    vonage_sandbox_number = "254769132469"  # Replace with your Vonage number
    token = generate_jwt(VONAGE_APPLICATION_ID, VONAGE_PRIVATE_KEY)
    
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {token}',
    }

    # Fetch the current message count from Azure Table Storage
    count = table_manager.get_message_count(to_number)
    message_threshold = MESSAGE_THRESHOLD if to_number in WHITELIST else 7

    if count >= message_threshold:
        if not table_manager.is_notification_sent(to_number):  # Check if notification has already been sent
        
            if to_number in WHITELIST:
                # Custom message for whitelisted users when they reach 5 messages
                notification_msg = ("Hello! 👋\n"
                                    "Thank you for participating in our trial. You have reached 50 messages. "
                                    "Please contact 254706601809 for your reward before you continue. "
                                    "This will allow us to go through the conversation for analysis. "
                                    "Share this message as proof. Thank you for your support!")
            else:
                # Standard message for non-whitelisted users when they reach 7 messages
                notification_msg = ("Hello! 👋\n"
                                    "Thanks for using gTahidi! You've reached your free message limit of "
                                    f"{message_threshold} messages. To keep enjoying our services, please "
                                    "complete a small payment of 20 shillings via M-Pesa.\n"
                                    "Ensure your WhatsApp number is linked to your M-Pesa account. Need help? "
                                    "Call our support team at +254726278575.\n"
                                    "Thank you for your support!")

            payload = {
                "from": vonage_sandbox_number,
                "to": to_number,
                "message_type": "text",
                "text": notification_msg,
                "channel": "whatsapp"
            }

            logger.info(f"Vonage payload: {payload}")
            
            # Send the threshold notification message via Vonage
            response = requests.post(VONAGE_MESSAGES_API_URL, headers=headers, json=payload)
            if response.status_code != 202:
                table_manager.set_notification_sent(to_number, sent=True)
                logger.error(f"Failed to send threshold notification to {to_number}, Status Code: {response.status_code}, Response Body: {response.text}")
            
            # Log that the threshold message was sent
            logger.info(f"Threshold notification sent to {to_number}. Message: {notification_msg}")

            table_manager.set_notification_sent(to_number, sent=True)

            # Do not proceed with further message sending since the threshold message has been sent
            return handle_threshold_exceeded(to_number)

    # If threshold not reached, proceed to send the message
    payload = {
        "from": vonage_sandbox_number,
        "to": to_number,
        "message_type": "text",
        "text": text_message,
        "channel": "whatsapp"
    }
    
    response = requests.post(VONAGE_MESSAGES_API_URL, headers=headers, json=payload)
    if response.status_code == 202:
        message_uuid = response.json().get("message_uuid")
        logger.info(f"Message accepted by Vonage, UUID: {message_uuid}")
        table_manager.update_message_count(to_number, count + 1)
    else:
        logger.error(f"Failed to send message via Vonage to {to_number}, Status Code: {response.status_code}, Response Body: {response.text}")






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
        
        # Attempt to extract the first assistant message with text content
        if 'assistant' in response_data and 'messages' in response_data['assistant']:
            for message in response_data['assistant']['messages']:
                if message['role'] == 'assistant' and 'content' in message and message['content']:
                    for content in message['content']:
                        if 'text' in content and 'value' in content['text']:
                            return content['text']['value']

        return 'Sorry, I could not process your request.'  # Default response if no suitable message is found
    except Exception as e:
        logger.error(f"Error querying Flowise: {e}")
        return "We are currently updating our systems to accommodate all of you, please check in later"
