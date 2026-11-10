"""Video stickers from videos in the chat, and the user's own sticker pack."""
import asyncio
import itertools
import logging
import time
import uuid
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import FSInputFile, InputSticker, Message, ReplyParameters, User
from aiogram.utils.chat_action import ChatActionSender

from .. import jobs
from ..errors import UserError
from ..i18n import t
from ..media import ffmpeg, sticker
from ..media.sticker import Cut
from . import clips
from .clips import Clip, clip_of
from .keyboards import describe, sticker_keyboard

log = logging.getLogger(__name__)

EMOJI = "🎬"
PACK_SIZE = 120

_busy = jobs.Busy()


def busy(user_id: int) -> bool:
    return user_id in _busy


async def make(bot: Bot, source: Message, user: User, cut: Cut) -> Message | None:
    """Render a sticker from the video in `source` and send it in reply; errors go to the chat."""
    reply = ReplyParameters(message_id=source.message_id, allow_sending_without_reply=True)
    clip = clip_of(source)
    if clip is None:
        await bot.send_message(user.id, f"❌ {t('video_missing')}", reply_parameters=reply)
        return None
    try:
        with jobs.tracked(), _busy.hold(user.id), clips.workdir(clip) as workdir:
            async with ChatActionSender.choose_sticker(bot=bot, chat_id=user.id):
                return await _render_and_send(bot, source, user, clip, cut, workdir, reply)
    except UserError as e:
        text = str(e)
    except TelegramAPIError:
        log.exception("failed to send sticker from %s", clip.unique_id)
        text = t("sticker_rejected")
    except Exception:
        log.exception("failed to make sticker from %s", clip.unique_id)
        text = t("sticker_failed")
    await bot.send_message(user.id, f"❌ {text}", reply_parameters=reply)
    return None


async def _render_and_send(bot: Bot, source: Message, user: User, clip: Clip, cut: Cut, workdir: Path,
                           reply: ReplyParameters) -> Message:
    path = await clips.fetch(bot, source, clip, user.id, workdir)
    duration, width, height = clip.duration, clip.width, clip.height
    if not (duration and width and height):
        streams = await asyncio.to_thread(ffmpeg.probe, path)
        width, height, duration = streams.width, streams.height, streams.duration
    if duration and cut.start >= duration:
        raise UserError("video_only", duration=sticker.format_time(duration))
    cut = cut.framed(round_video=clip.round)
    dest = workdir / f"{uuid.uuid4().hex}.webm"
    try:
        started = time.monotonic()
        async with jobs.renders:
            await asyncio.to_thread(sticker.render, path, dest, cut)
        log.info("sticker from %s, %s %s: %d KB, %.1fs", clip.unique_id, describe(cut, duration), cut.shape,
                 dest.stat().st_size // 1024, time.monotonic() - started)
        return await bot.send_sticker(user.id, FSInputFile(dest), emoji=EMOJI, reply_parameters=reply,
                                      reply_markup=sticker_keyboard(cut, duration, width, height),
                                      request_timeout=60)
    finally:
        dest.unlink(missing_ok=True)


async def add_to_pack(bot: Bot, user: User, file_id: str) -> str:
    """Add a sticker to the user's pack (u<id>_by_<bot>, then _2, _3… as they fill up); returns its name."""
    me = await bot.me()
    new = InputSticker(sticker=file_id, format="video", emoji_list=[EMOJI])
    with _busy.hold(user.id):
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
