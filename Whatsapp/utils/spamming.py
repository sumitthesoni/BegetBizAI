import time
from collections import defaultdict, deque
from debugging.logger import logging
from cachetools import TTLCache
from Whatsapp.send_whatsapp import send_text_message
import warnings # For ignoring the warnings
warnings.filterwarnings("ignore")

# ========== CONFIGURATION ==========
MAX_MESSAGES = 12         # Max messages allowed in short window
TIME_WINDOW = 60          # Time window for rate limiting (seconds)
DUPLICATE_COUNT = 3       # Same message repeated this many times = spam
BLOCK_DURATION = 1200     # 20 minutes in seconds
MESSAGE_HISTORY_LIMIT = 5 # Number of recent messages to track per user

# ========== IN-MEMORY STATE ==========
user_message_times = defaultdict(list)         # For rate limiting
recent_messages = defaultdict(lambda: deque(maxlen=MESSAGE_HISTORY_LIMIT))  # Track recent texts
blocked_users = TTLCache(maxsize=1000, ttl=BLOCK_DURATION)  # Blocked users

# ========== SPAM CHECKERS ==========

async def is_blocked(phone_number: str) -> bool:
    """Check if the user is currently blocked."""
    return phone_number in blocked_users

async def is_spamming(phone_number: str) -> bool:
    """Check if user is sending messages too quickly."""
    now = time.time()
    timestamps = user_message_times[phone_number]
    user_message_times[phone_number] = [t for t in timestamps if now - t < TIME_WINDOW]

    if len(user_message_times[phone_number]) >= MAX_MESSAGES:
        logging.warning(f"[SPAM] Rate limit exceeded by {phone_number}")
        blocked_users[phone_number] = True
        return True

    user_message_times[phone_number].append(now)
    return False

async def is_repeating_same_message(phone_number: str, text: str) -> bool:
    """Check if user sent same message 3 times in a row."""
    recent_texts = recent_messages[phone_number]
    recent_texts.append(text)
    
    # Check if we have enough messages to evaluate
    if len(recent_texts) < DUPLICATE_COUNT:
        return False

    # Manually check the last N messages instead of slicing
    duplicate_count = 0
    for i in range(1, DUPLICATE_COUNT + 1):
        if recent_texts[-i] == text:
            duplicate_count += 1
        else:
            break

    if duplicate_count >= DUPLICATE_COUNT:
        logging.warning(f"[SPAM] Duplicate message spam from {phone_number}")
        return True

    return False