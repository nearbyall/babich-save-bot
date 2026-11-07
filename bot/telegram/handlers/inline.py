"""Inline mode ("@bot link" picked from the pop-up) and guest mode ("@bot link" sent in a chat the bot isn't in).

Both end up in an inline message that holds one file. If the download isn't ready in time, a placeholder
is sent instead and edited into the file once it is."""
import asyncio
import contextlib
import hashlib
import logging
from collections import OrderedDict

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    ChosenInlineResult,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InlineQueryResultsButton,
    InputTextMessageContent,
    Message,
)

from ... import config
from ...db import Cached, CachedFile, CachedPost, Database
from ...errors import UserError
from ...links import Link, find_links
from .. import texts
from ..delivery import fetch_media, inline_result, input_media
from ..keyboards import LoadButton, placeholder_keyboard, post_keyboard
from ..messages import links_from, mentions, requester

log = logging.getLogger(__name__)
router = Router(name="inline")

PLACEHOLDER = "load:"


class _Placeholders:
    """Links behind placeholder messages, by short ids that fit into callback data."""

    def __init__(self, size: int = 1000) -> None:
        self._links: OrderedDict[str, Link] = OrderedDict()
        self._size = size

    def add(self, link: Link) -> str:
        pid = hashlib.sha1(link.key.encode()).hexdigest()[:16]
        self._links[pid] = link
        self._links.move_to_end(pid)
        while len(self._links) > self._size:
            self._links.popitem(last=False)
        return pid

    def get(self, pid: str) -> Link | None:
        return self._links.get(pid)


_placeholders = _Placeholders()


def _shown(cached: Cached, username: str) -> tuple[CachedFile, InlineKeyboardMarkup | None]:
    """The file an inline message shows: a post's first one, with a button for the rest."""
    if isinstance(cached, CachedPost):
        return cached.items[0], post_keyboard(username, cached)
    return cached, None


async def _show_error(bot: Bot, inline_message_id: str, text: str) -> None:
    try:
        await bot.edit_message_text(text=f"❌ {text}", inline_message_id=inline_message_id)
    except TelegramAPIError as e:
        log.info("can't show error in inline message: %s", e)


async def fill_placeholder(bot: Bot, db: Database, link: Link, user_id: int, inline_message_id: str) -> None:
    try:
        cached = await fetch_media(bot, db, link, user_id)
        me = await bot.me()
        item, keyboard = _shown(cached, me.username)
        await bot.edit_message_media(media=input_media(item, texts.caption(link, cached.uploader)),
                                     inline_message_id=inline_message_id, reply_markup=keyboard)
    except UserError as e:
        await _show_error(bot, inline_message_id, str(e))
    except TelegramBadRequest as e:
        if "not modified" in str(e):  # already filled by a parallel request
            return
        log.exception("failed to put media into inline message for %s", link.url)
        await _show_error(bot, inline_message_id, "Не получилось вставить файл в сообщение. Попробуй ещё раз.")
    except Exception:
        log.exception("unexpected error for %s", link.url)
        await _show_error(bot, inline_message_id, texts.FAILED)


@router.inline_query()
async def inline_query(query: InlineQuery, bot: Bot, db: Database) -> None:
    if not (links := find_links(query.query)):
        await query.answer([], cache_time=3600, button=InlineQueryResultsButton(
            text="Paste a TikTok/Reels/Shorts link · Вставь ссылку", start_parameter="help"))
        return
    link = links[0]
    try:
        cached = await asyncio.wait_for(fetch_media(bot, db, link, query.from_user.id), config.INLINE_WAIT)
    except asyncio.TimeoutError:
        cached = None  # fetch_media keeps downloading in the background
    except Exception as e:
        if not isinstance(e, UserError):
            log.exception("unexpected error for %s", link.url)
        text = str(e) if isinstance(e, UserError) else texts.FAILED
        with contextlib.suppress(TelegramAPIError):
            await query.answer([], cache_time=0, is_personal=True,
                               button=InlineQueryResultsButton(text=f"❌ {text}"[:64], start_parameter="help"))
        return

    try:
        if cached:
            me = await bot.me()
            item, keyboard = _shown(cached, me.username)
            post = isinstance(cached, CachedPost)
            description = " · ".join(filter(None, [link.platform, cached.uploader,
                                                   post and texts.post_summary(cached)]))
            await query.answer([inline_result(item, texts.caption(link, cached.uploader),
                                              title="📥 Отправить" if post else "📥 Отправить видео",
                                              description=description, reply_markup=keyboard)], cache_time=3600)
        else:
            # Without a keyboard Telegram doesn't hand back the inline_message_id needed to edit it later
            pid = _placeholders.add(link)
            await query.answer([InlineQueryResultArticle(
                id=PLACEHOLDER + pid,
                title="📥 Отправить",
                description="Ещё скачивается — сообщение обновится само",
                input_message_content=InputTextMessageContent(message_text=texts.loading(link)),
                reply_markup=placeholder_keyboard(pid),
            )], cache_time=0, is_personal=True)
    except TelegramBadRequest as e:
        log.info("inline query for %s expired: %s", link.key, e)


@router.chosen_inline_result(F.result_id.startswith(PLACEHOLDER))
async def placeholder_sent(result: ChosenInlineResult, bot: Bot, db: Database) -> None:
    if result.inline_message_id and (links := find_links(result.query)):
        await fill_placeholder(bot, db, links[0], result.from_user.id, result.inline_message_id)


@router.callback_query(LoadButton.filter())
async def placeholder_refresh(callback: CallbackQuery, callback_data: LoadButton, bot: Bot, db: Database) -> None:
    """For when inline feedback is off: anyone can tap to load the file."""
    link = _placeholders.get(callback_data.placeholder)
    if not callback.inline_message_id or not link:
        await callback.answer("Ссылка устарела — отправь её заново.")
        return
    await callback.answer("Загружаю…")
    await fill_placeholder(bot, db, link, callback.from_user.id, callback.inline_message_id)


def _article(text: str) -> InlineQueryResultArticle:
    return InlineQueryResultArticle(id="status", title="Babich Save",
                                    input_message_content=InputTextMessageContent(message_text=text))


@router.guest_message()
async def guest_message(message: Message, bot: Bot, db: Database) -> None:
    query_id = message.guest_query_id
    me = await bot.me()
    if not (links := links_from(message, me.id)):
        # Replies to the bot's messages come here too; only explicit mentions get the help
        if mentions(message, me.username):
            await bot.answer_guest_query(query_id, _article(texts.help_text(me.username)))
        return
    link = links[0]

    if cached := db.get(link.key):
        item, keyboard = _shown(cached, me.username)
        try:
            await bot.answer_guest_query(query_id, inline_result(item, texts.caption(link, cached.uploader),
                                                                 title="📥 Отправить", reply_markup=keyboard))
            return
        except TelegramBadRequest as e:
            log.warning("cached file for %s is unusable in guest mode (%s)", link.key, e)
            db.forget(cached)

    sent = await bot.answer_guest_query(query_id, _article(texts.loading(link)))
    await fill_placeholder(bot, db, link, requester(message), sent.inline_message_id)
