import warnings

# Ignore all warnings
warnings.filterwarnings("ignore")

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Query, Response, HTTPException

from Whatsapp.receive_whatsapp import handle_whatsapp_message
from Whatsapp.send_whatsapp import send_text_message
from Whatsapp.utils.spamming import is_spamming, is_repeating_same_message, is_blocked

from debugging.logger import logging
from debugging.exception import customException
import traceback 
import sys

# Load environment variables
load_dotenv()

from cachetools import TTLCache
from collections import defaultdict
import asyncio

# initialization
app = FastAPI()
PROCESSED_MESSAGES = TTLCache(maxsize=1000, ttl=300)  # 5-minute cache
USER_PROCESSING_STATE = defaultdict(lambda: False)
USER_QUEUES = defaultdict(asyncio.Queue)
BLOCKED_NOTICE_SENT = TTLCache(maxsize=1000, ttl=30)  # Avoid sending notice again for 30s

VERIFY_TOKEN = "BegetBegetBiz*1"
if not VERIFY_TOKEN:
    logging.error("VERIFY_TOKEN is not set in environment variables.")
    raise RuntimeError("VERIFY_TOKEN must be set in environment variables.")

@app.api_route("/webhook", methods=["GET", "POST"])
@app.api_route("/webhook/", methods=["GET", "POST"])
async def webhook(
    request: Request,
    hub_mode: str = Query(default=None, alias="hub.mode"),
    hub_challenge: str = Query(default=None, alias="hub.challenge"),
    hub_verify_token: str = Query(default=None, alias="hub.verify_token")
):
    # ─── Verification (GET) ───
    if request.method == "GET":
        try:
            logging.info("GET request received for webhook verification.")
            if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
                logging.info("Webhook verified successfully.")
                return Response(content=hub_challenge, media_type="text/plain")
            logging.warning("Webhook verification failed.")
            return Response(status_code=403, content="Forbidden")
        
        except Exception as e:
            logging.error(f"Webhook error: {traceback.format_exc()}")
            raise HTTPException(status_code=500, detail="Internal Server Error")  
          
    # ─── Incoming payload (POST) ───
    elif request.method == "POST":
        try:
            payload = await request.json()
            logging.info("Received POST data")
            # ─── 1) Short-circuit status updates ───
            entry = payload.get("entry", [{}])[0]
            change = entry.get("changes", [{}])[0]
            value = change.get("value", {})
            statuses = value.get("statuses")
            if statuses:
                for status in statuses:
                    logging.info(
                        f"Status update for {status.get('recipient_id')}: "
                        f"{status.get('status')} at {status.get('timestamp')}"
                    )
                # Don't process as a message
                return {"status": "status_update"}

            # ─── 2) Extract message ID and check duplicates ───
            messages = value.get("messages", [])
            if not messages:
                logging.warning("Received payload with no messages")
                return {'status': 'ignored'}
            message = messages[0]
            message_id = message["id"]
            phone_number = message["from"]

            # Check if we've already processed this message
            if message_id in PROCESSED_MESSAGES:
                logging.info(f"Ignoring duplicate message: {message_id}")
                return {"status": "duplicate"}

            # Pre-check before queueing
            message_type = message.get("type")
            text = message.get("text", {}).get("body", "").strip()
                
            # Check if blocked
            if await is_blocked(phone_number):
                logging.info(f"Blocked user tried to message: {phone_number}")
                if phone_number not in BLOCKED_NOTICE_SENT:
                    await send_text_message(to=phone_number, message="You are blocked for 20 minutes. Try again later.")
                    BLOCKED_NOTICE_SENT[phone_number] = True
                return {"status": "blocked"}
            
            # Check if spamming
            if await is_spamming(phone_number):
                return {"status": "spamming"}
            
            else:
                # Check repeated message
                if message_type == "text" and text:
                    if await is_repeating_same_message(phone_number, text):
                        await send_text_message(to=phone_number, message="Don't send the same message again and again.")
                        return {"status": "repeating"}
                # Add to processed cache
                PROCESSED_MESSAGES[message_id] = True

                # Queue and start processing
                await USER_QUEUES[phone_number].put((message, payload))
                if not USER_PROCESSING_STATE.get(phone_number, False):
                    USER_PROCESSING_STATE[phone_number] = True
                    asyncio.create_task(process_user_queue(phone_number))

                return {"status": "queued"}
            
        except Exception as e:
            logging.error(f"Webhook error: {traceback.format_exc()}")
            if phone_number:
                try:
                    await send_text_message(to=phone_number, message="Server busy. Try again later.")
                except Exception as inner:
                    logging.error(f"Notify failed: {inner}")
                raise HTTPException(status_code=500, detail="Internal Server Error")

# ────────────────────────────────────────────────────────────────
# QUEUE HANDLER FUNCTION
# ────────────────────────────────────────────────────────────────                     
async def process_user_queue(phone_number: str):
    USER_PROCESSING_STATE[phone_number] = True
    try:
        logging.info(f"Processing queue for {phone_number}")
        
        while not USER_QUEUES[phone_number].empty():
            if await is_blocked(phone_number):
                await send_text_message(to=phone_number, message="You are blocked for 20 minutes. Try again later.")
                logging.info(f"User {phone_number} is now blocked. Stopping further processing.")
                logging.info(f"Clearing queue for blocked user: {phone_number}")
                USER_QUEUES[phone_number] = asyncio.Queue()  # Reset the queue
                break  # Exit loop early

            try:
                message, payload = await USER_QUEUES[phone_number].get()

                # Optional: log message content
                logging.debug(f"Processing message from {phone_number}: {message.get('text', {}).get('body', '')}")

                # Pass directly to handler (all checks done earlier)
                try:
                    await handle_whatsapp_message(data=payload)

                except Exception as e:
                    logging.error(f"Handler failed: {traceback.format_exc()}")
                    try:
                        await send_text_message(phone_number, "⚠️ Our system is busy, please try again later.")
                    except Exception as send_fail:
                        logging.error(f"Failed to notify user of error: {send_fail}")
                
                finally:
                    USER_QUEUES[phone_number].task_done()
                    await asyncio.sleep(0.1)  # Small delay between tasks

            except Exception as e:
                logging.critical(f"Queue processor crashed: {traceback.format_exc()}")

    except Exception as e:
        logging.warning(f"Error occurred during processing: {str(customException(e, sys))}")
        try:
            await send_text_message(to=phone_number, message="⚠️ Server busy. Try again later.")
        except:
            pass

    finally:
        USER_PROCESSING_STATE[phone_number] = False
        logging.info(f"Stopped processing for {phone_number}")
