"""Videos in the chat as local files, for the jobs that work on them."""
import asyncio
import contextlib
import logging
import shutil
import weakref
from dataclasses import dataclass
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message, ReplyParameters

from .. import config
from ..errors import UserError
from ..links import find_links
from ..media import workspace
from ..media.downloader import download
from ..media.models import Album
from .messages import text_of

log = logging.getLogger(__name__)

# Bots can fetch files only up to 20 MB from Telegram; bigger videos are downloaded again by their link
MAX_TELEGRAM_FILE = 20 * config.MB

_fetching: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()


@dataclass
class Clip:
    file_id: str
    unique_id: str
    size: int | None
    duration: int | None
    width: int | None
    height: int | None
    round: bool


def clip_of(message: Message | None) -> Clip | None:
    if message is None:
        return None
    if media := message.video or message.animation:
        return Clip(media.file_id, media.file_unique_id, media.file_size, media.duration,
                    media.width, media.height, False)
    if note := message.video_note:
        return Clip(note.file_id, note.file_unique_id, note.file_size, note.duration, note.length, note.length, True)
    doc = message.document
    if doc and (doc.mime_type or "").startswith("video/"):
        return Clip(doc.file_id, doc.file_unique_id, doc.file_size, None, None, None, False)
    return None


def video_message(message: Message | None) -> Message | None:
    """The message with the video a button works on: the one it's under, or else the one that replies to,
    as the bot's stickers do and the buttons it puts under videos sent to it."""
    if message is None or clip_of(message):
        return message
    return message.reply_to_message if clip_of(message.reply_to_message) else None


@contextlib.contextmanager
def workdir(clip: Clip):
    """A work dir shared by all jobs on the clip, kept for a while so the next ones don't fetch it again."""
    with workspace.reusable(f"clip-{clip.unique_id}") as path:
        yield path


@contextlib.asynccontextmanager
async def errors_in_reply(bot: Bot, chat_id: int, reply: ReplyParameters, failure: str):
    """Errors of a job on a video go to the chat in reply to it."""
    try:
        yield
        return
    except UserError as e:
        text = str(e)
    except Exception:
        log.exception(failure)
        text = failure
    await bot.send_message(chat_id, f"❌ {text}", reply_parameters=reply)


async def fetch(bot: Bot, message: Message, clip: Clip, user_id: int, workdir: Path) -> Path:
    """The clip's video file in its work dir."""
    lock = _fetching.setdefault(clip.unique_id, asyncio.Lock())
    async with lock:
        path = workdir / "source"
        if not path.is_file():
            await _fetch(bot, message, clip, user_id, path)
        return path


async def _fetch(bot: Bot, message: Message, clip: Clip, user_id: int, path: Path) -> None:
    workspace.ensure_free_space()
    if (clip.size or 0) <= MAX_TELEGRAM_FILE:
        part = path.with_suffix(".part")
        try:
            await bot.download(clip.file_id, destination=part, timeout=120)
            part.rename(path)
            return
        except TelegramBadRequest as e:  # "file is too big" when the size wasn't known
            log.info("can't fetch %s from Telegram: %s", clip.unique_id, e)
    links = find_links(text_of(message))
    if not links:
        raise UserError("too_big_to_fetch")
    media = await download(links[0], user_id)
    try:
        if isinstance(media, Album):
            video = next((item.path for item in media.items if item.kind == "video"), None)
            if video is None:
                raise UserError("no_video_in_post")
        else:
            video = media.clip.path
        shutil.move(video, path)
    finally:
        media.cleanup()
