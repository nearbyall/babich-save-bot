"""Recognizing the music in a video through Shazam's unofficial API."""
import asyncio
import io
import logging
import time
import wave
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import aiohttp
from aiohttp_retry import ExponentialRetry
from shazamio import HTTPClient, Shazam
from shazamio.exceptions import BadResponseStatus, FailedDecodeJson, RateLimited
from shazamio_core import SignatureError

from ..errors import UserError
from . import audio

log = logging.getLogger(__name__)

RATE = 16000
WINDOW = 12  # seconds of sound per request, as the Shazam apps send
# Shazam answers about 3 requests a minute from one address and rejects the rest with 429
REQUESTS_PER_PERIOD, PERIOD = 3, 60.0
TIMEOUT = 100  # for a whole recognition, waiting for a turn included


@dataclass(frozen=True)
class Track:
    title: str
    artist: str
    album: str | None = None
    released: str | None = None
    cover: str | None = None
    shazam_url: str | None = None
    apple_music_url: str | None = None


class _Throttle:
    """Spaces out requests to stay within Shazam's rate limit."""

    def __init__(self, rate: int, period: float) -> None:
        self._sent: deque[float] = deque(maxlen=rate)
        self._period = period
        self._lock = asyncio.Lock()

    async def turn(self) -> None:
        async with self._lock:
            if len(self._sent) == self._sent.maxlen:
                await asyncio.sleep(self._sent[0] + self._period - time.monotonic())
            self._sent.append(time.monotonic())

    def exhausted(self) -> None:
        """Shazam rejected a request: hold off for a whole period."""
        self._sent.extend([time.monotonic()] * self._sent.maxlen)


_throttle = _Throttle(REQUESTS_PER_PERIOD, PERIOD)


def windows(duration: float) -> list[float]:
    """Where to listen, in turn: the middle as the Shazam apps do, then the start and the end."""
    starts: list[float] = []
    for start in (duration / 2 - WINDOW / 2, 0.0, duration - WINDOW):
        start = max(0.0, start)
        if all(abs(start - other) >= WINDOW / 2 for other in starts):
            starts.append(start)
    return starts


def parse(track: dict) -> Track:
    metadata = {item.get("title"): item.get("text")
                for section in track.get("sections") or [] for item in section.get("metadata") or []}
    images = track.get("images") or {}
    apple_music = next((action["uri"] for option in (track.get("hub") or {}).get("options") or []
                        for action in option.get("actions") or []
                        if action.get("type") == "applemusicopen" and action.get("uri", "").startswith("https://")),
                       None)
    return Track(title=track["title"], artist=track.get("subtitle") or "", album=metadata.get("Album"),
                 released=metadata.get("Released"), cover=images.get("coverarthq") or images.get("coverart"),
                 shazam_url=track.get("url"), apple_music_url=apple_music)


async def recognize(video: Path) -> Track | None:
    """The track playing in the video, or None when Shazam doesn't know it."""
    samples = await asyncio.to_thread(audio.pcm, video, RATE)
    try:
        async with asyncio.timeout(TIMEOUT), HTTPClient(retry_options=ExponentialRetry(attempts=1)) as client:
            shazam = Shazam(http_client=client)
            for start in windows(len(samples) / (2 * RATE)):
                if track := await _ask(shazam, _wav(samples, start)):
                    return track
    except TimeoutError as e:
        raise UserError("Shazam сейчас перегружен — попробуй через минуту.") from e
    return None


async def _ask(shazam: Shazam, wav: bytes) -> Track | None:
    while True:
        await _throttle.turn()
        try:
            answer = await shazam.recognize(wav)
        except RateLimited:
            log.info("Shazam rate limit hit, waiting")
            _throttle.exhausted()
            continue
        except SignatureError:  # too little sound to fingerprint
            return None
        except (aiohttp.ClientError, BadResponseStatus, FailedDecodeJson) as e:
            log.warning("Shazam request failed: %s", e)
            raise UserError("Shazam не отвечает — попробуй позже.") from e
        return parse(answer["track"]) if answer.get("track") else None


def _wav(samples: bytes, start: float) -> bytes:
    begin = int(start * RATE) * 2
    out = io.BytesIO()
    with wave.open(out, "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(RATE)
        file.writeframes(samples[begin:begin + WINDOW * RATE * 2])
    return out.getvalue()
