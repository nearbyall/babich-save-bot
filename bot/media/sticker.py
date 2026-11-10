"""Video sticker cuts and their rendering to Telegram's format: WEBM/VP9 without sound, up to 3 s and 256 KB,
one side exactly 512 px."""
import logging
import re
import subprocess
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

from ..errors import UserError

log = logging.getLogger(__name__)

LENGTH = 3.0
MAX_SIZE = 256 * 1024
# Speed doubles and halves: x8 packs 24 s of video into a sticker, x0.25 stretches 0.75 s
MIN_SPEED, MAX_SPEED = 0.25, 8.0


class Shape(StrEnum):
    ORIGINAL = "o"
    SQUARE = "1"
    WIDE = "w"
    TALL = "t"
    ROUND = "r"

    @property
    def frame(self) -> tuple[int, int] | None:
        """Width and height to crop to; None keeps the video's proportions."""
        return _FRAMES[self]


_FRAMES = {Shape.ORIGINAL: None, Shape.SQUARE: (512, 512), Shape.WIDE: (512, 288), Shape.TALL: (288, 512),
           Shape.ROUND: (512, 512)}
# Drawn once and looped: computing the mask for every frame doubles the rendering time
_CIRCLE_MASK = ("color=black:s=512x512:d=1,format=gray,geq=lum='255*clip(256.5-hypot(X-255.5,Y-255.5),0,1)',"
                "trim=end_frame=1,loop=loop=-1:size=1")


@dataclass(frozen=True)
class Cut:
    """`length` seconds of sticker from `start` of the video, played at `speed`, framed as `shape`."""
    start: float = 0.0
    length: float = LENGTH
    speed: float = 1.0
    shape: Shape | None = None  # None: round for video notes, the original proportions for the rest

    @property
    def span(self) -> float:
        """Seconds of the video that go into the sticker."""
        return self.length * self.speed

    def framed(self, round_video: bool) -> "Cut":
        """The cut with the default shape filled in."""
        return self if self.shape else replace(self, shape=Shape.ROUND if round_video else Shape.ORIGINAL)

    @classmethod
    def covering(cls, start: float, span: float) -> "Cut":
        """A cut of `span` seconds of the video, sped up to fit into one sticker."""
        speed = 1.0
        while span / speed > LENGTH and speed < MAX_SPEED:
            speed *= 2
        return cls(start, min(span / speed, LENGTH), speed)


_TIME = r"(?:(\d{1,2}):)?(\d{1,3}(?:[.,]\d+)?)"
_TIME_RE = re.compile(rf"\s*{_TIME}(?:\s*[-–—]\s*{_TIME})?\s*")


def parse_time(text: str | None) -> tuple[float, float] | None:
    """"12", "0:12", "1:02.5" or a range "0:12-0:14" -> (start, seconds of video)."""
    m = _TIME_RE.fullmatch(text or "")
    if not m:
        return None
    start = int(m[1] or 0) * 60 + float(m[2].replace(",", "."))
    if not m[4]:
        return start, LENGTH
    end = int(m[3] or 0) * 60 + float(m[4].replace(",", "."))
    return (start, end - start) if end > start else None


def format_time(seconds: float) -> str:
    minutes, seconds = divmod(seconds, 60)
    return f"{int(minutes)}:{seconds:05.2f}".rstrip("0").rstrip(".")


def _filtergraph(cut: Cut) -> str:
    chain = [f"setpts=(PTS-STARTPTS)/{cut.speed:g}"] if cut.speed != 1 else []
    chain.append("fps=30")
    if frame := cut.shape.frame:
        width, height = frame
        chain.append(f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}")
    else:
        chain.append("scale=512:512:force_original_aspect_ratio=decrease:force_divisible_by=2")
    graph = "[0:v]" + ",".join(chain)
    if cut.shape == Shape.ROUND:
        graph += f",format=yuva420p[v];{_CIRCLE_MASK}[m];[v][m]alphamerge=shortest=1"
    return graph


def render(source: Path, dest: Path, cut: Cut) -> None:
    """Render a framed cut of the video into a sticker file, lowering the bitrate until it fits."""
    pix_fmt = "yuva420p" if cut.shape == Shape.ROUND else "yuv420p"
    # VP9 overshoots the target by ~20% on busy footage; aim low so most cuts fit on the first try
    bitrate = MAX_SIZE * 8 * 0.65 / cut.length
    for _ in range(3):
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-nostats", "-progress", "pipe:1", "-y",
             "-ss", f"{cut.start:.2f}", "-t", f"{cut.span:.3f}", "-i", str(source),
             "-filter_complex", _filtergraph(cut), "-t", f"{cut.length:.3f}", "-an", "-sn", "-map_metadata", "-1",
             "-c:v", "libvpx-vp9", "-pix_fmt", pix_fmt, "-crf", "30", "-b:v", str(int(bitrate)),
             "-deadline", "good", "-cpu-used", "4", "-row-mt", "1", str(dest)],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode:
            log.warning("sticker rendering failed: %s", result.stderr.strip()[-500:])
            raise UserError("sticker_render_failed")
        frames = re.findall(r"^frame=(\d+)", result.stdout, re.MULTILINE)
        if not frames or frames[-1] == "0":
            raise UserError("no_frames_here")
        size = dest.stat().st_size
        if size <= MAX_SIZE:
            return
        bitrate *= MAX_SIZE * 0.85 / size
    raise UserError("too_much_motion")
