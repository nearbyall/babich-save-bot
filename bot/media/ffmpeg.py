"""ffmpeg helpers (the image ships ffmpeg without ffprobe)."""
import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Streams:
    """Video size as displayed (rotation applied), duration in seconds and the sound's codec, if any."""
    width: int | None = None
    height: int | None = None
    duration: int | None = None
    audio: str | None = None


def probe(path: Path) -> Streams:
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path)],
                             capture_output=True, text=True, timeout=30).stderr
    except Exception:
        log.exception("ffmpeg probe failed for %s", path)
        return Streams()
    width = height = duration = None
    if m := re.search(r"Stream #.*?Video:.*?[ ,](\d{2,5})x(\d{2,5})[ ,\[]", out):
        width, height = int(m[1]), int(m[2])
        if (r := re.search(r"rotation of (-?[\d.]+) degrees", out)) and round(abs(float(r[1]))) % 180 == 90:
            width, height = height, width
    if m := re.search(r"Duration: (\d+):(\d\d):(\d\d(?:\.\d+)?)", out):
        duration = round(int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]))
    audio = re.search(r"Stream #.*?Audio: (\w+)", out)
    return Streams(width, height, duration, audio and audio[1])


def thumbnail(video: Path, width: int | None, height: int | None, dest: Path | None = None) -> Path | None:
    """A JPEG preview up to 320 px on the longest side, as Telegram wants it."""
    thumb = dest or video.with_name(f"{video.stem}.thumb.jpg")
    scale = "320:-2" if (width or 0) >= (height or 0) else "-2:320"
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "0.3", "-i", str(video), "-frames:v", "1",
                        "-vf", f"scale={scale}", "-q:v", "5", str(thumb)],
                       capture_output=True, timeout=30, check=True)
    except Exception:
        log.warning("thumbnail generation failed for %s", video)
        return None
    return thumb if thumb.is_file() and thumb.stat().st_size < 200_000 else None


def to_jpeg(source: Path, dest: Path) -> bool:
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(source), "-q:v", "2", str(dest)],
                       capture_output=True, timeout=60, check=True)
        return True
    except Exception:
        return False
