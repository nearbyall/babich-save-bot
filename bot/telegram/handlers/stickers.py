"""Video stickers, in DMs only."""
import contextlib
import logging

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message

from ...i18n import t
from ...media.sticker import Cut, parse_time
from ..keyboards import CurrentButton, CutButton, KeepButton, describe, is_kept, kept_keyboard
from ..clips import clip_of, video_message
from ..stickers import add_to_pack, busy, make

log = logging.getLogger(__name__)
router = Router(name="stickers")
router.message.filter(F.chat.type == ChatType.PRIVATE)


@router.callback_query(CutButton.filter())
async def cut_pressed(callback: CallbackQuery, callback_data: CutButton, bot: Bot) -> None:
    """🎭 under a video, or a move/speed/shape button under a sticker made from it."""
    message = callback.message
    if not isinstance(message, Message):
        await callback.answer(t("message_expired"), show_alert=True)
        return
    if busy(callback.from_user.id):
        await callback.answer(t("sticker_busy"))
        return
    cut = callback_data.cut()
    redo = message.sticker is not None
    source = video_message(message)
    if source is None:
        await callback.answer(t("video_deleted"), show_alert=True)
        return
    if redo:
        clip = clip_of(source)
        await callback.answer(f"⏳ {describe(cut, clip and clip.duration)}")
    else:
        await callback.answer(t("making_sticker", seconds=cut.length))
    if await make(bot, source, callback.from_user, cut) and redo and not is_kept(message.reply_markup):
        with contextlib.suppress(TelegramAPIError):
            await message.delete()  # replaced by the new cut, unless it's already in the pack


@router.callback_query(CurrentButton.filter())
async def current_pressed(callback: CallbackQuery) -> None:
    await callback.answer(t("already_so"))


@router.callback_query(KeepButton.filter())
async def keep_pressed(callback: CallbackQuery, bot: Bot) -> None:
    message = callback.message
    if not isinstance(message, Message) or not message.sticker:
        await callback.answer(t("sticker_not_found"))
        return
    if busy(callback.from_user.id):
        await callback.answer(t("one_moment"))
        return
    try:
        pack = await add_to_pack(bot, callback.from_user, message.sticker.file_id)
    except TelegramAPIError as e:
        log.warning("failed to add sticker to the pack of %s: %s", callback.from_user.id, e)
        await callback.answer(t("pack_failed"), show_alert=True)
        return
    with contextlib.suppress(TelegramAPIError):
        await message.edit_reply_markup(reply_markup=kept_keyboard(message.reply_markup, pack))
    await callback.answer(t("pack_added"))


@router.message(F.text.func(parse_time))
async def time_sent(message: Message, bot: Bot) -> None:
    """A time in reply to a video: cut the sticker from there."""
    source = message.reply_to_message
    if clip_of(source) is None:
        await message.reply(t("time_to_sticker" if source and source.sticker else "time_to_video"))
        return
    if busy(message.from_user.id):
        await message.reply(t("sticker_busy"))
        return
    await make(bot, source, message.from_user, Cut.covering(*parse_time(message.text)))
