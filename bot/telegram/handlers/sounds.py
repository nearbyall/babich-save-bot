"""Shazam and audio buttons under videos in DMs."""
from aiogram import Bot, Router
from aiogram.types import CallbackQuery, Message

from .. import sounds
from ..clips import clip_of, video_message
from ..keyboards import SoundButton, TrackButton

router = Router(name="sounds")


async def _source(callback: CallbackQuery, started: str) -> Message | None:
    """The video the button works on, once the user can start a job on it."""
    source = video_message(callback.message) if isinstance(callback.message, Message) else None
    if source is None:
        await callback.answer("Видео не найдено — пришли его заново.", show_alert=True)
        return None
    if sounds.busy(callback.from_user.id):
        await callback.answer("Секунду, ещё занят прошлым видео…")
        return None
    await callback.answer(started)
    return source


@router.callback_query(TrackButton.filter())
async def track_pressed(callback: CallbackQuery, bot: Bot) -> None:
    if source := await _source(callback, "🎵 Слушаю…"):
        await sounds.identify(bot, source, clip_of(source), callback.from_user)


@router.callback_query(SoundButton.filter())
async def sound_pressed(callback: CallbackQuery, bot: Bot) -> None:
    if source := await _source(callback, "🎧 Достаю звук…"):
        await sounds.send_sound(bot, source, clip_of(source), callback.from_user)
