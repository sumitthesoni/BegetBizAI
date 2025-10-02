# ––– Standard Library Imports –––
import os
import json
import sys
import sqlite3
from dotenv import load_dotenv
from debugging.logger import logging
from debugging.exception import customException
from config import DB_PATH,SUMMARY_PROMPT_PATH,CRED_PATH
import warnings

# Ignore all warnings
warnings.filterwarnings("ignore")

# ––– Third-Party/External Library Imports –––
from langchain_groq import ChatGroq
from langchain.memory import ConversationSummaryBufferMemory
from langchain.schema import messages_to_dict, messages_from_dict
from langchain.prompts import PromptTemplate
import firebase_admin
from firebase_admin import credentials, firestore

# Loading GROQ_API_KEY
load_dotenv()
GROQ_API_KEY=os.getenv('GROQ_API_KEY')

# Initialize the Groq language model for summarization
llm = ChatGroq(model="llama-3.1-8b-instant", temperature=0.7)

# ––– 1) DATABASE HELPERS ––– #

# Define the SQLite database file path
DB_PATH = DB_PATH

# Create a connection to the SQLite database (thread-safe for use in FastAPI, etc.)
conn = sqlite3.connect(DB_PATH, check_same_thread=False)

# Create table to store chat sessions
# - thread_id: Unique ID per conversation
# - messages: JSON serialized list of messages
# - summary: Summarized string of chat history
# - image_store: JSON serialized dict mapping media_id -> image URL or base64
conn.execute('''
CREATE TABLE IF NOT EXISTS chat_sessions(
    thread_id TEXT PRIMARY KEY,
    messages TEXT,
    summary TEXT,
    image_store TEXT
)''')
conn.commit()

# initialize Firebase only once
if not firebase_admin._apps:
    #Firebase init
    cred = credentials.Certificate(CRED_PATH)
    firebase_admin.initialize_app(cred)

# Firestore Client
fire_db = firestore.client()

# Fetching summary prompt
with open(SUMMARY_PROMPT_PATH,encoding="utf-8") as f:
    summary_prompt=f.read()

# Wrap the raw prompt text in a PromptTemplate
summarization_template = PromptTemplate(
    input_variables=["summary", "new_lines"],
    template=summary_prompt
)    

def load_memory(thread_id):
    """
    Retrieve and reconstruct ConversationSummaryBufferMemory object for a given thread_id.
    Loads both full message buffer and summary from DB if exists.
    """
    try:
        curr = conn.execute(
            "SELECT messages, summary FROM chat_sessions WHERE thread_id=?",
            (thread_id,)
        )
        row = curr.fetchone()

        # Create memory object with summarization model
        memory = ConversationSummaryBufferMemory(
            llm=llm,
            max_token_limit=3500,     # Token budget for summary
            return_messages=True,     # Ensures access to actual message objects
            buffer_size=10,            # Max number of exchanges stored before summarizing
            prompt=summarization_template
        )


        # If past conversation exists in DB, load messages and summary
        if row:
            msgs_json, summary = row
            if msgs_json:
                memory.chat_memory.messages = messages_from_dict(json.loads(msgs_json))
            if summary:
                memory.moving_summary_buffer = summary

        return memory
    except Exception as e:
        logging.warning(f"error occurred during loading memory : error {e}")
        raise customException(e,sys)        

def save_memory(thread_id, memory):
    """
    Persist the memory object to the database.
    Saves full buffer of messages (excluding last two system ones) and the moving summary.
    """
    try:
        msgs = memory.chat_memory.messages
        # Remove last two system messages (typically summary prompts/responses)
        msgs_json = json.dumps(messages_to_dict(msgs[:-2]))

        # Get the current summary string
        summary = memory.moving_summary_buffer or ""

        # Insert new or update existing chat session
        conn.execute(
            '''
            INSERT INTO chat_sessions (thread_id, messages, summary)
            VALUES (?, ?, ?)
            ON CONFLICT(thread_id) DO UPDATE SET
                messages = excluded.messages,
                summary = excluded.summary
            ''',
            (thread_id, msgs_json, summary)
        )
        conn.commit()

    except Exception as e:
        logging.warning(f"error occurred during saving memory : error {e}")
        raise customException(e,sys)   
    
    """
    Persist the memory object to Firestore.
    Saves full buffer of messages (excluding last two system ones) and the moving summary.
    """
    try:
        msgs = memory.chat_memory.messages
        msgs_json = json.dumps(messages_to_dict(msgs[:-2]))  # exclude system summary messages
        summary = memory.moving_summary_buffer or ""

        fire_db.collection("chat_sessions").document(thread_id).set({
            "messages": msgs_json,
            "summary": summary
        }, merge=True)

    except Exception as e:
        logging.warning(f"error occurred during saving memory in firestore : error {e}")
        raise customException(e, sys)

async def update_image_store(thread_id, image_store_data):
    """
    Store/update the image metadata for a conversation.
    Expects a dictionary of media_id → image URL or base64 data.
    """
    try:
        image_store_json = json.dumps(image_store_data)
        conn.execute(
            "INSERT INTO chat_sessions (thread_id, image_store) VALUES (?, ?)"
            "ON CONFLICT(thread_id) DO UPDATE SET image_store = excluded.image_store",
            (thread_id, image_store_json)
        )
        conn.commit()
    except Exception as e:
        logging.warning(f"error occurred during updating image store : error {e}")
        raise customException(e,sys)   

async def get_image_store(thread_id):
    """
    Retrieve image data for a given thread_id from the database.
    Returns a dictionary mapping media_id to image URL/base64 string.
    """
    try:
        cursor = conn.execute(
            "SELECT image_store FROM chat_sessions WHERE thread_id = ?",
            (thread_id,)
        )
        row = cursor.fetchone()
        if row and row[0]:
            return json.loads(row[0])
        return {}
    except Exception as e:
        logging.warning(f"error occurred during getting image store : error {e}")
        raise customException(e,sys)   
