"""Round video messages from videos in the chat."""
import asyncio
import logging
import time
import uuid
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile, Message, ReplyParameters, User
from aiogram.utils.chat_action import ChatActionSender

from .. import jobs
from ..errors import UserError
from ..i18n import t
from ..media import ffmpeg, rounds
from ..media.sticker import format_time
from . import clips
from .clips import Clip
from .keyboards import round_keyboard

log = logging.getLogger(__name__)

_busy = jobs.Busy()


def busy(user_id: int) -> bool:
    return user_id in _busy


async def make(bot: Bot, source: Message, clip: Clip, user: User, start: int) -> None:
    """Reply to the video with a minute of it from `start` as a round video."""
    reply = ReplyParameters(message_id=source.message_id, allow_sending_without_reply=True)
    async with clips.errors_in_reply(bot, user.id, reply, t("round_failed")):
        with jobs.tracked(), _busy.hold(user.id), clips.workdir(clip) as workdir:
            async with ChatActionSender.record_video_note(bot=bot, chat_id=user.id):
                await _render_and_send(bot, source, clip, user.id, start, workdir, reply)


async def _render_and_send(bot: Bot, source: Message, clip: Clip, user_id: int, start: int, workdir: Path,
                           reply: ReplyParameters) -> None:
    path = await clips.fetch(bot, source, clip, user_id, workdir)
    duration = clip.duration or (await asyncio.to_thread(ffmpeg.probe, path)).duration
    if duration and start >= duration:
        raise UserError("video_only", duration=format_time(duration))
    dest = workdir / f"{uuid.uuid4().hex}.mp4"
    try:
        started = time.monotonic()
        async with jobs.renders:
            made = await asyncio.to_thread(rounds.render, path, dest, start)
        log.info("round from %s at %ds: %d KB, %.1fs", clip.unique_id, start, dest.stat().st_size // 1024,
                 time.monotonic() - started)
        await bot.send_video_note(user_id, FSInputFile(dest), duration=made.duration, length=made.width,
                                  reply_parameters=reply, reply_markup=round_keyboard(start, duration),
                                  request_timeout=120)
    except TelegramBadRequest as e:
        if "VOICE_MESSAGES_FORBIDDEN" not in e.message:
            raise
        raise UserError("rounds_forbidden") from e
    finally:
        dest.unlink(missing_ok=True)
