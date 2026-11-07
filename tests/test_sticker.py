import re
import shutil
import subprocess

import pytest

from bot.errors import UserError
from bot.media.sticker import MAX_SIZE, Cut, Shape, format_time, parse_time, render


@pytest.mark.parametrize("text, expected", [
    ("12", (12.0, 3.0)),
    ("0:12", (12.0, 3.0)),
    ("1:02.5", (62.5, 3.0)),
    ("12,5", (12.5, 3.0)),
    (" 0:12 - 0:14 ", (12.0, 2.0)),
    ("0:14-0:12", None),
    ("abc", None),
    ("1:2:3", None),
])
def test_parse_time(text, expected):
    assert parse_time(text) == expected


@pytest.mark.parametrize("seconds, text", [(0, "0:00"), (3, "0:03"), (62.5, "1:02.5"), (6.75, "0:06.75")])
def test_format_time(seconds, text):
    assert format_time(seconds) == text


@pytest.mark.parametrize("span, length, speed", [(2, 2, 1), (3, 3, 1), (6, 3, 2), (10, 2.5, 4), (60, 3, 8)])
def test_long_ranges_speed_up_to_fit(span, length, speed):
    cut = Cut.covering(5, span)
    assert (cut.start, cut.length, cut.speed) == (5, length, speed)


def test_default_shape_depends_on_the_video():
    assert Cut().framed(round_video=True).shape == Shape.ROUND
    assert Cut().framed(round_video=False).shape == Shape.ORIGINAL
    assert Cut(shape=Shape.WIDE).framed(round_video=True).shape == Shape.WIDE


ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    path = tmp_path_factory.mktemp("clip") / "clip.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1080x1920:r=30:d=6",
                    "-c:v", "libx264", "-preset", "ultrafast", str(path)], check=True)
    return path


def _info(path):
    out = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path)], capture_output=True, text=True).stderr
    duration = float(re.search(r"Duration: 00:00:([\d.]+)", out)[1])
    size = re.search(r"Video: vp9.*?(\d+)x(\d+)", out)
    return duration, (int(size[1]), int(size[2])), "Audio:" in out, bool(re.search(r"alpha_mode\s*:\s*1", out))


@ffmpeg
@pytest.mark.parametrize("cut, frame, alpha", [
    (Cut(0, 3, 1, Shape.ORIGINAL), (288, 512), False),
    (Cut(1, 3, 2, Shape.WIDE), (512, 288), False),
    (Cut(0, 3, 0.25, Shape.ROUND), (512, 512), True),
])
def test_render_meets_telegram_rules(clip, tmp_path, cut, frame, alpha):
    dest = tmp_path / "sticker.webm"
    render(clip, dest, cut)
    duration, size, audio, has_alpha = _info(dest)
    assert duration <= 3.0 and dest.stat().st_size <= MAX_SIZE
    assert (size, audio, has_alpha) == (frame, False, alpha)


@ffmpeg
def test_render_past_the_end(clip, tmp_path):
    with pytest.raises(UserError):
        render(clip, tmp_path / "sticker.webm", Cut(30, 3, 1, Shape.ORIGINAL))
