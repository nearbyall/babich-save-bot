"""Entry point of the media layer: a link in, a Video or an Album on disk out."""
import asyncio
import collections
import contextlib
import logging
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit

import aiohttp
import yt_dlp

from .. import config
from ..errors import UserError
from ..links import Link, find_links
from . import posts, workspace, ytdlp
from .models import Album, Video

log = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)


class _Backlog:
    """Bounds the requests in flight, overall and per user, so nobody can pile up work."""

    def __init__(self, total: int, per_user: int) -> None:
        self._total, self._per_user = total, per_user
        self._jobs: collections.Counter[int] = collections.Counter()

    @contextlib.contextmanager
    def slot(self, user_id: int):
        if self._jobs.total() >= self._total:
            raise UserError("too_many_requests")
        if self._jobs[user_id] >= self._per_user:
            raise UserError("wait_previous")
        self._jobs[user_id] += 1
        try:
            yield
        finally:
            self._jobs[user_id] -= 1
            if not self._jobs[user_id]:
                del self._jobs[user_id]


_backlog = _Backlog(config.MAX_QUEUE, config.MAX_JOBS_PER_USER)
_downloads = asyncio.Semaphore(config.MAX_PARALLEL_DOWNLOADS)
_youtube_downloads = asyncio.Semaphore(config.MAX_PARALLEL_YOUTUBE)


async def download(link: Link, user_id: int) -> Video | Album:
    with _backlog.slot(user_id):
        resolved = await resolve(link)
        youtube = _youtube_downloads if link.platform == "YouTube" else contextlib.nullcontext()
        async with youtube, _downloads:
            workspace.ensure_free_space()
            started = time.monotonic()
            media = await asyncio.to_thread(_download_sync, resolved)
    if isinstance(media, Album):
        log.info("downloaded %s: %d items%s, %.1fs", link.key, len(media.items),
                 " + audio" if media.audio else "", time.monotonic() - started)
    else:
        log.info("downloaded %s: %d KB, %sx%s, %.1fs", link.key, media.clip.path.stat().st_size // 1024,
                 media.clip.width, media.clip.height, time.monotonic() - started)
    for key in (resolved.key, link.key):
        if key not in media.keys:
            media.keys.insert(0, key)
    return media


async def resolve(link: Link) -> Link:
    """Expand a share or short link, so the cache and the photo/video checks see the post itself."""
    if not (want := link.expands_to):
        return link
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": _USER_AGENT}) as session:
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


def _download_sync(link: Link) -> Video | Album:
    workdir = workspace.create()
    deadline = time.monotonic() + config.DOWNLOAD_TIMEOUT
    try:
        with yt_dlp.YoutubeDL(ytdlp.options(workdir, deadline)) as ydl:
            return _extract(ydl, link, workdir, deadline)
    except BaseException:
        workspace.remove(workdir)
        raise


def _extract(ydl: yt_dlp.YoutubeDL, link: Link, workdir: Path, deadline: float) -> Video | Album:
    tiktok_id = m[1] if link.platform == "TikTok" and (m := re.search(r"/video/(\d+)", link.url)) else None
    try:
        info = ydl.extract_info(link.url, download=False, process=False)
    except yt_dlp.utils.DownloadError as e:
        # A slideshow yt-dlp can't parse may still have its pictures in the web page
        if tiktok_id and (album := posts.tiktok_slideshow(ydl, link, tiktok_id, workdir, deadline)):
            return album
        log.info("download failed for %s: %s", link.url, e)
        raise ytdlp.user_error(e) from e

    if link.platform == "TikTok" and not ytdlp.has_video(info):
        video_id = str(info.get("id") or tiktok_id)
        if album := posts.tiktok_slideshow(ydl, link, video_id, workdir, deadline):
            return album
        raise UserError("no_video_in_post")
    entries = ytdlp.entries(info)
    if not entries:
        raise UserError("no_video_in_post")
    if link.platform == "Instagram" and (len(entries) > 1 or not ytdlp.has_video(entries[0])):
        return posts.instagram_post(ydl, link, info, entries, workdir, deadline)

    clip, info = ytdlp.fetch_video(ydl, entries[0])
    return Video(clip=clip, workdir=workdir, uploader=ytdlp.uploader(info), keys=ytdlp.cache_keys(link, info))
