"""Jobs in progress: counted so a restart for a yt-dlp update can wait for them, and kept from piling up."""
import asyncio
import contextlib

from . import config

_active = 0
renders = asyncio.Semaphore(config.MAX_PARALLEL_RENDERS)


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


class Busy:
    """Users with a job of one kind running, so repeated taps don't start it again."""

    def __init__(self) -> None:
        self._users: set[int] = set()

    def __contains__(self, user_id: int) -> bool:
        return user_id in self._users

    @contextlib.contextmanager
    def hold(self, user_id: int):
        self._users.add(user_id)
        try:
            yield
        finally:
            self._users.discard(user_id)
