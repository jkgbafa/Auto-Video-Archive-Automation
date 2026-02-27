import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Common Configuration
DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")

# Ensure download directory exists
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# Dailymotion
DAILYMOTION_USERNAME = os.getenv("DAILYMOTION_USERNAME", "")
DAILYMOTION_PASSWORD = os.getenv("DAILYMOTION_PASSWORD", "")
DAILYMOTION_API_KEY = os.getenv("DAILYMOTION_API_KEY", "")
DAILYMOTION_API_SECRET = os.getenv("DAILYMOTION_API_SECRET", "")
DAILYMOTION_REFRESH_TOKEN = os.getenv("DAILYMOTION_REFRESH_TOKEN", "")

# Bitchute
BITCHUTE_USERNAME = os.getenv("BITCHUTE_USERNAME", "")
BITCHUTE_PASSWORD = os.getenv("BITCHUTE_PASSWORD", "")

# Telegram & Google Sheets (for later integration)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
GOOGLE_SHEET_URL = os.getenv("GOOGLE_SHEET_URL", "")

YOUTUBE_PLAYLIST_URL = os.getenv("YOUTUBE_PLAYLIST_URL", "")
