import asyncio
import contextlib
import copy
import itertools
import logging
import re
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit

import aiohttp
import yt_dlp
from yt_dlp.networking import Request
from yt_dlp.utils import int_or_none, traverse_obj, url_or_none

from . import config
from .links import Link, find_links

log = logging.getLogger(__name__)

_semaphore = asyncio.Semaphore(config.MAX_PARALLEL_DOWNLOADS)
_youtube_slots = asyncio.Semaphore(config.MAX_PARALLEL_YOUTUBE)
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)
# Telegram plays H.264/AAC in MP4 everywhere; prefer it and shrink if too big
_RESOLUTIONS = (1080, 720, 480)
_TIKTOK_HEADERS = {"Referer": "https://www.tiktok.com/"}

# Work dirs still in use (download running or file not yet uploaded); cleanup skips them
_active_dirs: set[Path] = set()
_jobs_total = 0
_jobs_by_user: dict[int, int] = {}


class DownloadError(Exception):
    """Error whose text is safe to show to the user."""


@dataclass
class Video:
    path: Path
    workdir: Path
    width: int | None = None
    height: int | None = None
    duration: int | None = None
    thumbnail: Path | None = None
    uploader: str | None = None
    keys: list[str] = field(default_factory=list)

    def cleanup(self) -> None:
        _remove_workdir(self.workdir)


@dataclass
class Media:
    """One picture or clip of a photo post."""
    path: Path
    kind: str  # "photo" or "video"
    width: int | None = None
    height: int | None = None
    duration: int | None = None
    thumbnail: Path | None = None


@dataclass
class Album:
    """Instagram photo post or carousel, TikTok slideshow."""
    items: list[Media]
    workdir: Path
    uploader: str | None = None
    keys: list[str] = field(default_factory=list)
    audio: Path | None = None  # slideshow soundtrack
    audio_title: str | None = None
    audio_performer: str | None = None
    audio_duration: int | None = None

    def cleanup(self) -> None:
        _remove_workdir(self.workdir)


def _remove_workdir(workdir: Path) -> None:
    shutil.rmtree(workdir, ignore_errors=True)
    _active_dirs.discard(workdir)


@contextlib.contextmanager
def in_use(workdir: Path):
    """Keep cleanup_stale off a work dir that outlives one job (sticker sources reused between cuts)."""
    _active_dirs.add(workdir)
    try:
        yield
    finally:
        _active_dirs.discard(workdir)


class _Logger:
    """Route yt-dlp output into logging instead of stdout."""

    def debug(self, msg: str) -> None:
        pass

    def info(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        log.debug("yt-dlp: %s", msg)

    def error(self, msg: str) -> None:
        log.info("yt-dlp: %s", msg)


def _human_error(err: Exception) -> str:
    text = str(err).lower()
    if any(s in text for s in ("ip address is blocked", "your country", "your location")):
        return "Платформа не отдаёт это видео в регион сервера."
    if "not a bot" in text:
        return "YouTube временно ограничил доступ серверу. Попробуй позже."
    if any(s in text for s in ("login", "private", "rate-limit", "cookies", "sign in")):
        return "Видео недоступно без входа в аккаунт (приватное или с ограничениями)."
    if "no video" in text or "there is no video" in text:
        return "В этом посте нет видео."
    if "unsupported url" in text:
        return "Не удалось распознать ссылку как видео."
    if any(s in text for s in ("unavailable", "not exist", "removed", "deleted", "404", "not found")):
        return "Видео удалено или недоступно."
    return "Не удалось скачать видео. Попробуй ещё раз чуть позже."


def _reject_long(info: dict, *, incomplete: bool) -> str | None:
    """yt-dlp match_filter: skip the download of overly long videos up front."""
    if (info.get("duration") or 0) > config.MAX_DURATION:
        return "too long"
    return None


def _format_sort(resolution: int) -> list[str]:
    return ["vcodec:h264", f"res:{resolution}", "acodec:aac", "ext:mp4:m4a"]


def _ydl_opts(workdir: Path, deadline: float) -> dict:
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
        "match_filter": _reject_long,
        "progress_hooks": [enforce_deadline],
        "noplaylist": True,
        # Photo posts have no formats; they're handled by hand instead of failing
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
        # yt-dlp writes cookies back on exit; give each run its own copy
        cookies = workdir / "cookies.txt"
        shutil.copyfile(config.COOKIES_FILE, cookies)
        opts["cookiefile"] = str(cookies)
    return opts


def probe(path: Path) -> tuple[int | None, int | None, int | None]:
    """Width, height and duration from `ffmpeg -i` (the image ships without ffprobe)."""
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path)],
                             capture_output=True, text=True, timeout=30).stderr
    except Exception:
        log.exception("ffmpeg probe failed for %s", path)
        return None, None, None
    width = height = duration = None
    if m := re.search(r"Stream #.*?Video:.*?[ ,](\d{2,5})x(\d{2,5})[ ,\[]", out):
        width, height = int(m[1]), int(m[2])
        if (r := re.search(r"rotation of (-?[\d.]+) degrees", out)) and round(abs(float(r[1]))) % 180 == 90:
            width, height = height, width
    if m := re.search(r"Duration: (\d+):(\d\d):(\d\d(?:\.\d+)?)", out):
        duration = round(int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]))
    return width, height, duration


def _make_thumbnail(path: Path, width: int | None, height: int | None) -> Path | None:
    thumb = path.with_name(f"{path.stem}.thumb.jpg")
    # Telegram wants a JPEG up to 320px on the longest side
    scale = "320:-2" if (width or 0) >= (height or 0) else "-2:320"
    try:
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", "0.3", "-i", str(path), "-frames:v", "1",
             "-vf", f"scale={scale}", "-q:v", "5", str(thumb)],
            capture_output=True, timeout=30, check=True,
        )
        return thumb if thumb.is_file() and thumb.stat().st_size < 200_000 else None
    except Exception:
        log.warning("thumbnail generation failed for %s", path)
        return None


def _uploader(info: dict) -> str | None:
    return info.get("uploader") or info.get("channel") or info.get("uploader_id")


def _keys(link: Link, info: dict) -> list[str]:
    keys = [link.key]
    if info.get("extractor_key") and info.get("id"):
        keys.append(f"{info['extractor_key'].lower()}:{info['id']}")
    return keys


def _has_video(entry: dict) -> bool:
    if entry.get("_type") in ("url", "url_transparent"):
        return True
    formats = entry.get("formats") or ([entry] if entry.get("url") else [])
    return any(f.get("vcodec") != "none" for f in formats)


def _entries(info: dict) -> list[dict]:
    if info.get("_type") != "playlist":
        return [info]
    entries = [e for e in itertools.islice(info.get("entries") or [], config.MAX_POST_ITEMS) if e]
    for entry in entries:
        if entry.get("_type") in ("url", "url_transparent"):
            continue
        # Carousel items come without the bookkeeping fields yt-dlp needs to download them
        for k in ("extractor", "extractor_key", "webpage_url", "webpage_url_basename",
                  "webpage_url_domain", "original_url"):
            entry.setdefault(k, info.get(k))
    return entries


def _too_long() -> DownloadError:
    return DownloadError(f"Видео длиннее {config.MAX_DURATION // 60} мин — такие не качаю.")


def _fetch_video(ydl: yt_dlp.YoutubeDL, entry: dict) -> tuple[Path, dict]:
    """Download one clip, stepping the quality down until it fits the Bot API limit."""
    if (entry.get("duration") or 0) > config.MAX_DURATION:
        raise _too_long()
    for resolution in _RESOLUTIONS:
        ydl.params["format_sort"] = _format_sort(resolution)
        try:
            info = ydl.process_ie_result(copy.deepcopy(entry), download=True)
        except yt_dlp.utils.DownloadCancelled as e:
            raise DownloadError("Видео качается слишком долго, попробуй позже.") from e
        except yt_dlp.utils.DownloadError as e:
            log.info("download failed for %s: %s", entry.get("webpage_url"), e)
            raise DownloadError(_human_error(e)) from e
        if (info.get("duration") or 0) > config.MAX_DURATION:
            raise _too_long()
        files = [Path(d["filepath"]) for d in info.get("requested_downloads") or [] if d.get("filepath")]
        files = [f for f in files if f.is_file()]
        if files and files[0].stat().st_size <= config.MAX_FILE_SIZE:
            return files[0], info
        # Too big (or skipped by max_filesize): retry in lower quality
        for f in files:
            f.unlink(missing_ok=True)
        log.info("%s too big at %sp, retrying lower", entry.get("webpage_url"), resolution)
    raise DownloadError("Видео больше 50 МБ — Telegram не даст боту его отправить.")


def _video_media(path: Path, info: dict) -> Media:
    width, height, duration = probe(path)
    return Media(
        path=path,
        kind="video",
        width=width or info.get("width"),
        height=height or info.get("height"),
        duration=duration or (round(info["duration"]) if info.get("duration") else None),
        thumbnail=_make_thumbnail(path, width, height),
    )


def _fetch_photo(ydl: yt_dlp.YoutubeDL, urls: list[str], dest: Path, headers: dict) -> Media | None:
    """First of the URLs that downloads, as a JPEG or PNG (what Telegram takes as a photo)."""
    for url in urls:
        try:
            with ydl.urlopen(Request(url, headers=headers)) as resp:
                data = resp.read(config.MAX_PHOTO_SIZE + 1)
        except Exception as e:
            log.info("photo download failed (%s…): %s", url[:80], e)
            continue
        if len(data) > config.MAX_PHOTO_SIZE:
            log.info("photo too big (%s…)", url[:80])
            continue
        if data.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")):
            dest.write_bytes(data)
            return Media(dest, "photo")
        source = dest.with_suffix(".src")
        source.write_bytes(data)
        try:  # WebP and friends
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(source), "-q:v", "2", str(dest)],
                           capture_output=True, timeout=60, check=True)
            return Media(dest, "photo")
        except Exception:
            log.info("can't convert photo (%s…)", url[:80])
        finally:
            source.unlink(missing_ok=True)
    return None


def _photo_urls(entry: dict) -> list[str]:
    thumbs = [t for t in entry.get("thumbnails") or [] if url_or_none(t.get("url"))]
    # Smallest first; when sizes are unknown the order stays as is (Instagram lists the original last)
    thumbs.sort(key=lambda t: (t.get("width") or 0) * (t.get("height") or 0))
    urls = [t["url"] for t in reversed(thumbs)]
    if url_or_none(entry.get("thumbnail")):
        urls.append(entry["thumbnail"])
    return list(dict.fromkeys(urls))[:3]


def _check_deadline(deadline: float) -> None:
    if time.monotonic() > deadline:
        raise DownloadError("Пост качается слишком долго, попробуй позже.")


def _instagram_post(ydl: yt_dlp.YoutubeDL, link: Link, info: dict, entries: list[dict],
                    workdir: Path, deadline: float) -> Album:
    # Carousel clips come as a 360p DASH stream plus progressive files of unknown size that are
    # really 720p with sound; yt-dlp ranks the known 360p higher, so take a progressive file first
    ydl.format_selector = ydl.build_format_selector("b/bv*+ba")
    items = []
    for i, entry in enumerate(entries):
        _check_deadline(deadline)
        try:
            if _has_video(entry):
                items.append(_video_media(*_fetch_video(ydl, entry)))
            elif photo := _fetch_photo(ydl, _photo_urls(entry), workdir / f"{i:02d}.jpg",
                                       entry.get("http_headers") or {}):
                items.append(photo)
        except DownloadError as e:
            if len(entries) == 1:
                raise
            log.info("skipping item %d of %s: %s", i, link.url, e)
    if not items:
        raise DownloadError("Не получилось скачать ни одного фото или видео из поста.")
    return Album(items, workdir, uploader=_uploader(info), keys=_keys(link, info))


def _tiktok_slideshow(ydl: yt_dlp.YoutubeDL, link: Link, video_id: str, workdir: Path,
                      deadline: float) -> Album | None:
    """yt-dlp only gets the soundtrack of a slideshow; the pictures are in the web page data."""
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
        if photo := _fetch_photo(ydl, urls, workdir / f"{i:02d}.jpg", _TIKTOK_HEADERS):
            items.append(photo)
    if not items:
        return None
    album = Album(items, workdir,
                  uploader=traverse_obj(data, ("author", "uniqueId", {str})),
                  keys=[link.key, f"tiktok:{video_id}"])
    music = data.get("music") or {}
    if play_url := url_or_none(music.get("playUrl")):
        try:
            with ydl.urlopen(Request(play_url, headers=_TIKTOK_HEADERS)) as resp:
                sound = resp.read(config.MAX_FILE_SIZE + 1)
            if len(sound) <= config.MAX_FILE_SIZE:
                album.audio = workdir / "music.mp3"
                album.audio.write_bytes(sound)
                album.audio_title = music.get("title")
                album.audio_performer = music.get("authorName")
                album.audio_duration = int_or_none(music.get("duration"))
        except Exception as e:
            log.info("slideshow soundtrack download failed for %s: %s", video_id, e)
    return album


def _extract(ydl: yt_dlp.YoutubeDL, link: Link, workdir: Path, deadline: float) -> Video | Album:
    tiktok_id = m[1] if link.platform == "TikTok" and (m := re.search(r"/video/(\d+)", link.url)) else None
    try:
        info = ydl.extract_info(link.url, download=False, process=False)
    except yt_dlp.utils.DownloadError as e:
        # A slideshow yt-dlp can't parse may still have its pictures in the web page
        if tiktok_id and (album := _tiktok_slideshow(ydl, link, tiktok_id, workdir, deadline)):
            return album
        log.info("download failed for %s: %s", link.url, e)
        raise DownloadError(_human_error(e)) from e

    if link.platform == "TikTok" and not _has_video(info):
        video_id = str(info.get("id") or tiktok_id)
        if album := _tiktok_slideshow(ydl, link, video_id, workdir, deadline):
            return album
        raise DownloadError("В этом посте нет видео.")
    entries = _entries(info)
    if not entries:
        raise DownloadError("В этом посте нет видео.")
    if link.platform == "Instagram" and (len(entries) > 1 or not _has_video(entries[0])):
        return _instagram_post(ydl, link, info, entries, workdir, deadline)

    path, info = _fetch_video(ydl, entries[0])
    media = _video_media(path, info)
    return Video(path=path, workdir=workdir, width=media.width, height=media.height,
                 duration=media.duration, thumbnail=media.thumbnail,
                 uploader=_uploader(info), keys=_keys(link, info))


def _download_sync(link: Link) -> Video | Album:
    workdir = config.TMP_DIR / uuid.uuid4().hex
    workdir.mkdir(parents=True)
    _active_dirs.add(workdir)
    deadline = time.monotonic() + config.DOWNLOAD_TIMEOUT
    try:
        with yt_dlp.YoutubeDL(_ydl_opts(workdir, deadline)) as ydl:
            return _extract(ydl, link, workdir, deadline)
    except BaseException:
        _remove_workdir(workdir)
        raise


# Share and short links are redirects; expand them so the cache and the photo/video checks see the post
_SHORT_KEYS = {"ig-share:": "ig:", "tt-short:": "tt:"}


async def resolve(link: Link) -> Link:
    want = next((full for short, full in _SHORT_KEYS.items() if link.key.startswith(short)), None)
    if not want:
        return link
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": _UA}) as session:
            async with session.get(link.url, allow_redirects=True) as resp:
                final = str(resp.url)
                history = [str(r.url) for r in resp.history]
                locations = [r.headers.get("Location", "") for r in resp.history]
    except Exception:
        log.warning("failed to resolve %s", link.url)
        return link
    candidates = [final, *parse_qs(urlsplit(final).query).get("next", []), *reversed(locations), *reversed(history)]
    for candidate in candidates:
        for resolved in find_links(urljoin(link.url, candidate)):
            if resolved.key.startswith(want):
                return resolved
    return link


def free_disk() -> int:
    return shutil.disk_usage(config.TMP_DIR.parent).free


def cleanup_stale(max_age: float = config.STALE_TMP_AGE) -> int:
    """Remove leftover work dirs (crashes, kills); returns bytes freed."""
    freed = 0
    if not config.TMP_DIR.is_dir():
        return 0
    now = time.time()
    for workdir in config.TMP_DIR.iterdir():
        if workdir in _active_dirs:
            continue
        try:
            if now - workdir.stat().st_mtime < max_age:
                continue
            freed += sum(f.stat().st_size for f in workdir.rglob("*") if f.is_file())
        except OSError:
            pass
        if workdir.is_dir():
            shutil.rmtree(workdir, ignore_errors=True)
        else:
            workdir.unlink(missing_ok=True)
    return freed


def _ensure_disk_space() -> None:
    if free_disk() >= config.MIN_FREE_DISK:
        return
    cleanup_stale(max_age=0)
    if free_disk() < config.MIN_FREE_DISK:
        log.warning("only %d MB free on disk, refusing downloads", free_disk() // config.MB)
        raise DownloadError("На сервере заканчивается место, загрузки временно приостановлены.")


@contextlib.contextmanager
def _job_slot(user_id: int):
    """Bound the backlog overall and per user so nobody can pile up work."""
    global _jobs_total
    if _jobs_total >= config.MAX_QUEUE:
        raise DownloadError("Сейчас слишком много запросов, попробуй через минуту.")
    if _jobs_by_user.get(user_id, 0) >= config.MAX_JOBS_PER_USER:
        raise DownloadError("Подожди, пока скачаются предыдущие видео.")
    _jobs_total += 1
    _jobs_by_user[user_id] = _jobs_by_user.get(user_id, 0) + 1
    try:
        yield
    finally:
        _jobs_total -= 1
        if (left := _jobs_by_user.pop(user_id) - 1) > 0:
            _jobs_by_user[user_id] = left


async def download(link: Link, user_id: int) -> Video | Album:
    with _job_slot(user_id):
        resolved = await resolve(link)
        heavy = _youtube_slots if link.platform == "YouTube" else contextlib.nullcontext()
        async with heavy, _semaphore:
            _ensure_disk_space()
            started = time.monotonic()
            media = await asyncio.to_thread(_download_sync, resolved)
    if isinstance(media, Album):
        log.info("downloaded %s: %d items%s, %.1fs", link.key, len(media.items),
                 " + audio" if media.audio else "", time.monotonic() - started)
    else:
        log.info("downloaded %s: %d KB, %sx%s, %.1fs", link.key, media.path.stat().st_size // 1024,
                 media.width, media.height, time.monotonic() - started)
    for key in (resolved.key, link.key):
        if key not in media.keys:
            media.keys.insert(0, key)
    return media
