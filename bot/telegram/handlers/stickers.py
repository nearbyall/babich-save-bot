"""Video stickers, in DMs only."""
import contextlib
import logging

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message

from ...media.sticker import Cut, parse_time
from .. import texts
from ..keyboards import CurrentButton, CutButton, KeepButton, describe, is_kept, kept_keyboard
from ..stickers import add_to_pack, busy, clip_of, make

log = logging.getLogger(__name__)
router = Router(name="stickers")
router.message.filter(F.chat.type == ChatType.PRIVATE)

HINT = "Под ним — сдвиг, скорость и форма. Точный момент — ответь на видео временем, например 0:12 или 0:12-0:14"


@router.callback_query(CutButton.filter())
async def cut_pressed(callback: CallbackQuery, callback_data: CutButton, bot: Bot) -> None:
    """🎭 under a video, or a move/speed/shape button under a sticker made from it."""
    message = callback.message
    if not isinstance(message, Message):
        await callback.answer("Сообщение устарело — пришли видео заново.", show_alert=True)
        return
    if busy(callback.from_user.id):
        await callback.answer(texts.STICKER_BUSY)
        return
    cut = callback_data.cut()
    redo = message.sticker is not None
    source = message.reply_to_message if redo else message
    if source is None:
        await callback.answer("Видео удалено — пришли его заново.", show_alert=True)
        return
    if redo:
        clip = clip_of(source)
        await callback.answer(f"⏳ {describe(cut, clip and clip.duration)}")
    else:
        await callback.answer(f"🎭 Делаю стикер из первых {cut.length:g} секунд. {HINT}")
    if await make(bot, source, callback.from_user, cut) and redo and not is_kept(message.reply_markup):
        with contextlib.suppress(TelegramAPIError):
            await message.delete()  # replaced by the new cut, unless it's already in the pack


@router.callback_query(CurrentButton.filter())
async def current_pressed(callback: CallbackQuery) -> None:
    await callback.answer("Уже так")


@router.callback_query(KeepButton.filter())
async def keep_pressed(callback: CallbackQuery, bot: Bot) -> None:
    message = callback.message
    if not isinstance(message, Message) or not message.sticker:
        await callback.answer("Стикер не найден.")
        return
    if busy(callback.from_user.id):
        await callback.answer("Секунду…")
        return
    try:
        pack = await add_to_pack(bot, callback.from_user, message.sticker.file_id)
    except TelegramAPIError as e:
        log.warning("failed to add sticker to the pack of %s: %s", callback.from_user.id, e)
        await callback.answer("Не получилось добавить в пак, попробуй ещё раз.", show_alert=True)
        return
    with contextlib.suppress(TelegramAPIError):
        await message.edit_reply_markup(reply_markup=kept_keyboard(message.reply_markup, pack))
    await callback.answer("✅ Добавил в твой пак")


@router.message(F.text.func(parse_time))
async def time_sent(message: Message, bot: Bot) -> None:
    """A time in reply to a video: cut the sticker from there."""
    source = message.reply_to_message
    if clip_of(source) is None:
        hint = ("ответь временем на само видео, а не на стикер" if source and source.sticker
                else "ответь этим временем на видео")
        await message.reply(f"Чтобы сделать стикер с этого момента, {hint}.")
        return
    if busy(message.from_user.id):
        await message.reply(texts.STICKER_BUSY)
        return
    await make(bot, source, message.from_user, Cut.covering(*parse_time(message.text)))


@router.message(F.video | F.animation | F.video_note | F.document.mime_type.startswith("video/"))
async def video_sent(message: Message, bot: Bot) -> None:
    """Any video, GIF or round video sent or forwarded to the bot becomes a sticker."""
    if busy(message.from_user.id):
        await message.reply(texts.STICKER_BUSY)
        return
    await make(bot, message, message.from_user, Cut())
