"""Which language the bot speaks to whom: Russian, unless the user picked English with /lang."""
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand, BotCommandScopeChat, TelegramObject, User

from .. import i18n
from ..db import Database
from ..i18n import Lang, t

log = logging.getLogger(__name__)


class LanguageMiddleware(BaseMiddleware):
    """Sets the language of whoever sent the update for everything that handles it."""

    async def __call__(self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
                      event: TelegramObject, data: dict[str, Any]) -> Any:
        user: User | None = data.get("event_from_user")
        db: Database = data["db"]
        token = i18n.current.set(db.lang(user.id) if user else i18n.DEFAULT)
        try:
            return await handler(event, data)
        finally:
            i18n.current.reset(token)


def dm_commands(lang: Lang) -> list[BotCommand]:
    return [BotCommand(command=command, description=t(f"cmd_{command}", lang))
            for command in ("start", "report", "lang")]


def group_commands(lang: Lang) -> list[BotCommand]:
    return [BotCommand(command="dl", description=t("cmd_dl", lang))]


async def choose(bot: Bot, db: Database, user_id: int, lang: Lang) -> None:
    """Speak `lang` to the user from now on, the rest of this update included, and show the menu in it."""
    db.set_lang(user_id, lang)
    i18n.current.set(lang)
    try:
        await bot.set_my_commands(dm_commands(lang), scope=BotCommandScopeChat(chat_id=user_id))
    except TelegramAPIError:
        log.warning("failed to set the menu of %s", user_id, exc_info=True)
