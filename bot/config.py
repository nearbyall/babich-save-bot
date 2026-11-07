import os
from pathlib import Path

MB = 1024 * 1024


def _optional_int(name: str) -> int | None:
    value = os.getenv(name, "").strip()
    return int(value) if value else None


TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
DB_PATH = DATA_DIR / "bot.sqlite3"
# Optional Netscape-format cookies (e.g. for Instagram posts that need a login)
COOKIES_FILE = DATA_DIR / "cookies.txt"
YTDLP_CACHE_DIR = DATA_DIR / "yt-dlp-cache"
TMP_DIR = Path(os.getenv("TMP_DIR", "/tmp/babichsavebot"))

# Chat the bot can upload videos to in order to get a file_id for guest/inline
# replies (inline messages can't receive new uploads). A private channel with
# the bot as admin is ideal; without it the caller's / owner's DM is used.
STORAGE_CHAT_ID = _optional_int("STORAGE_CHAT_ID")
# Fallback upload target; defaults to the first user who wrote the bot in DM.
OWNER_ID = _optional_int("OWNER_ID")

# Bot API upload limit is 50 MB
MAX_FILE_SIZE = int(float(os.getenv("MAX_FILE_SIZE_MB", "49.5")) * MB)
MAX_DURATION = int(os.getenv("MAX_DURATION_SEC", str(10 * 60)))
MAX_LINKS_PER_MESSAGE = 5
# Photo posts: TikTok slideshows hold up to 35 pictures, Instagram carousels up to 20
MAX_POST_ITEMS = 35
MAX_PHOTO_SIZE = 10 * MB  # Bot API limit for photos

# --- Protecting the host ---
MAX_PARALLEL_DOWNLOADS = int(os.getenv("MAX_PARALLEL_DOWNLOADS", "2"))
# YouTube runs a deno process (~250 MB) to solve its challenges, so it gets its own cap
MAX_PARALLEL_YOUTUBE = int(os.getenv("MAX_PARALLEL_YOUTUBE", "1"))
# Video sticker encoding (VP9, ~2 s of one core each)
MAX_PARALLEL_STICKERS = int(os.getenv("MAX_PARALLEL_STICKERS", "2"))
# Requests in flight (running + waiting); beyond that users get "busy"
MAX_QUEUE = int(os.getenv("MAX_QUEUE", "12"))
MAX_JOBS_PER_USER = int(os.getenv("MAX_JOBS_PER_USER", "3"))
# Hard cap on the transfer phase of one download
DOWNLOAD_TIMEOUT = int(os.getenv("DOWNLOAD_TIMEOUT_SEC", "180"))
# Stop downloading when the disk gets this full
MIN_FREE_DISK = int(os.getenv("MIN_FREE_DISK_MB", "1024")) * MB

HOUSEKEEPING_INTERVAL = 10 * 60
# Temp dirs left behind by crashes are removed after this long
STALE_TMP_AGE = 15 * 60
CACHE_TTL_DAYS = int(os.getenv("CACHE_TTL_DAYS", "30"))
CACHE_MAX_ROWS = int(os.getenv("CACHE_MAX_ROWS", "20000"))
YTDLP_CACHE_TTL_DAYS = 7

# How long an inline query waits for a fresh download before falling back
# to a placeholder that gets replaced with the video once it's ready
INLINE_WAIT = float(os.getenv("INLINE_WAIT_SEC", "5"))
