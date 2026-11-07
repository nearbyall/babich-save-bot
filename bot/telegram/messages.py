"""Reading incoming Telegram messages."""
from aiogram.types import Message

from ..links import Link, find_links


def text_of(message: Message | None) -> str:
    """Visible text plus the URLs hidden behind text links."""
    if message is None:
        return ""
    text = message.text or message.caption or ""
    hidden = [e.url for e in (message.entities or message.caption_entities or []) if e.url]
    return "\n".join([text, *hidden])


def is_from_bot(message: Message, bot_id: int) -> bool:
    return bool((message.from_user and message.from_user.id == bot_id)
                or (message.via_bot and message.via_bot.id == bot_id))


def links_from(message: Message, bot_id: int) -> list[Link]:
    """Links in the message, or else in the message it replies to.

    The bot's own messages are skipped: their captions link to the source, and a reply like
    "thanks" to a downloaded video must not download it again."""
    if links := find_links(text_of(message)):
        return links
    reply = message.reply_to_message
    if reply and not is_from_bot(reply, bot_id):
        return find_links(text_of(reply))
    return []


def mentions(message: Message, username: str) -> bool:
    return f"@{username}".lower() in (message.text or message.caption or "").lower()


def requester(message: Message) -> int:
    return message.from_user.id if message.from_user else message.chat.id


def topic(message: Message) -> int | None:
    return message.message_thread_id if message.is_topic_message else None
