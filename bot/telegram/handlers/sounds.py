"""Shazam and audio buttons under videos in DMs."""
from aiogram import Bot, Router
from aiogram.types import CallbackQuery, Message

from .. import sounds
from ..clips import clip_of
from ..keyboards import SoundButton, TrackButton

router = Router(name="sounds")


async def _ready(callback: CallbackQuery, started: str) -> bool:
    if not isinstance(callback.message, Message) or clip_of(callback.message) is None:
        await callback.answer("Видео не найдено — пришли ссылку заново.", show_alert=True)
        return False
    if sounds.busy(callback.from_user.id):
        await callback.answer("Секунду, ещё занят прошлым видео…")
        return False
    await callback.answer(started)
    return True


@router.callback_query(TrackButton.filter())
async def track_pressed(callback: CallbackQuery, bot: Bot) -> None:
    if await _ready(callback, "🎵 Слушаю…"):
        await sounds.identify(bot, callback.message, clip_of(callback.message), callback.from_user)


@router.callback_query(SoundButton.filter())
async def sound_pressed(callback: CallbackQuery, bot: Bot) -> None:
    if await _ready(callback, "🎧 Достаю звук…"):
        await sounds.send_sound(bot, callback.message, clip_of(callback.message), callback.from_user)
