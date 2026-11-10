"""/lang in DMs: Russian, the default, or English."""
import contextlib

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from ... import i18n
from ...db import Database
from ...i18n import t
from .. import languages
from ..keyboards import LangButton, lang_keyboard

router = Router(name="languages")


@router.message(F.chat.type == ChatType.PRIVATE, Command("lang"))
async def lang_command(message: Message, bot: Bot, db: Database, command: CommandObject) -> None:
    """/lang shows the choice; /lang en or /lang ru switches at once."""
    lang = (command.args or "").strip().lower()
    if lang in i18n.LANGS:
        await languages.choose(bot, db, message.from_user.id, lang)
        await message.answer(t("lang_set"))
        return
    await message.answer(t("lang_choose"), reply_markup=lang_keyboard(i18n.current.get()))


@router.callback_query(LangButton.filter())
async def lang_pressed(callback: CallbackQuery, callback_data: LangButton, bot: Bot, db: Database) -> None:
    lang = callback_data.lang if callback_data.lang in i18n.LANGS else i18n.DEFAULT
    await languages.choose(bot, db, callback.from_user.id, lang)
    await callback.answer()
    if isinstance(callback.message, Message):
        with contextlib.suppress(TelegramAPIError):  # "not modified" when tapped twice
            await callback.message.edit_text(t("lang_set"))
