"""/report in DMs: problems go to the owner, and the owner's answers go back to the user."""
import html
import logging

from aiogram import Bot, F, Router
from aiogram.enums import ChatType, ContentType
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandObject
from aiogram.types import ForceReply, Message

from ...db import Database
from .. import reports, texts
from ..messages import is_from_bot

log = logging.getLogger(__name__)
router = Router(name="reports")
router.message.filter(F.chat.type == ChatType.PRIVATE)


async def answered_report(message: Message, bot: Bot, db: Database) -> dict[str, int] | bool:
    """The owner's reply to a report header: whom the answer goes to. Async: aiogram runs sync filters in a
    thread, and the database can't be used from one."""
    reply = message.reply_to_message
    if not reply or not is_from_bot(reply, bot.id) or message.from_user.id != db.owner_id():
        return False
    user_id = db.reporter(reply.message_id)
    return {"user_id": user_id} if user_id else False


@router.message(answered_report)
async def answer_written(message: Message, bot: Bot, user_id: int) -> None:
    try:
        await reports.answer(bot, user_id, message)
    except TelegramForbiddenError:
        await message.reply("❌ Не доставил: пользователь заблокировал бота.")
    except TelegramBadRequest as e:
        await message.reply(f"❌ Не доставил: {html.escape(e.message)}")
    else:
        await message.reply("✅ Отправил.")


@router.message(F.reply_to_message.text == texts.REPORT_PROMPT)
async def report_described(message: Message, bot: Bot, db: Database) -> None:
    await _report(message, bot, db, message.text or message.caption or "", about=None)


@router.message(Command("report"))
async def report_command(message: Message, bot: Bot, db: Database, command: CommandObject) -> None:
    """/report text, or /report in reply to the message with the problem; a bare /report asks what's wrong."""
    about = message.reply_to_message
    if not command.args and not about and message.content_type == ContentType.TEXT:
        await message.answer(texts.REPORT_PROMPT, reply_markup=ForceReply(input_field_placeholder="Что не так?"))
        return
    await _report(message, bot, db, command.args or "", about)


async def _report(message: Message, bot: Bot, db: Database, text: str, about: Message | None) -> None:
    if reports.too_soon(message.from_user.id):
        await message.reply("Подожди немного перед следующим репортом.")
    elif await _send(message, bot, db, text, about):
        await message.reply("✅ Передал разработчику, спасибо! Ответ, если будет, придёт сюда.")
    else:
        await message.reply("❌ Не получилось отправить репорт. Попробуй ещё раз чуть позже.")


async def _send(message: Message, bot: Bot, db: Database, text: str, about: Message | None) -> bool:
    if not (owner := db.owner_id()):
        log.warning("report from %s dropped: the bot has no owner yet", message.from_user.id)
        return False
    try:
        header_id = await reports.send(bot, owner, message, text, about)
    except TelegramAPIError:
        log.exception("failed to send a report from %s", message.from_user.id)
        return False
    db.remember_report(header_id, message.from_user.id)
    log.info("report from %s sent", message.from_user.id)
    return True
