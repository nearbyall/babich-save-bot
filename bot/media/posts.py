"""Photo posts: Instagram photos and carousels, TikTok slideshows."""
import logging
import re
import time
from pathlib import Path

import yt_dlp
from yt_dlp.utils import int_or_none, traverse_obj, url_or_none

from .. import config
from ..errors import UserError
from ..links import Link
from . import ytdlp
from .models import Album, Audio

log = logging.getLogger(__name__)

_TIKTOK_HEADERS = {"Referer": "https://www.tiktok.com/"}


def _check_deadline(deadline: float) -> None:
    if time.monotonic() > deadline:
        raise UserError("Пост качается слишком долго, попробуй позже.")


def instagram_post(ydl: yt_dlp.YoutubeDL, link: Link, info: dict, entries: list[dict],
                   workdir: Path, deadline: float) -> Album:
    # Carousel clips come as a 360p DASH stream plus progressive files of unknown size that are really
    # 720p with sound; yt-dlp ranks the known 360p higher, so pick a progressive file first
    ydl.format_selector = ydl.build_format_selector("b/bv*+ba")
    items = []
    for i, entry in enumerate(entries):
        _check_deadline(deadline)
        try:
            if ytdlp.has_video(entry):
                items.append(ytdlp.fetch_video(ydl, entry)[0])
            elif photo := ytdlp.fetch_photo(ydl, ytdlp.photo_urls(entry), workdir / f"{i:02d}.jpg",
                                            entry.get("http_headers") or {}):
                items.append(photo)
        except UserError as e:
            if len(entries) == 1:
                raise
            log.info("skipping item %d of %s: %s", i, link.url, e)
    if not items:
        raise UserError("Не получилось скачать ни одного фото или видео из поста.")
    return Album(items=items, workdir=workdir, uploader=ytdlp.uploader(info), keys=ytdlp.cache_keys(link, info))


def tiktok_slideshow(ydl: yt_dlp.YoutubeDL, link: Link, video_id: str, workdir: Path,
                     deadline: float) -> Album | None:
    """yt-dlp only sees the soundtrack of a slideshow; the pictures are in the web page data."""
    ie = ydl.get_info_extractor("TikTok")
    try:
        data, _ = ie._extract_web_data_and_status(ie._create_url(None, video_id), video_id, fatal=False)
    except Exception:
        log.warning("can't get TikTok page data for %s", video_id, exc_info=True)
        return None
    images = traverse_obj(data, ("imagePost", "images", ..., "imageURL", "urlList", {list}))
    if not images:
        return None
    items = []
    for i, urls in enumerate(images[: config.MAX_POST_ITEMS]):
        _check_deadline(deadline)
        urls = sorted(filter(url_or_none, urls), key=lambda u: not re.search(r"\.jpe?g\b", u))
        if photo := ytdlp.fetch_photo(ydl, urls, workdir / f"{i:02d}.jpg", _TIKTOK_HEADERS):
            items.append(photo)
    if not items:
        return None
    return Album(items=items, workdir=workdir, uploader=traverse_obj(data, ("author", "uniqueId", {str})),
                 keys=[link.key, f"tiktok:{video_id}"], audio=_soundtrack(ydl, data.get("music") or {}, workdir))


def _soundtrack(ydl: yt_dlp.YoutubeDL, music: dict, workdir: Path) -> Audio | None:
    if not (url := url_or_none(music.get("playUrl"))):
        return None
    if (sound := ytdlp.fetch_bytes(ydl, url, _TIKTOK_HEADERS, config.MAX_FILE_SIZE)) is None:
        return None
    path = workdir / "music.mp3"
    path.write_bytes(sound)
    return Audio(path, title=music.get("title"), performer=music.get("authorName"),
                 duration=int_or_none(music.get("duration")))
