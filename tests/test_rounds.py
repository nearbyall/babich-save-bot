import shutil
import subprocess

import pytest

from bot.errors import UserError
from bot.media import rounds

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")


def _video(path, size, seconds, sound=True):
    inputs = ["-f", "lavfi", "-i", f"testsrc2=s={size}:r=10:d={seconds}"]
    if sound:
        inputs += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    subprocess.run(["ffmpeg", "-v", "error", *inputs, "-c:v", "libx264", "-preset", "ultrafast", "-shortest",
                    str(path)], check=True)
    return path


def test_tall_video_becomes_a_square_with_sound(tmp_path):
    made = rounds.render(_video(tmp_path / "tall.mp4", "720x1280", 3), tmp_path / "round.mp4", 0)
    assert (made.width, made.height, made.duration, made.audio) == (rounds.MAX_SIDE, rounds.MAX_SIDE, 3, "aac")


def test_small_odd_silent_video_keeps_its_size(tmp_path):
    made = rounds.render(_video(tmp_path / "odd.mp4", "301x405", 2, sound=False), tmp_path / "round.mp4", 0)
    assert (made.width, made.height, made.audio) == (300, 300, None)


def test_a_round_holds_a_minute(tmp_path):
    video = _video(tmp_path / "long.mp4", "160x120", rounds.LENGTH + 5)
    assert rounds.render(video, tmp_path / "first.mp4", 0).duration == rounds.LENGTH
    assert rounds.render(video, tmp_path / "rest.mp4", rounds.LENGTH).duration == 5


def test_render_past_the_end(tmp_path):
    with pytest.raises(UserError):
        rounds.render(_video(tmp_path / "short.mp4", "160x120", 2), tmp_path / "round.mp4", 10)
