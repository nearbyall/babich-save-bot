"""Round video buttons under videos in DMs, and under the round videos made from them."""
from aiogram import Bot, Router
from aiogram.types import CallbackQuery, Message

from ...media.rounds import LENGTH
from .. import rounds
from ..clips import clip_of, video_message
from ..keyboards import RoundButton

router = Router(name="rounds")


@router.callback_query(RoundButton.filter())
async def round_pressed(callback: CallbackQuery, callback_data: RoundButton, bot: Bot) -> None:
    message = callback.message
    source = None
    if isinstance(message, Message):
        # Round videos with buttons are the bot's own, made from the video they reply to
        source = message.reply_to_message if message.video_note else video_message(message)
    clip = clip_of(source)
    if clip is None:
        await callback.answer("Видео не найдено — пришли его заново.", show_alert=True)
        return
    if rounds.busy(callback.from_user.id):
        await callback.answer("Секунду, ещё делаю прошлый кружок…")
        return
    if not callback_data.start and (clip.duration or 0) > LENGTH:
        await callback.answer("⚪ Делаю кружок из первой минуты, под ним будут кнопки следующих.")
    else:
        await callback.answer("⚪ Делаю кружок…")
    await rounds.make(bot, source, clip, callback.from_user, callback_data.start)
