import logging
from zep_python import ZepClient, NotFoundError
from zep_python.user import CreateUserRequest, UpdateUserRequest
from zep_python.memory import Memory
from zep_python.message import Message
from zep_python.memory import Session

# Configure logging
logging.basicConfig(level=logging.INFO)

async def ensure_user_exists(client, user_id, metadata):
    """
    Ensure the user exists in Zep, or creates a new one.
    """
    try:
        await client.user.aget(user_id)
        logging.info(f"User {user_id} already exists.")
    except NotFoundError:
        user_request = CreateUserRequest(user_id=user_id, metadata=metadata)
        await client.user.aadd(user_request)
        logging.info(f"User {user_id} created.")

def prepare_messages_for_zep(flowise_response):
    """
    Prepare messages to be sent to Zep from the Flowise response.
    """
    messages = []
    for msg in flowise_response['assistant']['messages']:
        content = msg['content'][0]['text']['value'] if msg['content'] else 'No Content'
        role = 'human' if msg['role'] == 'user' else 'ai'
        messages.append(Message(role=role, content=content))
    return messages

def extract_user_metadata(flowise_response):
    """
    Extract metadata from the Flowise response.
    """
    metadata = {
        'assistantId': flowise_response['assistant'].get('assistantId', 'Unknown'),
        'threadId': flowise_response['assistant'].get('threadId', 'Unknown'),
        'runId': flowise_response['assistant'].get('runId', 'Unknown'),
        'usedTools': flowise_response.get('usedTools', []),
        'fileAnnotations': flowise_response.get('fileAnnotations', [])
        # Add other metadata extraction as needed
    }
    return metadata

async def send_memory_to_zep(client, session_id, zep_messages, metadata):
    """
    Send the prepared memory to Zep.
    """
    memory = Memory(messages=zep_messages, metadata=metadata)
    try:
        await client.memory.aadd_memory(session_id, memory)
        logging.info(f"Memory uploaded for session {session_id}.")
    except Exception as e:
        logging.error(f"Error uploading memory for session {session_id}: {e}")
