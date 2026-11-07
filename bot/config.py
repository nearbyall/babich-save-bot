import os
from pathlib import Path

MB = 1024 * 1024


def _optional_int(name: str) -> int | None:
    value = os.getenv(name, "").strip()
    return int(value) if value else None


TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
DB_PATH = DATA_DIR / "bot.sqlite3"
# Netscape-format cookies for Instagram posts that need a login
COOKIES_FILE = DATA_DIR / "cookies.txt"
YTDLP_CACHE_DIR = DATA_DIR / "yt-dlp-cache"
TMP_DIR = Path(os.getenv("TMP_DIR", "/tmp/babichsavebot"))

# Inline messages can't take uploads: files go to this chat first (a private channel with the bot as admin),
# else to the requester's or the owner's DM, and get deleted there right away
STORAGE_CHAT_ID = _optional_int("STORAGE_CHAT_ID")
# Defaults to the first user who writes the bot in DM
OWNER_ID = _optional_int("OWNER_ID")

MAX_FILE_SIZE = int(float(os.getenv("MAX_FILE_SIZE_MB", "49.5")) * MB)  # Bot API upload limit is 50 MB
MAX_PHOTO_SIZE = 10 * MB
MAX_DURATION = int(os.getenv("MAX_DURATION_SEC", str(10 * 60)))
MAX_LINKS_PER_MESSAGE = 5
MAX_POST_ITEMS = 35  # TikTok slideshows hold up to 35 pictures, Instagram carousels up to 20

MAX_PARALLEL_DOWNLOADS = int(os.getenv("MAX_PARALLEL_DOWNLOADS", "2"))
# Each YouTube download runs a ~250 MB deno process to solve its challenges
MAX_PARALLEL_YOUTUBE = int(os.getenv("MAX_PARALLEL_YOUTUBE", "1"))
MAX_PARALLEL_STICKERS = int(os.getenv("MAX_PARALLEL_STICKERS", "2"))
MAX_QUEUE = int(os.getenv("MAX_QUEUE", "12"))
MAX_JOBS_PER_USER = int(os.getenv("MAX_JOBS_PER_USER", "3"))
DOWNLOAD_TIMEOUT = int(os.getenv("DOWNLOAD_TIMEOUT_SEC", "180"))
MIN_FREE_DISK = int(os.getenv("MIN_FREE_DISK_MB", "1024")) * MB

HOUSEKEEPING_INTERVAL = 10 * 60
STALE_TMP_AGE = 15 * 60
CACHE_TTL_DAYS = int(os.getenv("CACHE_TTL_DAYS", "30"))
CACHE_MAX_ROWS = int(os.getenv("CACHE_MAX_ROWS", "20000"))
YTDLP_CACHE_TTL_DAYS = 7
YTDLP_UPDATE_CHECK_INTERVAL = 6 * 3600

# How long an inline query waits for a download before answering with a placeholder
INLINE_WAIT = float(os.getenv("INLINE_WAIT_SEC", "5"))
