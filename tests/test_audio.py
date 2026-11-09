import shutil
import subprocess

import pytest

from bot.errors import UserError
from bot.media import audio, ffmpeg

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")


def _video(path, sound_codec=None):
    inputs = ["-f", "lavfi", "-i", "testsrc2=s=320x240:r=10:d=3"]
    codec = []
    if sound_codec:
        inputs += ["-f", "lavfi", "-i", "sine=frequency=440:duration=3"]
        codec = ["-c:a", sound_codec]
    subprocess.run(["ffmpeg", "-v", "error", *inputs, "-c:v", "libx264", "-preset", "ultrafast", *codec,
                    "-shortest", str(path)], check=True)
    return path


@pytest.mark.parametrize("container, codec", [("mp4", "aac"), ("mkv", "libopus")])
def test_extract_keeps_aac_and_converts_the_rest(tmp_path, container, codec):
    video = _video(tmp_path / f"video.{container}", codec)
    sound = audio.extract(video, tmp_path / "sound.m4a", "Title", "Artist")
    streams = ffmpeg.probe(sound.path)
    assert (streams.audio, streams.width, sound.duration) == ("aac", None, 3)
    assert (sound.title, sound.performer) == ("Title", "Artist")


def test_pcm_is_mono_16_bit(tmp_path):
    samples = audio.pcm(_video(tmp_path / "video.mp4", "aac"), 16000)
    assert abs(len(samples) - 3 * 16000 * 2) < 16000


def test_silent_video_has_no_sound(tmp_path):
    video = _video(tmp_path / "silent.mp4")
    assert ffmpeg.probe(video).audio is None
    with pytest.raises(UserError):
        audio.extract(video, tmp_path / "sound.m4a", "Title", None)
    with pytest.raises(UserError):
        audio.pcm(video, 16000)
