import os
import httpx
import asyncio
import sys
# from debugging.logger import logging
import logging
from debugging.exception import customException
from dotenv import load_dotenv
from langsmith.run_trees import RunTree
import warnings # For ignoring the warnings
warnings.filterwarnings("ignore")

load_dotenv()

# ─── Environment Configuration ───
WHATSAPP_API_URL       = os.getenv("WHATSAPP_API_URL")
WHATSAPP_ACCESS_TOKEN  = os.getenv("WHATSAPP_ACCESS_TOKEN")
PHONE_NUMBER_ID        = os.getenv("PHONE_NUMBER_ID")

# ─── Shared HTTP Headers and Timeout Config ───
HEADERS = {
    "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
    "Content-Type": "application/json"
}
TIMEOUT = httpx.Timeout(
    connect=15.0,  # time to establish connection
    read=60.0,     # time to wait for a read operation
    write=60.0,    # time to complete sending the request (upload)
    pool=10.0      # idle connection timeout
)

MAX_RETRIES = 5
RETRY_DELAY = 2  # in seconds

# ─────────────────────────────────────────────────────────────────────────────
# ── Send Text Message to WhatsApp ────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
async def send_text_message(to: str, message: str) -> bool:  
    """
    Sends a plain text message via WhatsApp API.
    Retries on transient (timeout/5xx) errors.
    """
    url = f"{WHATSAPP_API_URL}/{PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message}
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logging.info(f"[Attempt {attempt}] Sending text to {to}: {message}")
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                resp = await client.post(url, headers=HEADERS, json=payload)
                resp.raise_for_status()
            logging.info(f"Text sent to {to} (status {resp.status_code})")
            run = RunTree(name="Outgoing WhatsApp", inputs={"to": to, "message": message})
            run.post()  
            return True, resp.json()

        except (httpx.ConnectTimeout, httpx.ReadTimeout) as e:
            logging.warning(f"Timeout on attempt {attempt} sending text: {e!r}")

        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if 500 <= status < 600 and attempt < MAX_RETRIES:
                logging.warning(f"Server error {status} on attempt {attempt}; retrying...")
            else:
                logging.error(f"Failed to send text (status {status}): {e.response.text}")
                break

        except Exception as e:
            logging.error(f"Unexpected error sending text: {e!r}")
            break

        await asyncio.sleep(RETRY_DELAY)

    logging.error(f"All retries failed for sending text to {to}")
    return False,resp.json()

# ─────────────────────────────────────────────────────────────────────────────
# ── Upload Media (Image) to WhatsApp ─────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
async def upload_media(image_url: str) -> str:
    """
    Downloads image from URL and uploads it to WhatsApp.
    Returns the media_id or raises customException on failure.
    """

    # Step 1: Download image
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(image_url)
            resp.raise_for_status()
        image_bytes  = resp.content
        content_type = resp.headers.get("Content-Type", "application/octet-stream")
        if content_type == "image/jpg":
            content_type = "image/jpeg"
    except Exception as e:
        logging.error(f"Failed to download image {image_url}: {e!r}")
        raise customException(e, sys)

    # Step 2: Upload to WhatsApp
    url = f"{WHATSAPP_API_URL}/{PHONE_NUMBER_ID}/media"
    params = {"messaging_product": "whatsapp"}
    filename = os.path.basename(image_url).split("?")[0] or "upload"
    files = {"file": (filename, image_bytes, content_type)}

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logging.info(f"[Attempt {attempt}] Uploading media {filename}")
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                r = await client.post(url, headers={"Authorization": HEADERS["Authorization"]}, params=params, files=files)
                r.raise_for_status()
            media_id = r.json().get("id")
            logging.info(f"Uploaded media, media_id={media_id}")
            return media_id

        except (httpx.ConnectTimeout, httpx.ReadTimeout) as e:
            logging.warning(f"Timeout on attempt {attempt} uploading media: {e!r}")

        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if 500 <= status < 600 and attempt < MAX_RETRIES:
                logging.warning(f"Server error {status} on media upload; retrying...")
            else:
                logging.error(f"Failed to upload media (status {status}): {e.response.text}")
                break

        except Exception as e:
            logging.error(f"Unexpected error uploading media: {e!r}")
            break

        await asyncio.sleep(RETRY_DELAY)

    raise customException(RuntimeError("Media upload failed after retries"), sys)

# ─────────────────────────────────────────────────────────────────────────────
# ── Send Image by media_id with Optional Caption ─────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
async def send_image_by_id(to: str, media_id: str, caption: str = "") -> bool:
    """
    Sends an uploaded image to the given phone number using its media_id.
    Returns (True, response_json) on success, otherwise (False, response_json).
    """
    url = f"{WHATSAPP_API_URL}/{PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "image",
        "image": {"id": media_id, "caption": caption}
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logging.info(f"[Attempt {attempt}] Sending image-id {media_id} to {to}")
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                r = await client.post(url, headers=HEADERS, json=payload)
                r.raise_for_status()
            logging.info(f"Image-by-ID sent (status {r.status_code})")
            return True, r.json()

        except (httpx.ConnectTimeout, httpx.ReadTimeout) as e:
            logging.warning(f"Timeout on attempt {attempt} sending image-id: {e!r}")

        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if 500 <= status < 600 and attempt < MAX_RETRIES:
                logging.warning(f"Server error {status} sending image-id; retrying...")
            else:
                logging.error(f"Failed to send image-by-id (status {status}): {e.response.text}")
                break

        except Exception as e:
            logging.error(f"Unexpected error sending image-by-id: {e!r}")
            break

        await asyncio.sleep(RETRY_DELAY)

    logging.error(f"All retries failed for sending image-id {media_id} to {to}")
    return False, r.json()