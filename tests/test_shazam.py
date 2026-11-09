import asyncio
import io
import time
import wave

import pytest

from bot.media import shazam
from bot.media.shazam import RATE, WINDOW, Track

ANSWER = {
    "title": "Monster (Rework)",
    "subtitle": "DotEXE",
    "url": "https://www.shazam.com/track/218265405/monster-rework",
    "images": {"coverart": "https://example.com/400.jpg", "coverarthq": "https://example.com/hq.jpg"},
    "hub": {"options": [{"actions": [
        {"type": "applemusicopen", "uri": "https://music.apple.com/gb/album/x?i=1"},
        {"type": "uri", "uri": "https://music.apple.com/gb/album/x?i=1"}]}]},
    "sections": [{"type": "SONG", "metadata": [{"title": "Album", "text": "Monster"},
                                                {"title": "Released", "text": "2026"}]},
                 {"type": "RELATED", "url": "https://example.com"}],
}


def test_parse_answer():
    assert shazam.parse(ANSWER) == Track(
        "Monster (Rework)", "DotEXE", "Monster", "2026", "https://example.com/hq.jpg",
        "https://www.shazam.com/track/218265405/monster-rework", "https://music.apple.com/gb/album/x?i=1")


def test_parse_minimal_answer():
    assert shazam.parse({"title": "T", "subtitle": "A"}) == Track("T", "A")


@pytest.mark.parametrize("duration, starts", [
    (8, [0]),
    (20, [4]),
    (24, [6, 0, 12]),
    (236, [112, 0, 224]),
])
def test_windows_start_in_the_middle(duration, starts):
    assert shazam.windows(duration) == starts


def test_wav_window():
    samples = bytes(30 * RATE * 2)
    with wave.open(io.BytesIO(shazam._wav(samples, 25))) as file:
        assert (file.getframerate(), file.getnchannels(), file.getnframes()) == (RATE, 1, 5 * RATE)
    with wave.open(io.BytesIO(shazam._wav(samples, 0))) as file:
        assert file.getnframes() == WINDOW * RATE


def test_throttle_spaces_requests_out():
    async def run():
        throttle = shazam._Throttle(rate=2, period=0.3)
        started = time.monotonic()
        for _ in range(3):
            await throttle.turn()
        third = time.monotonic() - started
        throttle.exhausted()
        await throttle.turn()
        return third, time.monotonic() - started - third

    third, after_rejection = asyncio.run(run())
    assert 0.25 < third < 0.5 and after_rejection > 0.25
