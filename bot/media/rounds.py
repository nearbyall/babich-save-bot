"""Round video messages: a square H.264 clip of up to a minute, which Telegram shows as a circle."""
import logging
import subprocess
from pathlib import Path

from ..errors import UserError
from . import ffmpeg

log = logging.getLogger(__name__)

LENGTH = 60  # Telegram plays round videos of up to a minute
MAX_SIDE = 640
# The largest centered square, even-sided for H.264, scaled down to MAX_SIDE
_SQUARE = rf"crop=trunc(min(iw\,ih)/2)*2:trunc(min(iw\,ih)/2)*2,scale=min(iw\,{MAX_SIDE}):-2,setsar=1"


def render(source: Path, dest: Path, start: int) -> ffmpeg.Streams:
    """A minute of the video from `start` as a round video file, with its sound if it has any."""
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-ss", str(start), "-t", str(LENGTH), "-i", str(source),
         "-map", "0:v:0", "-map", "0:a:0?", "-vf", _SQUARE, "-fpsmax", "30",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-maxrate", "2M", "-bufsize", "4M",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-sn", "-dn", "-map_metadata", "-1",
         "-movflags", "+faststart", str(dest)],
        capture_output=True, text=True, timeout=180,
    )
    if result.returncode:
        log.warning("round video rendering failed: %s", result.stderr.strip()[-500:])
        raise UserError("Не получилось сделать кружок из этого видео.")
    streams = ffmpeg.probe(dest)
    if not streams.width:
        raise UserError("На этом месте в видео уже нет кадров.")
    return streams
