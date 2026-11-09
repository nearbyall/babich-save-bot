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
