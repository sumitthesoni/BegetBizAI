# whatsapp_tools.py
# 
# This module provides functions to send WhatsApp messages and share chat histories
# with retries, error handling, and integration with Langsmith RunTree.

# ─── Standard Library Imports ───────────────────────────────
import os
import time
import io
import warnings  # For ignoring any warnings

# ─── Third-Party Imports ────────────────────────────────────
import httpx  # HTTP client for making requests
from dotenv import load_dotenv  # Load environment variables from .env files

# ─── Langchain & Langsmith Imports ─────────────────────────
from langchain_core.tools import tool
from langchain_core.runnables.config import RunnableConfig
from langsmith.run_trees import RunTree

# ─── Custom Module Imports ──────────────────────────────────
from debugging.logger import logging  # Custom logging configuration
from Memory.sqldatabase import load_memory  # Load chat memory from SQL database
from config import OPERATION_TEAM_NUMBER # Loading operation team number

# ─── Configuration & Environment Setup ─────────────────────
warnings.filterwarnings("ignore")
load_dotenv()  # Load .env variables into process environment

# WhatsApp API configuration from environment
WHATSAPP_API_URL = os.getenv("WHATSAPP_API_URL")
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

# Shared HTTP headers and timeout settings
TIMEOUT = httpx.Timeout(
    connect=15.0,  # Max time to establish connection
    read=60.0,     # Max time to wait for server response
    write=60.0,    # Max time to send request data
    pool=10.0      # Max time for idle connection reuse
)

# Retry configuration
MAX_RETRIES = 5
RETRY_DELAY = 2  # Delay (in seconds) between retry attempts


def convert_messages_to_text(messages: list) -> str:
    """
    Convert a list of chat messages into a single text string.
    Each message is prefixed by the sender (User or Assistant).
    """
    lines = []
    for msg in messages:
        if msg.type == "human":
            lines.append(f"User: {msg.content}")
        elif msg.type == "ai":
            lines.append(f"Divya: {msg.content}")
    # Join messages with double newlines between entries
    return "\n\n".join(lines)


def send_txt_history_on_whatsapp(thread_id: str, phone_number: str) -> bool:
    """
    Share the chat history for a given thread as a .txt document via WhatsApp.

    Steps:
    1. Load conversation memory from the database.
    2. Convert messages to text and store in an in-memory buffer.
    3. Upload the buffer as a document to the WhatsApp media endpoint.
    4. Send the uploaded media by referencing its media ID.

    Returns a success or error message string.
    """
    HEADERS = {
    "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"
    }
    try:
        # Load chat memory
        memory = load_memory(thread_id)
        messages = memory.chat_memory.messages

        # Convert messages to text and write to BytesIO buffer
        txt_content = f"Phone Number: {thread_id}\n\n"+f"Previous history summary: {memory.moving_summary_buffer}\n\n"+convert_messages_to_text(messages)
        buffer = io.BytesIO()
        buffer.write(txt_content.encode("utf-8"))
        buffer.seek(0)

        # Upload document to WhatsApp media endpoint
        upload_url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/media"
        files = {"file": (f"{thread_id}_history.txt", buffer, "text/plain")}
        data = {"messaging_product": "whatsapp", "type": "document"}

        logging.info("Uploading chat history document...")
        with httpx.Client(timeout=TIMEOUT) as client:
            upload_resp = client.post(upload_url, headers=HEADERS, data=data, files=files)
            upload_resp.raise_for_status()
            media_id = upload_resp.json().get("id")

        # Send the uploaded document via WhatsApp
        send_url = f"{WHATSAPP_API_URL}/{PHONE_NUMBER_ID}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": phone_number,
            "type": "document",
            "document": {"id": media_id, "filename": f"{thread_id}_history.txt"}
        }

        logging.info("Sending document message...")
        with httpx.Client(timeout=TIMEOUT) as client:
            send_resp = client.post(
                send_url,
                headers={**HEADERS, "Content-Type": "application/json"},
                json=payload
            )
            send_resp.raise_for_status()

        logging.info(f"Document sent to {phone_number} successfully.")
        return True

    except Exception as e:
        logging.error(f"Error sending chat history via WhatsApp: {e}")
        # Fallback message in case of failure
        return False


# ─── Plain Text Message Sending Function ────────────────────

def send_text_message(to: str, message: str) -> bool:
    """
    Send a plain text message via WhatsApp with retry logic.

    Returns True on success, False otherwise.
    """
    HEADERS = {
    "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
    "Content-Type": "application/json"
    }

    url = f"{WHATSAPP_API_URL}/{PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message}
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logging.info(f"[Attempt {attempt}] Sending text to {to}")
            with httpx.Client(timeout=TIMEOUT) as client:
                resp = client.post(url, headers=HEADERS, json=payload)
                resp.raise_for_status()

            logging.info(f"Text sent (status {resp.status_code})")
            run = RunTree(name="Outgoing WhatsApp", inputs={"to": to, "message": message})
            run.post()
            return True

        except (httpx.ConnectTimeout, httpx.ReadTimeout) as e:
            logging.warning(f"Timeout on attempt {attempt}: {e}")

        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if 500 <= status < 600 and attempt < MAX_RETRIES:
                logging.warning(f"Server error {status}, retrying...")
            else:
                logging.error(f"Failed (status {status}): {e.response.text}")
                break

        except Exception as e:
            logging.error(f"Unexpected error: {e}")
            break

        time.sleep(RETRY_DELAY)

    logging.error(f"All retries failed for {to}")
    return False


# ─── Langchain Tool Definition ─────────────────────────────
@tool
def send_lead(lead: str, config: RunnableConfig) -> str:
    """
    Langchain tool to send lead information to the operations team.

    """
    thread_id = config.get('metadata').get('thread_id')
    # Send lead notification to operations
    if send_text_message(to=OPERATION_TEAM_NUMBER, message=lead):
        # On success, share full chat history
        logging.info("Lead summary sent successfully")
        if send_txt_history_on_whatsapp(thread_id=thread_id, phone_number=OPERATION_TEAM_NUMBER):
            logging.info("Lead history also sent successfully")
            return 'Lead shared successfully'
        else:
            return (
                    "Lead couldn't be shared due to an internal issue. "
                    f"say to user to call the operations team directly at {OPERATION_TEAM_NUMBER}"
                )
    else:
            return (
                    "Lead couldn't be shared due to an internal issue. "
                    f"say to user to call the operations team directly at {OPERATION_TEAM_NUMBER}"
                )    