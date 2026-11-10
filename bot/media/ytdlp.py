"""yt-dlp: options, user-facing errors, fetching clips and pictures."""
import copy
import itertools
import logging
import shutil
import time
from pathlib import Path

import yt_dlp
from yt_dlp.networking import Request
from yt_dlp.utils import url_or_none

from .. import config
from ..errors import UserError
from ..links import Link
from . import ffmpeg
from .models import MediaItem

log = logging.getLogger(__name__)

# Telegram plays H.264/AAC in MP4 everywhere; the resolution steps down until the file fits the upload limit
_RESOLUTIONS = (1080, 720, 480)


class _Logger:
    def debug(self, msg: str) -> None:
        pass

    def info(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        log.debug("yt-dlp: %s", msg)

    def error(self, msg: str) -> None:
        log.info("yt-dlp: %s", msg)


def user_error(err: Exception) -> UserError:
    text = str(err).lower()
    if any(s in text for s in ("ip address is blocked", "your country", "your location")):
        return UserError("geo_blocked")
    if "not a bot" in text:
        return UserError("youtube_blocked")
    if any(s in text for s in ("login", "private", "rate-limit", "cookies", "sign in")):
        return UserError("login_required")
    if "no video" in text:
        return UserError("no_video_in_post")
    if "unsupported url" in text:
        return UserError("unsupported_link")
    if any(s in text for s in ("unavailable", "not exist", "removed", "deleted", "404", "not found")):
        return UserError("video_unavailable")
    return UserError("download_failed")


def _too_long() -> UserError:
    return UserError("too_long", minutes=config.MAX_DURATION // 60)


def _skip_long(info: dict, *, incomplete: bool) -> str | None:
    return "too long" if (info.get("duration") or 0) > config.MAX_DURATION else None


def _format_sort(resolution: int) -> list[str]:
    return ["vcodec:h264", f"res:{resolution}", "acodec:aac", "ext:mp4:m4a"]


def options(workdir: Path, deadline: float) -> dict:
    def enforce_deadline(_progress: dict) -> None:
        if time.monotonic() > deadline:
            raise yt_dlp.utils.DownloadCancelled("download timeout")

    opts = {
        "outtmpl": str(workdir / "%(id)s.%(ext)s"),
        "paths": {"temp": str(workdir)},
        "format": "bv*+ba/b",
        "format_sort": _format_sort(_RESOLUTIONS[0]),
        "merge_output_format": "mp4",
        "postprocessors": [{"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"}],
        "max_filesize": config.MAX_FILE_SIZE,
        "match_filter": _skip_long,
        "progress_hooks": [enforce_deadline],
        "noplaylist": True,
        # Photo posts have no formats and are fetched by hand
        "ignore_no_formats_error": True,
        "quiet": True,
        "noprogress": True,
        "no_warnings": True,
        "logger": _Logger(),
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
        "concurrent_fragment_downloads": 1,
        "cachedir": str(config.YTDLP_CACHE_DIR),
    }
    if config.COOKIES_FILE.is_file():
        # yt-dlp writes cookies back on exit, so every run gets its own copy
        cookies = workdir / "cookies.txt"
        shutil.copyfile(config.COOKIES_FILE, cookies)
        opts["cookiefile"] = str(cookies)
    return opts


def uploader(info: dict) -> str | None:
    return info.get("uploader") or info.get("channel") or info.get("uploader_id")


def cache_keys(link: Link, info: dict) -> list[str]:
    keys = [link.key]
    if info.get("extractor_key") and info.get("id"):
        keys.append(f"{info['extractor_key'].lower()}:{info['id']}")
    return keys


def has_video(entry: dict) -> bool:
    if entry.get("_type") in ("url", "url_transparent"):
        return True
    formats = entry.get("formats") or ([entry] if entry.get("url") else [])
    return any(f.get("vcodec") != "none" for f in formats)


def entries(info: dict) -> list[dict]:
    if info.get("_type") != "playlist":
        return [info]
    items = [e for e in itertools.islice(info.get("entries") or [], config.MAX_POST_ITEMS) if e]
    for item in items:
        if item.get("_type") in ("url", "url_transparent"):
            continue
        # Carousel items lack the fields yt-dlp needs to download them
        for k in ("extractor", "extractor_key", "webpage_url", "webpage_url_basename",
                  "webpage_url_domain", "original_url"):
            item.setdefault(k, info.get(k))
    return items


def fetch_video(ydl: yt_dlp.YoutubeDL, entry: dict) -> tuple[MediaItem, dict]:
    """Download one clip in the best quality that fits the upload limit."""
    if (entry.get("duration") or 0) > config.MAX_DURATION:
        raise _too_long()
    for resolution in _RESOLUTIONS:
        ydl.params["format_sort"] = _format_sort(resolution)
        try:
            info = ydl.process_ie_result(copy.deepcopy(entry), download=True)
        except yt_dlp.utils.DownloadCancelled as e:
            raise UserError("download_too_slow") from e
        except yt_dlp.utils.DownloadError as e:
            log.info("download failed for %s: %s", entry.get("webpage_url"), e)
            raise user_error(e) from e
        if (info.get("duration") or 0) > config.MAX_DURATION:
            raise _too_long()
        files = [Path(d["filepath"]) for d in info.get("requested_downloads") or [] if d.get("filepath")]
        files = [f for f in files if f.is_file()]
        if files and files[0].stat().st_size <= config.MAX_FILE_SIZE:
            return _clip(files[0], info), info
        for f in files:
            f.unlink(missing_ok=True)
        log.info("%s too big at %sp, retrying lower", entry.get("webpage_url"), resolution)
    raise UserError("too_big")


def _clip(path: Path, info: dict) -> MediaItem:
    streams = ffmpeg.probe(path)
    return MediaItem(
        path=path,
        kind="video",
        width=streams.width or info.get("width"),
        height=streams.height or info.get("height"),
        duration=streams.duration or (round(info["duration"]) if info.get("duration") else None),
        thumbnail=ffmpeg.thumbnail(path, streams.width, streams.height),
        sound=streams.audio is not None,
    )


def fetch_bytes(ydl: yt_dlp.YoutubeDL, url: str, headers: dict, limit: int) -> bytes | None:
    """The response body, or None if the request fails or the body is over the limit."""
    try:
        with ydl.urlopen(Request(url, headers=headers)) as resp:
            data = resp.read(limit + 1)
    except Exception as e:
        log.info("request failed (%s…): %s", url[:80], e)
        return None
    if len(data) > limit:
        log.info("response too big (%s…)", url[:80])
        return None
    return data


def fetch_photo(ydl: yt_dlp.YoutubeDL, urls: list[str], dest: Path, headers: dict) -> MediaItem | None:
    """The first of the URLs that downloads, saved as a JPEG or PNG, which Telegram takes as a photo."""
    for url in urls:
        data = fetch_bytes(ydl, url, headers, config.MAX_PHOTO_SIZE)
        if data is None:
            continue
        if data.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")):
            dest.write_bytes(data)
            return MediaItem(dest, "photo")
        source = dest.with_suffix(".src")
        source.write_bytes(data)
        converted = ffmpeg.to_jpeg(source, dest)
        source.unlink(missing_ok=True)
        if converted:
            return MediaItem(dest, "photo")
        log.info("can't convert photo (%s…)", url[:80])
    return None


def photo_urls(entry: dict) -> list[str]:
    """Largest first; Instagram gives no sizes but lists the original last."""
    thumbs = [t for t in entry.get("thumbnails") or [] if url_or_none(t.get("url"))]
    thumbs.sort(key=lambda t: (t.get("width") or 0) * (t.get("height") or 0))
    urls = [t["url"] for t in reversed(thumbs)]
    if url_or_none(entry.get("thumbnail")):
        urls.append(entry["thumbnail"])
    return list(dict.fromkeys(urls))[:3]
