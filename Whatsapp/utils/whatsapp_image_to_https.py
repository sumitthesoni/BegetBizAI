import os
import sys
import requests
from debugging.logger import logging
from debugging.exception import customException
from base64 import b64encode
from tenacity import retry, stop_after_attempt, wait_exponential
import warnings # For ignoring the warnings
warnings.filterwarnings("ignore")

# Load credentials from environment
ACCESS_TOKEN = os.getenv('WHATSAPP_ACCESS_TOKEN')
IMGBB_API_KEY = os.getenv('IMGBB_API_KEY')
IMGBB_URL = os.getenv("IMGBB_URL", "https://api.imgbb.com/1/upload")  # default fallback
WHATSAPP_API_VERSION = "v22.0"

# ─────────────────────────────────────────────────────────────────────────────
# ── Step 1: Get WhatsApp Media Temporary URL ─────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _get_whatsapp_media_url(media_id: str) -> str:
    url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{media_id}"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    media_url = response.json().get("url")
    if not media_url:
        raise ValueError("WhatsApp API did not return a media URL")
    return media_url

# ─────────────────────────────────────────────────────────────────────────────
# ── Step 2: Download Media Bytes from WhatsApp ───────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _get_image_bytes(media_url: str) -> bytes:
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    response = requests.get(media_url, headers=headers, timeout=10)
    response.raise_for_status()
    return response.content

# ─────────────────────────────────────────────────────────────────────────────
# ── Step 3: Convert to Public HTTPS via ImgBB ────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=2, max=10))
def whatsapp_image_to_https(media_id: str) -> str:
    """
    Converts a WhatsApp media ID into a publicly accessible HTTPS image URL
    using ImgBB as a hosting service.
    """
    try:
        # Step 1: Get temporary media URL from WhatsApp
        media_url = _get_whatsapp_media_url(media_id)
        logging.info(f"Got media URL for {media_id}: {media_url}")

        # Step 2: Download image data
        image_bytes = _get_image_bytes(media_url)
        logging.info(f"Downloaded image bytes for {media_id}")
        logging.info(f"Uploading image of size {len(image_bytes) / 1024:.2f} KB")

        # Step 3: Upload to ImgBB
        payload = {
            'key': IMGBB_API_KEY,
            'image': b64encode(image_bytes),
            'name': f'whatsapp_image_{media_id}',
            'expiration': 0  # image will not expire
        }

        response = requests.post(IMGBB_URL, data=payload, timeout=30)
        response.raise_for_status()

        # Step 4: Parse and return image URL
        image_url = response.json()['data']['display_url']
        logging.info(f"Uploaded to ImgBB: {image_url}")
        return image_url

    except Exception as e:
        logging.error(f"Failed to convert media {media_id} Error: {str(customException(e,sys))}")
        raise customException(e,sys)