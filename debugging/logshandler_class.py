import logging
from datetime import datetime

# Firebase logging
import firebase_admin
from firebase_admin import credentials, firestore
from config import CRED_PATH

# initialize Firebase only once
if not firebase_admin._apps:
    cred = credentials.Certificate(CRED_PATH)
    firebase_admin.initialize_app(cred)

db = firestore.client()

class FirebaseHandler(logging.Handler):
    def __init__(self, collection_name="logs"):
        super().__init__()
        self.collection = db.collection(collection_name)

    def emit(self, record):
        log_entry = {
            "level": record.levelname,
            "message": record.getMessage(),
            "created_at": datetime.utcnow().isoformat(),
            "filename": record.filename,
            "line_no": record.lineno,
            "function": record.funcName,
        }
        try:
            self.collection.add(log_entry)
        except Exception as e:
            print(f"Error saving log to Firestore: {e}")
