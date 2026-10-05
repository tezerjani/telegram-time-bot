import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Required Environment Variables
BOT_TOKEN = os.getenv('BOT_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
TURSO_DATABASE_URL = os.getenv('TURSO_DATABASE_URL')
TURSO_AUTH_TOKEN = os.getenv('TURSO_AUTH_TOKEN')
ADMIN_ID_STR = os.getenv('ADMIN_ID')
ADMIN_ID = int(ADMIN_ID_STR) if ADMIN_ID_STR and ADMIN_ID_STR.isdigit() else None

# Optional Environment Variables with Defaults
TIMEZONE = os.getenv('TIMEZONE', 'Asia/Tehran')
PORT = int(os.getenv('PORT', 8000))

# Global Constants
GEMINI_MODEL = 'gemini-2.5-flash'
MAX_RETRIES = 5
BASE_BACKOFF = 1.0
MAX_BACKOFF = 60.0
TASK_UPDATE_INTERVAL_MINUTES = 12
EPHEMERAL_TTL_SECONDS = 60
DAILY_POSTER_BG = 'assets/background.jpg'
FONT_PATH = 'assets/font.ttf'
WEEKLY_FONT_PATH = 'assets/font.ttf'


def validate_config() -> None:
    """
    Validates that all required environment variables are set.
    Raises ValueError if any are missing.
    """
    missing_vars = []
    
    if not BOT_TOKEN:
        missing_vars.append('BOT_TOKEN')
    if not GEMINI_API_KEY:
        missing_vars.append('GEMINI_API_KEY')
    if not TURSO_DATABASE_URL:
        missing_vars.append('TURSO_DATABASE_URL')
    if not TURSO_AUTH_TOKEN:
        missing_vars.append('TURSO_AUTH_TOKEN')
    if not ADMIN_ID:
        missing_vars.append('ADMIN_ID (must be a valid integer)')
        
    if missing_vars:
        raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

# Call validate_config() explicitly from main.py, not at import time
