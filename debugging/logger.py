import logging
import os
from datetime import datetime
from config import log_path
from debugging.logshandler_class import FirebaseHandler

LOG_FILE=f"{datetime.now().strftime('%m_%d_%Y_%H_%M_%S')}.log"

os.makedirs(log_path,exist_ok=True)

LOG_FILEPATH=os.path.join(log_path,LOG_FILE)

logging.basicConfig(level=logging.INFO,
                    filename=LOG_FILEPATH,
                    format="[%(asctime)s] %(lineno)d %(name)s - %(levelname)s - %(message)s"
)

# Add Firebase handler
firebase_handler = FirebaseHandler(collection_name="app_logs")
logging.getLogger().addHandler(firebase_handler)