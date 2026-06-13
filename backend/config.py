import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (parent of backend/)
load_dotenv(Path(__file__).parent.parent / ".env")

BASE_DIR = Path(__file__).parent
DOWNLOADS_DIR = BASE_DIR / "downloads"
DOWNLOADS_DIR.mkdir(exist_ok=True)

FRONTEND_DIR = BASE_DIR.parent / "frontend"

# Files older than this are deleted by the cleanup service (seconds)
FILE_TTL = 3600  # 1 hour

# Public base URL — used by the Telegram bot when files are too large to upload
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

MAX_WORKERS = 3

# Optional: path to a Netscape-format cookies file for Instagram (and other
# platforms that require auth from server IPs).
# Place the file at this path on the server to enable authenticated downloads.
INSTAGRAM_COOKIES_FILE = BASE_DIR.parent / "instagram_cookies.txt"
YOUTUBE_COOKIES_FILE = BASE_DIR.parent / "youtube_cookies.txt"

# PostgreSQL
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://videograb:vg_db_s3cure_2024@localhost/videograb")

# Instagram Messaging API
IG_APP_ID             = os.getenv("IG_APP_ID", "")
IG_APP_SECRET         = os.getenv("IG_APP_SECRET", "")
IG_PAGE_ACCESS_TOKEN  = os.getenv("IG_PAGE_ACCESS_TOKEN", "")
IG_ACCOUNT_ID         = os.getenv("IG_ACCOUNT_ID", "")
IG_WEBHOOK_VERIFY_TOKEN = os.getenv("IG_WEBHOOK_VERIFY_TOKEN", "videograb_webhook_2024")
