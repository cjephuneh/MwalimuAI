## vonage main running application


import azure.functions as func
import os
import requests
import json
import logging
import jwt
import base64
from pathlib import Path
import time
 
# Set up logging
logger = logging.getLogger(__name__)
 
# Vonage and Flowise configuration

VONAGE_MESSAGES_API_URL = "https://api.nexmo.com/v1/messages"
VONAGE_APPLICATION_ID = os.getenv('VONAGE_APPLICATION_ID')

FLOWISE_API_URL = "http://20.8.140.23:3000/api/v1/prediction/ab912ece-da19-4721-ba72-6acd787adead"
 
# Path to private key file
PRIVATE_KEY_FILE_PATH = '/home/site/wwwroot/copilot/private.pem'

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
 


def process_image_with_azure_ai(image_url):
    # Log the image processing step for debugging
    logger.info(f"Processing image with Azure AI: {image_url}")
    
    # Download the image from the provided URL
    image_response = requests.get(image_url)
    image_response.raise_for_status()
    
    # Encode the image in base64
    encoded_image = base64.b64encode(image_response.content).decode('ascii')
    
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
        "top_p": 0.95,
        "max_tokens": 800
    }
    
    # Send POST request to the Azure endpoint and return the analyzed result
    try:
        ai_response = requests.post(AZURE_AI_ENDPOINT, headers=headers, json=payload)
        ai_response.raise_for_status()
        analysis_result = ai_response.json()

        # Log the full response from Azure AI for debugging
        logger.info(f"Azure AI response: {analysis_result}")
        return analysis_result
    except requests.RequestException as e:
        logger.error(f"Error processing image with Azure AI: {e}")
        return None


def get_image_url_from_data(data):
    """
    Extract the image URL from the Vonage inbound data.

    Args:
    data (dict): The inbound data from Vonage containing image information.

    Returns:
    str: The URL of the image if it exists, otherwise None.
    """
    # Extract the 'image' dictionary from the data and then the 'url' from the 'image' dictionary
    image_info = data['image']
    if image_info and 'url' in image_info:
        return image_info['url']
    else:
        # Log an error if the URL is not found and return None
        logger.error("No image URL found in the inbound data.")
        return None

# Global counter for responses
response_counter = 0

# Define the handler for vonage-inbound
def handle_vonage_inbound(data):
    global response_counter
    logger.info(f"Incoming data: {data}")

    sender_phone_number = data.get('from')

    # Call the STK push function with the sender's phone number
    call_mpesa_stkpush(sender_phone_number)

    # Increment the response counter and check if it's time to call Mpesa API
    response_counter += 1
    if response_counter >= 10:
        call_mpesa_stkpush()
        response_counter = 0  # Reset the counter

def call_mpesa_stkpush(sender_phone_number):
    logger.info("Calling Mpesa STK Push API...")

    # Construct the payload
    stk_payload = {
        "amount": 100,  # Hardcoded amount
        "phone_number": sender_phone_number  # Phone number from the sender
    }

    # Headers (if required, add here)
    headers = {
        'Content-Type': 'application/json'
        # Add other headers if needed
    }

    try:
        response = requests.post("https://gtahidi-django-api.azurewebsites.net/api/stkpush/", 
                                 json=stk_payload, 
                                 headers=headers)
        response.raise_for_status()
        logger.info(f"Mpesa STK Push API response: {response.json()}")
    except requests.RequestException as e:
        logger.error(f"Error calling Mpesa STK Push API: {e}")

 
 
def main(req: func.HttpRequest) -> func.HttpResponse:
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
        return handle_vonage_inbound(request_body)
 
    # If the request method is not POST, return a not found response
    return func.HttpResponse(status_code=404, body='Not Found')
 
    
# Initialization outside function to ensure it persists across invocations
processed_message_uuids = set()
 

# Define the handler for vonage-inbound
def handle_vonage_inbound(data):
    logger.info(f"Incoming data: {data}")

    try:
        # Extracting message_uuid and sender_phone_number
        message_uuid = data.get('message_uuid')
        sender_phone_number = data.get('from')

        # Skip processing if this UUID has been processed before
        if message_uuid in processed_message_uuids:
            logger.info("Duplicate message received, skipping processing.")
            return func.HttpResponse(status_code=200)
        

        processed_message_uuids.add(message_uuid)

        



        # Check message type here and handle None case
        message_type = data.get('message_type')
        if message_type is None:
            logger.warning(f"Received message with no type: {data}")
            # Handle this case as appropriate or return an error message
            return func.HttpResponse("Message type is undefined", status_code=400)

        # Handling 'image' message type from Vonage
        if message_type == 'image':
            image_url = get_image_url_from_data(data)
            if image_url:
                # Notify Flowise of image processing
                notify_flowise_image_processing("I received an image and am analyzing it. Please wait...", sender_phone_number)

                # Process the image and get the description
                image_description = process_image_with_azure_ai(image_url)
                # Send the description to Flowise and get the response
                if image_description:
                    # Now assume this returned description in string format
                    analysis_description = "Here is the description: " + str(image_description)
                    # Notify Flowise that image processing is finished and include the description
                    flowise_response_message = notify_flowise_image_processing("I have finished analyzing the image.", sender_phone_number, analysis_description)
                    if flowise_response_message:
                        # Send the response from Flowise to the user via WhatsApp
                        send_whatsapp_message(sender_phone_number, flowise_response_message)
                    else:
                        logger.error("Failed to get valid response from Flowise.")
                        # Handle error case, maybe send a default fallback message to the user, etc.
                else:
                    logger.error("Failed to get image description from Azure AI.")
            else:
                logger.error("No image URL found in the data.")

        # Handling 'text' message type from Vonage
        elif message_type == 'text':
            incoming_msg = data.get('text', '')
            response_message = query_flowise(incoming_msg, sender_phone_number)

            # Send the response message using Vonage API
            if response_message:
                send_whatsapp_message(sender_phone_number, response_message)
                return func.HttpResponse(
                    json.dumps({"status": "success", "response_from_flowise": response_message}),
                    status_code=200,
                    mimetype="application/json"
                )
            else:
                return func.HttpResponse("Failed to process text message.", status_code=500)

        # Handling unsupported message types
        else:
            logger.error(f"Unhandled message type: {message_type}")
            return func.HttpResponse("Message type not supported.", status_code=400)
        
                # Add the UUID to the set to mark it as processed after all processing is successful


    except Exception as e:
        logger.error(f"Exception in handle_vonage_inbound: {e}")
        return func.HttpResponse("Server error", status_code=500)

    

def notify_flowise_image_processing(notification_message, sender_phone_number, image_analysis=None):
    # Build the payload based on whether the image_analysis is provided
    payload = {"chatId": sender_phone_number}
    if image_analysis:
        payload["question"] = notification_message + " " + image_analysis
    else:
        payload["question"] = notification_message
    
    # Log the payload for debugging purposes
    logger.info(f"Payload being sent to Flowise: {payload}")

    # Send the notification to Flowise API
    try:
        response = requests.post(FLOWISE_API_URL, json=payload)
        response.raise_for_status()
        response_data = response.json()

        # Log the reponse for debugging purposes
        logger.info(f"Flowise response: {response_data}")
        
        # Assuming Flowise API returns a text field in the response with the message
        return response_data.get("text", "")

    except requests.RequestException as e:
        logger.error(f"Error notifying Flowise: {e}")
        return None

 
# Define the function to query the Flowise API
def query_flowise(question, chat_id, history=None, overrideConfig=None):
    payload = {
        "question": question,
        "chatId": chat_id
    }
# Include history and overrideConfig if provided
    if history is not None:
        payload["history"] = history
    if overrideConfig is not None:
        payload["overrideConfig"] = overrideConfig
 
    try:
        response = requests.post(FLOWISE_API_URL, json=payload)
        response.raise_for_status()
        response_data = response.json()
 
        logger.info(f"Response from Flowise: {response_data}")
        
        # Assuming the structure of the response, extract the response text
        messages = response_data.get('assistant', {}).get('messages', [])
        answer = ''
        if messages:
            answer_section = messages[0].get('content')[0].get('text')
            if answer_section:
                answer = answer_section.get('value', 'Sorry, I could not process your request.')
        else:
            answer = 'Sorry, I could not process your request.'
        
        logger.info(f"Answer from Flowise: {answer}")  # Logging the extracted answer
        
        return answer
    
    except requests.RequestException as e:
        logger.error(f"Error querying Flowise: {e}")
        return "An error occurred while processing your request."
 


 
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
    vonage_sandbox_number = "254795603014"  # Replaced with thw new number out of the sandbox
 
    token = generate_jwt(VONAGE_APPLICATION_ID, VONAGE_PRIVATE_KEY)

    # Construct the headers and payload
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {token}',
    }
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
        # You can store `message_uuid` for further tracking if needed
    else:
        logger.error(f"Failed to send message via Vonage, Status Code: {response.status_code}, Response Body: {response.text}")