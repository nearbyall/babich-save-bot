"""Video stickers from videos in the chat, and the user's own sticker pack."""
import asyncio
import contextlib
import itertools
import logging
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import FSInputFile, InputSticker, Message, ReplyParameters, User
from aiogram.utils.chat_action import ChatActionSender

from .. import config, jobs
from ..errors import UserError
from ..links import find_links
from ..media import ffmpeg, sticker, workspace
from ..media.downloader import download
from ..media.models import Album
from ..media.sticker import Cut
from .keyboards import describe, sticker_keyboard
from .messages import text_of

log = logging.getLogger(__name__)

EMOJI = "🎬"
PACK_SIZE = 120
# Bots can fetch files only up to 20 MB from Telegram; bigger videos are downloaded again by their link
MAX_TELEGRAM_FILE = 20 * config.MB

_renderers = asyncio.Semaphore(config.MAX_PARALLEL_STICKERS)
_busy: set[int] = set()


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


def busy(user_id: int) -> bool:
    return user_id in _busy


@contextlib.contextmanager
def _exclusive(user_id: int):
    """One sticker job at a time per user."""
    _busy.add(user_id)
    try:
        yield
    finally:
        _busy.discard(user_id)


async def make(bot: Bot, source: Message, user: User, cut: Cut) -> Message | None:
    """Render a sticker from the video in `source` and send it in reply; errors go to the chat."""
    reply = ReplyParameters(message_id=source.message_id, allow_sending_without_reply=True)
    clip = clip_of(source)
    if clip is None:
        await bot.send_message(user.id, "❌ Не вижу видео — пришли его заново.", reply_parameters=reply)
        return None
    try:
        with jobs.tracked(), _exclusive(user.id), workspace.reusable(f"sticker-{clip.unique_id}") as workdir:
            async with ChatActionSender.choose_sticker(bot=bot, chat_id=user.id):
                return await _render_and_send(bot, source, user, clip, cut, workdir, reply)
    except UserError as e:
        text = str(e)
    except TelegramAPIError:
        log.exception("failed to send sticker from %s", clip.unique_id)
        text = "Telegram не принял стикер. Попробуй другой момент."
    except Exception:
        log.exception("failed to make sticker from %s", clip.unique_id)
        text = "Не получилось сделать стикер."
    await bot.send_message(user.id, f"❌ {text}", reply_parameters=reply)
    return None


async def _render_and_send(bot: Bot, source: Message, user: User, clip: Clip, cut: Cut, workdir: Path,
                           reply: ReplyParameters) -> Message:
    path = await _source_file(bot, source, clip, user.id, workdir)
    duration, width, height = clip.duration, clip.width, clip.height
    if not (duration and width and height):
        width, height, duration = await asyncio.to_thread(ffmpeg.probe, path)
    if duration and cut.start >= duration:
        raise UserError(f"В видео всего {sticker.format_time(duration)}.")
    cut = cut.framed(round_video=clip.round)
    dest = workdir / f"{uuid.uuid4().hex}.webm"
    try:
        started = time.monotonic()
        async with _renderers:
            await asyncio.to_thread(sticker.render, path, dest, cut)
        log.info("sticker from %s, %s %s: %d KB, %.1fs", clip.unique_id, describe(cut, duration), cut.shape,
                 dest.stat().st_size // 1024, time.monotonic() - started)
        return await bot.send_sticker(user.id, FSInputFile(dest), emoji=EMOJI, reply_parameters=reply,
                                      reply_markup=sticker_keyboard(cut, duration, width, height),
                                      request_timeout=60)
    finally:
        dest.unlink(missing_ok=True)


async def _source_file(bot: Bot, message: Message, clip: Clip, user_id: int, workdir: Path) -> Path:
    """The video file, kept in the work dir so the next cuts of it don't fetch it again."""
    path = workdir / "source"
    if path.is_file():
        return path
    workspace.ensure_free_space()
    if (clip.size or 0) <= MAX_TELEGRAM_FILE:
        part = workdir / "source.part"
        try:
            await bot.download(clip.file_id, destination=part, timeout=120)
            return part.rename(path)
        except TelegramBadRequest as e:  # "file is too big" when the size wasn't known
            log.info("can't fetch %s from Telegram: %s", clip.unique_id, e)
    links = find_links(text_of(message))
    if not links:
        raise UserError("Видео больше 20 МБ — такие бот не может забрать из Telegram. "
                        "Пришли ссылку на него или файл поменьше.")
    media = await download(links[0], user_id)
    try:
        if isinstance(media, Album):
            video = next((item.path for item in media.items if item.kind == "video"), None)
            if video is None:
                raise UserError("В этом посте нет видео.")
        else:
            video = media.clip.path
        shutil.move(video, path)
    finally:
        media.cleanup()
    return path


async def add_to_pack(bot: Bot, user: User, file_id: str) -> str:
    """Add a sticker to the user's pack (u<id>_by_<bot>, then _2, _3… as they fill up); returns its name."""
    me = await bot.me()
    new = InputSticker(sticker=file_id, format="video", emoji_list=[EMOJI])
    with _exclusive(user.id):
        for n in itertools.count(1):
            name = f"u{user.id}{f'_{n}' if n > 1 else ''}_by_{me.username}"
            try:
                pack = await bot.get_sticker_set(name=name)
            except TelegramBadRequest:
                title = f"{user.first_name[:30]} · @{me.username}" + (f" {n}" if n > 1 else "")
                await bot.create_new_sticker_set(user_id=user.id, name=name, title=title, stickers=[new])
                return name
            if len(pack.stickers) < PACK_SIZE:
                await bot.add_sticker_to_set(user_id=user.id, name=name, sticker=new)
                return name
