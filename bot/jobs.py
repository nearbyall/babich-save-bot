"""Requests in progress, so a restart for a yt-dlp update can wait for them to finish."""
import contextlib

_active = 0


def active() -> int:
    return _active


@contextlib.contextmanager
def tracked():
    global _active
    _active += 1
    try:
        yield
    finally:
        _active -= 1
