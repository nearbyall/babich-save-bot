"""Who uses the bot and where, for /stats: a mark per user, day and place, nothing of what they send."""
import logging
import re
import sqlite3
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Bot
from aiogram.enums import ChatType
from aiogram.types import Message, Update, User

from ..db import Database
from ..links import from_payload
from .messages import GROUP_CHATS, is_from_bot, mentions

log = logging.getLogger(__name__)

DM, GROUP, INLINE, GUEST = "dm", "group", "inline", "guest"
POST = "post"  # the «whole post» button under an inline message, pressed by someone else in that chat


class StatsMiddleware(BaseMiddleware):
    async def __call__(self, handler: Callable[[Update, dict[str, Any]], Awaitable[Any]],
                       event: Update, data: dict[str, Any]) -> Any:
        try:
            await _record(event, data["bot"], data["db"], data.get("event_from_user"))
        except sqlite3.Error:
            log.exception("failed to record stats")
        return await handler(event, data)


async def _record(update: Update, bot: Bot, db: Database, user: User | None) -> None:
    if (message := update.message) and message.chat.type in GROUP_CHATS:
        db.mark_group(message.chat.id)
    if user and not user.is_bot and (where := await place(update, bot)):
        db.mark_seen(user.id, where, source(update) or where)


async def place(update: Update, bot: Bot) -> str | None:
    """Where the user used the bot, or None if the update isn't them using it."""
    if update.inline_query or update.chosen_inline_result:
        return INLINE
    if update.guest_message:
        return GUEST
    if update.pre_checkout_query:
        return DM
    if callback := update.callback_query:
        if callback.inline_message_id or not callback.message:
            return INLINE
        return DM if callback.message.chat.type == ChatType.PRIVATE else GROUP
    if message := update.message:
        if message.chat.type == ChatType.PRIVATE:
            return DM
        if message.chat.type in GROUP_CHATS and await _addressed(message, bot):
            return GROUP
    return None


async def _addressed(message: Message, bot: Bot) -> bool:
    """A group message meant for the bot: a command to it, a reply to it or a mention of it."""
    me = await bot.me()
    text = message.text or message.caption or ""
    if text.startswith("/"):
        target = text.split(maxsplit=1)[0].partition("@")[2]
        if not target or target.lower() == me.username.lower():
            return True
    reply = message.reply_to_message
    return mentions(message, me.username) or bool(reply and is_from_bot(reply, me.id))


def source(update: Update) -> str | None:
    """Where a /start link came from: a shared post, the inline pop-up's hint or an ad (t.me/bot?start=ad_x)."""
    message = update.message
    if not message or message.chat.type != ChatType.PRIVATE or not message.text:
        return None
    command, _, payload = message.text.partition(" ")
    if command != "/start" or not (payload := payload.strip()):
        return None
    if from_payload(payload):
        return POST
    if payload == "help":
        return INLINE
    return re.sub(r"[^\w-]", "", payload)[:32] or None
