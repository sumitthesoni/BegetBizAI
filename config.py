import os

# Base project directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Memory & Database
MEMORY_PATH = os.path.join(BASE_DIR, 'Memory')
DB_PATH = os.path.join(MEMORY_PATH, 'chat_memory.db')

# System Prompt
PROMPTS_PATH = os.path.join(BASE_DIR, 'Prompts')
SYSTEM_PROMPT_PATH=os.path.join(PROMPTS_PATH, 'system_prompt.txt')

# Summary Prompt
PROMPTS_PATH = os.path.join(BASE_DIR, 'Prompts')
SUMMARY_PROMPT_PATH=os.path.join(PROMPTS_PATH, 'summary_prompt.txt')

# Log Path
debugging_path=os.path.join(BASE_DIR, 'debugging')
log_path=os.path.join(debugging_path, 'logs.log')

# Operation team number
OPERATION_TEAM_NUMBER="917978022640"

# Firebase cred
CRED_PATH=os.path.join(BASE_DIR,'begetbiz-e3f35-firebase-adminsdk-fbsvc-0a2e7951dd.json')