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

# Rumble
RUMBLE_EMAIL = os.getenv("RUMBLE_EMAIL", "")
RUMBLE_PASSWORD = os.getenv("RUMBLE_PASSWORD", "")
RUMBLE_CHANNEL_NAME = os.getenv("RUMBLE_CHANNEL_NAME", "")

# Telegram & Google Sheets (for later integration)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
GOOGLE_SHEET_URL = os.getenv("GOOGLE_SHEET_URL", "")

YOUTUBE_PLAYLIST_URL = os.getenv("YOUTUBE_PLAYLIST_URL", "")

# Odysee
ODYSEE_EMAIL = os.getenv("ODYSEE_EMAIL", "")
ODYSEE_PASSWORD = os.getenv("ODYSEE_PASSWORD", "")

# Year-specific playlist URLs (for multi-year pipelines)
YOUTUBE_PLAYLIST_URL_1999 = os.getenv("YOUTUBE_PLAYLIST_URL_1999", "")
YOUTUBE_PLAYLIST_URL_2000 = os.getenv("YOUTUBE_PLAYLIST_URL_2000", "")
YOUTUBE_PLAYLIST_URL_2001 = os.getenv("YOUTUBE_PLAYLIST_URL_2001", "")
YOUTUBE_PLAYLIST_URL_2002 = os.getenv("YOUTUBE_PLAYLIST_URL_2002", "")
YOUTUBE_PLAYLIST_URL_2003 = os.getenv("YOUTUBE_PLAYLIST_URL_2003", "")

# ---- Phase 2: Archive Backup Platforms ----

# pCloud
PCLOUD_EMAIL = os.getenv("PCLOUD_EMAIL", "")
PCLOUD_PASSWORD = os.getenv("PCLOUD_PASSWORD", "")

# Internxt
INTERNXT_EMAIL = os.getenv("INTERNXT_EMAIL", "")
INTERNXT_PASSWORD = os.getenv("INTERNXT_PASSWORD", "")

# Icedrive
ICEDRIVE_EMAIL = os.getenv("ICEDRIVE_EMAIL", "")
ICEDRIVE_PASSWORD = os.getenv("ICEDRIVE_PASSWORD", "")
ICEDRIVE_WEBDAV_URL = os.getenv("ICEDRIVE_WEBDAV_URL", "https://webdav.icedrive.io/")
ICEDRIVE_ACCESS_KEY = os.getenv("ICEDRIVE_ACCESS_KEY", "")  # WebDAV uses Access Key, not password

# Koofr
KOOFR_EMAIL = os.getenv("KOOFR_EMAIL", "")
KOOFR_PASSWORD = os.getenv("KOOFR_PASSWORD", "")

# NicoNico
NICONICO_EMAIL = os.getenv("NICONICO_EMAIL", "")
NICONICO_PASSWORD = os.getenv("NICONICO_PASSWORD", "")

# Bilibili
BILIBILI_EMAIL = os.getenv("BILIBILI_EMAIL", "")
BILIBILI_PASSWORD = os.getenv("BILIBILI_PASSWORD", "")
