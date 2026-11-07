"""Uploading downloads to Telegram and resending them by file_id."""
import asyncio
import contextlib
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import (
    FSInputFile,
    InlineKeyboardMarkup,
    InlineQueryResultCachedDocument,
    InlineQueryResultCachedMpeg4Gif,
    InlineQueryResultCachedPhoto,
    InlineQueryResultCachedVideo,
    InputMediaAnimation,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
    Message,
)

from .. import config, jobs
from ..db import Cached, CachedFile, CachedPost, Database
from ..errors import UserError
from ..links import Link, canonical_key
from ..media.downloader import download
from ..media.models import Album, Download, MediaItem, Video
from .texts import caption

log = logging.getLogger(__name__)

ALBUM_SIZE = 10
# The 50 MB Bot API limit applies to the whole request, so a media group of uploads must fit in it
UPLOAD_BUDGET = 48 * config.MB

# Downloads for inline and guest requests, shared by everyone asking for the same link
_inflight: dict[str, asyncio.Task] = {}


def cached_file(message: Message, uploader: str | None) -> CachedFile:
    if message.photo:
        photo = message.photo[-1]
        return CachedFile(photo.file_id, "photo", uploader, photo.width, photo.height, None)
    if video := message.video:
        return CachedFile(video.file_id, "video", uploader, video.width, video.height, video.duration)
    if animation := message.animation:
        return CachedFile(animation.file_id, "animation", uploader, animation.width, animation.height,
                          animation.duration)
    return CachedFile(message.document.file_id, "document", uploader, None, None, None)


async def _retrying(call):
    """Ride out Telegram's flood control, which albums of many messages run into."""
    for attempt in range(3):
        try:
            return await call()
        except TelegramRetryAfter as e:
            if attempt == 2 or e.retry_after > 60:
                raise
            log.info("flood control, waiting %ss", e.retry_after)
            await asyncio.sleep(e.retry_after + 1)


def input_media(cached: CachedFile, caption: str | None):
    if cached.kind == "video":
        return InputMediaVideo(media=cached.file_id, caption=caption, supports_streaming=True,
                               width=cached.width, height=cached.height, duration=cached.duration)
    if cached.kind == "photo":
        return InputMediaPhoto(media=cached.file_id, caption=caption)
    if cached.kind == "animation":
        return InputMediaAnimation(media=cached.file_id, caption=caption)
    return InputMediaDocument(media=cached.file_id, caption=caption)


def _upload_media(item: MediaItem, caption: str | None):
    if item.kind == "photo":
        return InputMediaPhoto(media=FSInputFile(item.path), caption=caption)
    return InputMediaVideo(media=FSInputFile(item.path), caption=caption, width=item.width, height=item.height,
                           duration=item.duration, supports_streaming=True,
                           thumbnail=FSInputFile(item.thumbnail) if item.thumbnail else None)


async def _send_one(bot: Bot, chat_id: int, media, **kwargs) -> Message:
    if isinstance(media, InputMediaPhoto):
        return await bot.send_photo(chat_id, media.media, caption=media.caption, **kwargs)
    if isinstance(media, InputMediaVideo):
        return await bot.send_video(chat_id, media.media, caption=media.caption, width=media.width,
                                    height=media.height, duration=media.duration, thumbnail=media.thumbnail,
                                    supports_streaming=True, **kwargs)
    if isinstance(media, InputMediaAnimation):
        return await bot.send_animation(chat_id, media.media, caption=media.caption, **kwargs)
    return await bot.send_document(chat_id, media.media, caption=media.caption, **kwargs)


def _chunks(media: list, sizes: list[int] | None = None) -> list[list]:
    """Media groups of up to 10 items and, for uploads, within the request size limit."""
    chunks, current, total = [], [], 0
    for i, item in enumerate(media):
        size = sizes[i] if sizes else 0
        if current and (len(current) == ALBUM_SIZE or total + size > UPLOAD_BUDGET):
            chunks.append(current)
            current, total = [], 0
        current.append(item)
        total += size
    return chunks + [current] if current else chunks


async def _send_groups(bot: Bot, chat_id: int, chunks: list[list], reply_parameters=None,
                       **kwargs) -> list[Message]:
    messages = []
    for n, chunk in enumerate(chunks):
        extra = dict(kwargs, request_timeout=300)
        if n == 0 and reply_parameters:
            extra["reply_parameters"] = reply_parameters
        if len(chunk) == 1:  # a media group needs at least two items
            messages.append(await _retrying(lambda: _send_one(bot, chat_id, chunk[0], **extra)))
        else:
            messages += await _retrying(lambda: bot.send_media_group(chat_id, chunk, **extra))
    return messages


async def upload(bot: Bot, chat_id: int, media: Download, caption: str, *,
                 reply_markup: InlineKeyboardMarkup | None = None, **kwargs) -> tuple[list[Message], Cached]:
    """Upload a download; reply_markup goes under a single video (media groups can't have buttons)."""
    if isinstance(media, Video):
        message = await bot.send_video(chat_id, FSInputFile(media.clip.path), width=media.clip.width,
                                       height=media.clip.height, duration=media.clip.duration,
                                       thumbnail=FSInputFile(media.clip.thumbnail) if media.clip.thumbnail else None,
                                       supports_streaming=True, caption=caption, reply_markup=reply_markup,
                                       request_timeout=300, **kwargs)
        return [message], cached_file(message, media.uploader)
    return await _upload_album(bot, chat_id, media, caption, **kwargs)


async def _upload_album(bot: Bot, chat_id: int, album: Album, caption: str, reply_parameters=None,
                        **kwargs) -> tuple[list[Message], CachedPost]:
    media = [_upload_media(item, caption if i == 0 else None) for i, item in enumerate(album.items)]
    sizes = [item.upload_size for item in album.items]
    messages = await _send_groups(bot, chat_id, _chunks(media, sizes), reply_parameters, **kwargs)
    items = [cached_file(m, album.uploader) for m in messages]
    audio = None
    if album.audio:
        message = await _retrying(lambda: bot.send_audio(
            chat_id, FSInputFile(album.audio.path), title=album.audio.title, performer=album.audio.performer,
            duration=album.audio.duration, request_timeout=300, **kwargs))
        messages.append(message)
        audio = message.audio.file_id if message.audio else None
    return messages, CachedPost(canonical_key(album.keys) or album.keys[0], items, audio, album.uploader)


async def send_cached(bot: Bot, chat_id: int, cached: Cached, caption: str, *, reply_parameters=None,
                      reply_markup: InlineKeyboardMarkup | None = None, **kwargs) -> None:
    """Resend by file_id; reply_markup goes under a single file."""
    if isinstance(cached, CachedPost):
        media = [input_media(item, caption if i == 0 else None) for i, item in enumerate(cached.items)]
        await _send_groups(bot, chat_id, _chunks(media), reply_parameters, **kwargs)
        if cached.audio:
            await _retrying(lambda: bot.send_audio(chat_id, cached.audio, **kwargs))
        return
    await _send_one(bot, chat_id, input_media(cached, caption), reply_parameters=reply_parameters,
                    reply_markup=reply_markup, **kwargs)


def inline_result(cached: CachedFile, caption: str, title: str, description: str | None = None,
                  reply_markup: InlineKeyboardMarkup | None = None):
    common = dict(id="media", caption=caption, reply_markup=reply_markup)
    if cached.kind == "video":
        return InlineQueryResultCachedVideo(video_file_id=cached.file_id, title=title, description=description,
                                            **common)
    if cached.kind == "photo":
        return InlineQueryResultCachedPhoto(photo_file_id=cached.file_id, title=title, description=description,
                                            **common)
    if cached.kind == "animation":
        return InlineQueryResultCachedMpeg4Gif(mpeg4_file_id=cached.file_id, title=title, **common)
    return InlineQueryResultCachedDocument(document_file_id=cached.file_id, title=title, description=description,
                                           **common)


async def fetch_media(bot: Bot, db: Database, link: Link, user_id: int) -> Cached:
    """file_ids for the link: cached, or downloaded and parked in a chat to get them.

    Callers may stop waiting (an inline query times out); the download goes on, so a later
    request for the same link picks up the result."""
    if cached := db.get(link.key):
        return cached
    task = _inflight.get(link.key)
    if task is None:
        task = asyncio.create_task(_fetch(bot, db, link, user_id))
        _inflight[link.key] = task

        def forget(t: asyncio.Task, key: str = link.key) -> None:
            _inflight.pop(key, None)
            if not t.cancelled():
                t.exception()  # retrieved, even if every waiter gave up

        task.add_done_callback(forget)
    return await asyncio.shield(task)


async def _fetch(bot: Bot, db: Database, link: Link, user_id: int) -> Cached:
    with jobs.tracked():
        media = await download(link, user_id)
        try:
            cached = await _park(bot, media, caption(link, media.uploader),
                                 [config.STORAGE_CHAT_ID, user_id, db.owner_id()])
        except TelegramAPIError as e:
            log.exception("failed to upload %s", link.url)
            raise UserError("Telegram не принял файл. Попробуй ещё раз.") from e
        finally:
            media.cleanup()
    if not cached:
        me = await bot.me()
        raise UserError(f"Сначала открой @{me.username} в личке и нажми «Старт», потом повтори.")
    db.put(media.keys, cached)
    return cached


async def _park(bot: Bot, media: Download, caption: str, chat_ids: list[int | None]) -> Cached | None:
    """Upload to the first chat that takes it, to get file_ids for inline messages."""
    for chat_id in dict.fromkeys(c for c in chat_ids if c):
        try:
            messages, cached = await upload(bot, chat_id, media, caption, disable_notification=True)
        except (TelegramForbiddenError, TelegramBadRequest) as e:
            log.info("can't use chat %s for upload: %s", chat_id, e)
            continue
        if chat_id != config.STORAGE_CHAT_ID:
            with contextlib.suppress(TelegramAPIError):
                await bot.delete_messages(chat_id, [m.message_id for m in messages])
        return cached
    return None
