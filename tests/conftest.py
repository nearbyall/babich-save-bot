import os
import tempfile

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "1:test")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("TMP_DIR", tempfile.mkdtemp())

import pytest  # noqa: E402

from bot import i18n  # noqa: E402


@pytest.fixture
def english():
    """Run the test as a user who picked English."""
    token = i18n.current.set("en")
    yield
    i18n.current.reset(token)
