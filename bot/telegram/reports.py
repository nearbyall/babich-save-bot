"""Problem reports from users to the owner, and the owner's answers back."""
import html
import logging
import time

from aiogram import Bot
from aiogram.enums import ContentType
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message, ReplyParameters, User

from ..i18n import Lang, t

log = logging.getLogger(__name__)

INTERVAL = 30  # seconds between reports of one user
MAX_TEXT = 3500  # the header with the report has to fit in one message

_last_report: dict[int, float] = {}


def header(user: User, text: str, lang: Lang) -> str:
    """The report as the owner gets it, in the owner's language; searching for its #u<id> tag finds all reports
    of that user."""
    who = [f'<a href="tg://user?id={user.id}">{html.escape(user.full_name)}</a>']
    if user.username:
        who.append(f"@{html.escape(user.username)}")
    if user.language_code:
        who.append(html.escape(user.language_code))
    body = html.escape(text.strip()[:MAX_TEXT]) or t("report_no_text", lang)
    return (f"{t('report_mark', lang)} #u{user.id}\n👤 {' · '.join(who)}\n"
            f"<blockquote expandable>{body}</blockquote>\n{t('report_reply_hint', lang)}")


def too_soon(user_id: int) -> bool:
    """Whether the user's last report was less than INTERVAL ago; if not, this one counts as the last."""
    now = time.monotonic()
    last = _last_report.get(user_id)
    if last is not None and now - last < INTERVAL:
        return True
    _last_report[user_id] = now
    return False


async def send(bot: Bot, owner_id: int, owner_lang: Lang, report: Message, text: str,
               about: Message | None) -> int:
    """Send the owner the header, then the message the report is about and the report's own attachment as
    replies to it. Returns the header's message_id: answers go to whoever sent it, never to a user named in
    the text, since the copies are the bot's messages too and their text is the user's."""
    sent = await bot.send_message(owner_id, header(report.from_user, text, owner_lang))
    reply = ReplyParameters(message_id=sent.message_id, allow_sending_without_reply=True)
    attachment = report if report.content_type != ContentType.TEXT else None
    for message in filter(None, (about, attachment)):
        try:
            await message.copy_to(owner_id, reply_parameters=reply)
        except TelegramBadRequest as e:
            log.warning("failed to copy message %s of a report: %s", message.message_id, e)
    return sent.message_id


async def answer(bot: Bot, user_id: int, user_lang: Lang, message: Message) -> None:
    """Send the owner's answer to whoever reported."""
    title = t("report_answer", user_lang)
    if message.text:
        await bot.send_message(user_id, f"{title}\n\n{message.html_text}")
    else:
        await bot.send_message(user_id, title)
        await message.copy_to(user_id)
