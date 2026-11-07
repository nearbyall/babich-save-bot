import os
import tempfile

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "1:test")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("TMP_DIR", tempfile.mkdtemp())
