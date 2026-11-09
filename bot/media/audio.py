"""The sound of a video."""
import subprocess
from pathlib import Path

from ..errors import UserError
from . import ffmpeg
from .models import Audio


def extract(video: Path, dest: Path, title: str, performer: str | None) -> Audio:
    """The sound as an M4A file: AAC is copied as is, anything else re-encoded."""
    streams = _with_sound(video)
    codec = ["-c:a", "copy"] if streams.audio == "aac" else ["-c:a", "aac", "-b:a", "192k"]
    tags = ["-metadata", f"title={title}"] + (["-metadata", f"artist={performer}"] if performer else [])
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-map", "0:a:0", "-map_metadata", "-1",
                    *codec, *tags, "-movflags", "+faststart", str(dest)],
                   capture_output=True, timeout=120, check=True)
    return Audio(dest, title=title, performer=performer, duration=streams.duration)


def pcm(video: Path, rate: int) -> bytes:
    """The sound as 16-bit mono samples."""
    _with_sound(video)
    return subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-map", "0:a:0", "-ac", "1", "-ar", str(rate),
                           "-f", "s16le", "pipe:1"], capture_output=True, timeout=120, check=True).stdout


def _with_sound(video: Path) -> ffmpeg.Streams:
    streams = ffmpeg.probe(video)
    if not streams.audio:
        raise UserError("В этом видео нет звука.")
    return streams
