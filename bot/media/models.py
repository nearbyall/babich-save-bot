from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from . import workspace


@dataclass
class MediaItem:
    """A downloaded picture or clip."""
    path: Path
    kind: Literal["photo", "video"]
    width: int | None = None
    height: int | None = None
    duration: int | None = None
    thumbnail: Path | None = None
    sound: bool = False

    @property
    def upload_size(self) -> int:
        return self.path.stat().st_size + (self.thumbnail.stat().st_size if self.thumbnail else 0)


@dataclass
class Audio:
    path: Path
    title: str | None = None
    performer: str | None = None
    duration: int | None = None


@dataclass(kw_only=True)
class Download:
    """Files of one link, kept in a work dir until they're uploaded."""
    workdir: Path
    uploader: str | None = None
    keys: list[str] = field(default_factory=list)

    def cleanup(self) -> None:
        workspace.remove(self.workdir)


@dataclass(kw_only=True)
class Video(Download):
    clip: MediaItem


@dataclass(kw_only=True)
class Album(Download):
    """An Instagram photo post or carousel, or a TikTok slideshow."""
    items: list[MediaItem]
    audio: Audio | None = None
