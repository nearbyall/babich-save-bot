import asyncio
import contextlib
import html
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import (
    FSInputFile,
    InlineKeyboardButton,
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

from . import config
from .db import CachedPost, CachedVideo, Database
from .downloader import Album, DownloadError, Video, download
from .links import Link, canonical_key, to_payload

log = logging.getLogger(__name__)

Cached = CachedVideo | CachedPost

# Requests in progress, so a self-restart for updates can wait for them
active_jobs = 0
# Downloads in progress for guest/inline requests, shared by everyone asking for the same link
_inflight: dict[str, asyncio.Task] = {}
ALBUM_SIZE = 10  # Telegram's limit per media group
# The 50 MB Bot API limit applies to the whole request, so a media group of uploads must fit in it
UPLOAD_BUDGET = 48 * config.MB


@contextlib.contextmanager
def tracked():
    global active_jobs
    active_jobs += 1
    try:
        yield
    finally:
        active_jobs -= 1


def caption(link: Link, uploader: str | None) -> str:
    text = f'<a href="{html.escape(link.url)}">{link.platform}</a>'
    if uploader:
        text += f" · {html.escape(uploader[:100])}"
    return text


def _cached_from(message: Message, uploader: str | None) -> CachedVideo:
    # Telegram may store a silent clip as an animation, or an odd file as a document
    if message.photo:
        photo = message.photo[-1]
        return CachedVideo(photo.file_id, "photo", uploader, photo.width, photo.height, None)
    if message.video:
        v = message.video
        return CachedVideo(v.file_id, "video", uploader, v.width, v.height, v.duration)
    if message.animation:
        a = message.animation
        return CachedVideo(a.file_id, "animation", uploader, a.width, a.height, a.duration)
    return CachedVideo(message.document.file_id, "document", uploader, None, None, None)


async def _retrying(call):
    """Albums are many messages at once; ride out Telegram's flood control."""
    for attempt in range(3):
        try:
            return await call()
        except TelegramRetryAfter as e:
            if attempt == 2 or e.retry_after > 60:
                raise
            log.info("flood control, waiting %ss", e.retry_after)
            await asyncio.sleep(e.retry_after + 1)


async def upload(bot: Bot, chat_id: int, video: Video, caption: str, **kwargs) -> tuple[Message, CachedVideo]:
    message = await bot.send_video(
        chat_id,
        FSInputFile(video.path),
        width=video.width,
        height=video.height,
        duration=video.duration,
        thumbnail=FSInputFile(video.thumbnail) if video.thumbnail else None,
        supports_streaming=True,
        caption=caption,
        request_timeout=300,
        **kwargs,
    )
    return message, _cached_from(message, video.uploader)


async def _send_one(bot: Bot, chat_id: int, item, **kwargs) -> Message:
    if isinstance(item, InputMediaPhoto):
        return await bot.send_photo(chat_id, item.media, caption=item.caption, **kwargs)
    if isinstance(item, InputMediaVideo):
        return await bot.send_video(chat_id, item.media, caption=item.caption, width=item.width,
                                    height=item.height, duration=item.duration, thumbnail=item.thumbnail,
                                    supports_streaming=True, **kwargs)
    if isinstance(item, InputMediaAnimation):
        return await bot.send_animation(chat_id, item.media, caption=item.caption, **kwargs)
    return await bot.send_document(chat_id, item.media, caption=item.caption, **kwargs)


def _chunks(media: list, sizes: list[int] | None = None) -> list[list]:
    """Albums of up to 10 items and, for uploads, under the request size limit."""
    chunks, current, total = [], [], 0
    for i, item in enumerate(media):
        size = sizes[i] if sizes else 0
        if current and (len(current) == ALBUM_SIZE or total + size > UPLOAD_BUDGET):
            chunks.append(current)
            current, total = [], 0
        current.append(item)
        total += size
    return chunks + [current] if current else chunks


async def _send_media(bot: Bot, chat_id: int, chunks: list[list], reply_parameters=None,
                      **kwargs) -> list[Message]:
    """A lone item goes as a plain message (an album needs two)."""
    messages = []
    for n, chunk in enumerate(chunks):
        extra = dict(kwargs, request_timeout=300)
        if n == 0 and reply_parameters:
            extra["reply_parameters"] = reply_parameters
        if len(chunk) == 1:
            messages.append(await _retrying(lambda: _send_one(bot, chat_id, chunk[0], **extra)))
        else:
            messages += await _retrying(lambda: bot.send_media_group(chat_id, chunk, **extra))
    return messages


async def upload_album(bot: Bot, chat_id: int, album: Album, caption: str, reply_parameters=None,
                       **kwargs) -> tuple[list[Message], CachedPost]:
    media, sizes = [], []
    for i, item in enumerate(album.items):
        text = caption if i == 0 else None
        sizes.append(item.path.stat().st_size + (item.thumbnail.stat().st_size if item.thumbnail else 0))
        if item.kind == "photo":
            media.append(InputMediaPhoto(media=FSInputFile(item.path), caption=text))
        else:
            media.append(InputMediaVideo(
                media=FSInputFile(item.path), caption=text, width=item.width, height=item.height,
                duration=item.duration, supports_streaming=True,
                thumbnail=FSInputFile(item.thumbnail) if item.thumbnail else None))
    messages = await _send_media(bot, chat_id, _chunks(media, sizes), reply_parameters, **kwargs)
    items = [_cached_from(m, album.uploader) for m in messages]
    audio = None
    if album.audio:
        message = await _retrying(lambda: bot.send_audio(
            chat_id, FSInputFile(album.audio), title=album.audio_title, performer=album.audio_performer,
            duration=album.audio_duration, request_timeout=300, **kwargs))
        messages.append(message)
        audio = message.audio.file_id if message.audio else None
    return messages, CachedPost(canonical_key(album.keys) or album.keys[0], items, audio, album.uploader)


async def send_cached_post(bot: Bot, chat_id: int, post: CachedPost, caption: str, reply_parameters=None,
                           **kwargs) -> None:
    media = [input_media(item, caption if i == 0 else None) for i, item in enumerate(post.items)]
    await _send_media(bot, chat_id, _chunks(media), reply_parameters, **kwargs)
    if post.audio:
        await _retrying(lambda: bot.send_audio(chat_id, post.audio, **kwargs))


def cached_result(cached: CachedVideo, caption: str, title: str = "Видео", description: str | None = None,
                  reply_markup: InlineKeyboardMarkup | None = None):
    """Inline result that sends an already uploaded video or photo."""
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


def input_media(cached: CachedVideo, caption: str | None):
    if cached.kind == "video":
        return InputMediaVideo(media=cached.file_id, caption=caption, supports_streaming=True,
                               width=cached.width, height=cached.height, duration=cached.duration)
    if cached.kind == "photo":
        return InputMediaPhoto(media=cached.file_id, caption=caption)
    if cached.kind == "animation":
        return InputMediaAnimation(media=cached.file_id, caption=caption)
    return InputMediaDocument(media=cached.file_id, caption=caption)


def post_keyboard(username: str, post: CachedPost) -> InlineKeyboardMarkup | None:
    """Inline and guest messages hold one picture; a button opens the whole post in the bot's DM."""
    payload = to_payload(post.key)
    if not payload or (len(post.items) < 2 and not post.audio):
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=f"🖼 Весь пост: {post.summary}", url=f"https://t.me/{username}?start={payload}")]])


async def _park(bot: Bot, media: Video | Album, caption: str, chat_ids: list[int | None]) -> Cached | None:
    """Inline messages can't take new uploads, so park the files in some chat to get file_ids."""
    for chat_id in dict.fromkeys(c for c in chat_ids if c):
        try:
            if isinstance(media, Album):
                messages, cached = await upload_album(bot, chat_id, media, caption, disable_notification=True)
            else:
                message, cached = await upload(bot, chat_id, media, caption, disable_notification=True)
                messages = [message]
        except (TelegramForbiddenError, TelegramBadRequest) as e:
            log.info("can't use chat %s for upload: %s", chat_id, e)
            continue
        if chat_id != config.STORAGE_CHAT_ID:
            with contextlib.suppress(TelegramAPIError):
                await bot.delete_messages(chat_id, [m.message_id for m in messages])
        return cached
    return None


async def _fetch(bot: Bot, db: Database, link: Link, user_id: int) -> Cached:
    with tracked():
        media = await download(link, user_id)
        try:
            cached = await _park(bot, media, caption(link, media.uploader),
                                 [config.STORAGE_CHAT_ID, user_id, db.owner_id()])
        except TelegramAPIError as e:
            log.exception("failed to upload %s", link.url)
            raise DownloadError("Telegram не принял файл. Попробуй ещё раз.") from e
        finally:
            media.cleanup()
    if not cached:
        me = await bot.me()
        raise DownloadError(f"Сначала открой @{me.username} в личке и нажми «Старт», потом повтори.")
    db.put_media(media.keys, cached)
    return cached


async def fetch_media(bot: Bot, db: Database, link: Link, user_id: int) -> Cached:
    """file_ids for the link: cached, or downloaded and parked in a storage chat.

    Callers may give up waiting (e.g. an inline query timing out); the download
    keeps going so a later request for the same link picks up the result."""
    if cached := db.get_media(link.key):
        return cached
    task = _inflight.get(link.key)
    if task is None:
        task = asyncio.create_task(_fetch(bot, db, link, user_id))
        _inflight[link.key] = task

        def forget(t: asyncio.Task, key: str = link.key) -> None:
            _inflight.pop(key, None)
            if not t.cancelled():
                t.exception()  # mark as retrieved even if every waiter gave up

        task.add_done_callback(forget)
    return await asyncio.shield(task)
