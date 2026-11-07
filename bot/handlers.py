import asyncio
import contextlib
import hashlib
import logging
from collections import OrderedDict

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    CallbackQuery,
    ChosenInlineResult,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InlineQueryResultsButton,
    InputTextMessageContent,
    Message,
)
from aiogram.utils.chat_action import ChatActionSender

from . import config
from .db import CachedPost, CachedVideo, Database
from .delivery import (
    Cached,
    cached_result,
    caption,
    fetch_media,
    input_media,
    post_keyboard,
    send_cached_post,
    tracked,
    upload,
    upload_album,
)
from .downloader import Album, DownloadError, download
from .links import Link, find_links, from_payload, is_from_bot, links_from
from .stickers import sticker_button

log = logging.getLogger(__name__)
router = Router()

GROUP_CHATS = {ChatType.GROUP, ChatType.SUPERGROUP}
NO_LINKS = (
    "Send me a TikTok, Instagram or YouTube Shorts link.\n"
    "Пришли ссылку на TikTok, Instagram или YouTube Shorts."
)
FAILED = "Не удалось скачать видео. Попробуй ещё раз чуть позже."


def _mentions(message: Message, username: str) -> bool:
    return f"@{username}".lower() in (message.text or message.caption or "").lower()


def _requester(message: Message) -> int:
    return message.from_user.id if message.from_user else message.chat.id


def help_text(username: str) -> str:
    return (
        "🇬🇧 <b>Send a TikTok, Instagram or YouTube Shorts link — I'll send back the video, "
        "photos or slideshow.</b>\n"
        f"Any chat: type <code>@{username} link</code> and tap what pops up.\n"
        "Groups I'm in: <code>/dl link</code>.\n"
        "🎭 Video sticker: tap the button under a video, or send me any video or GIF. "
        "Buttons under the sticker move it, change speed and shape; "
        "reply to the video with a time like <code>0:12</code> to cut from there.\n\n"
        "🇷🇺 <b>Пришли ссылку на TikTok, Instagram или YouTube Shorts — пришлю видео, фото или слайдшоу.</b>\n"
        f"Любой чат: набери <code>@{username} ссылка</code> и нажми на то, что появится.\n"
        "Группы, где я есть: <code>/dl ссылка</code>.\n"
        "🎭 Видеостикер: кнопка под видео или пришли мне любое видео или GIF. "
        "Кнопки под стикером двигают его, меняют скорость и форму; "
        "ответь на видео временем, например <code>0:12</code>, — вырежу с этого места."
    )


# --- DMs and groups the bot is a member of: upload straight into the chat ---

def _thread(message: Message) -> int | None:
    return message.message_thread_id if message.is_topic_message else None


def _video_keyboard(message: Message) -> InlineKeyboardMarkup | None:
    """Stickers are made in DMs only: they go into the user's own pack."""
    return sticker_button() if message.chat.type == ChatType.PRIVATE else None


async def _reply_cached(message: Message, cached: Cached, text: str) -> None:
    if isinstance(cached, CachedPost):
        await send_cached_post(message.bot, message.chat.id, cached, text, message_thread_id=_thread(message),
                               reply_parameters=message.as_reply_parameters(allow_sending_without_reply=True))
    elif cached.kind == "video":
        await message.reply_video(cached.file_id, caption=text, supports_streaming=True,
                                  width=cached.width, height=cached.height, duration=cached.duration,
                                  reply_markup=_video_keyboard(message))
    elif cached.kind == "animation":
        await message.reply_animation(cached.file_id, caption=text, reply_markup=_video_keyboard(message))
    elif cached.kind == "photo":
        await message.reply_photo(cached.file_id, caption=text)
    else:
        await message.reply_document(cached.file_id, caption=text)


async def deliver(message: Message, link: Link, db: Database) -> None:
    if cached := db.get_media(link.key):
        try:
            await _reply_cached(message, cached, caption(link, cached.uploader))
            return
        except TelegramBadRequest as e:
            log.warning("cached file for %s is unusable (%s), downloading again", link.key, e)
            db.forget_media(cached)

    async with ChatActionSender.upload_video(bot=message.bot, chat_id=message.chat.id,
                                             message_thread_id=message.message_thread_id):
        try:
            media = await download(link, _requester(message))
        except DownloadError as e:
            await message.reply(f"❌ {e}")
            return
        except Exception:
            log.exception("unexpected error downloading %s", link.url)
            await message.reply(f"❌ {FAILED}")
            return
        if isinstance(media, Album):
            send, extra = upload_album, {}  # media groups can't have buttons
        else:
            send, extra = upload, {"reply_markup": _video_keyboard(message)}
        try:
            _, cached = await send(message.bot, message.chat.id, media, caption(link, media.uploader),
                                   message_thread_id=_thread(message),
                                   reply_parameters=message.as_reply_parameters(allow_sending_without_reply=True),
                                   **extra)
        except TelegramAPIError:
            log.exception("failed to upload %s", link.url)
            await message.reply("❌ Telegram не принял файл. Попробуй ещё раз.")
            return
        finally:
            media.cleanup()
    db.put_media(media.keys, cached)


async def handle_links(message: Message, links: list[Link], db: Database) -> None:
    with tracked():
        for link in links[: config.MAX_LINKS_PER_MESSAGE]:
            await deliver(message, link, db)


@router.message(CommandStart())
@router.message(Command("help"))  # not in the menu, but people type it out of habit
async def cmd_start(message: Message, bot: Bot, db: Database, command: CommandObject) -> None:
    if message.chat.type == ChatType.PRIVATE and db.remember_owner(message.from_user.id):
        log.info("owner set to %s (%s)", message.from_user.id, message.from_user.username)
    # "Весь пост" button under an inline/guest photo: t.me/bot?start=tt_123
    if command.args and (link := from_payload(command.args)):
        await handle_links(message, [link], db)
        return
    me = await bot.me()
    await message.answer(help_text(me.username))


@router.message(Command("dl", "save", "download"))
async def cmd_download(message: Message, bot: Bot, db: Database) -> None:
    links = links_from(message, bot.id)
    if not links:
        await message.reply(f"{NO_LINKS}\n<code>/dl https://vm.tiktok.com/…</code>")
        return
    await handle_links(message, links, db)


@router.message(F.chat.type == ChatType.PRIVATE)
async def private_message(message: Message, bot: Bot, db: Database) -> None:
    if db.remember_owner(message.from_user.id):
        log.info("owner set to %s (%s)", message.from_user.id, message.from_user.username)
    links = links_from(message, bot.id)
    if not links:
        await message.reply(NO_LINKS)
        return
    await handle_links(message, links, db)


@router.message(F.chat.type.in_(GROUP_CHATS))
async def group_message(message: Message, bot: Bot, db: Database) -> None:
    """Only react when the bot is mentioned or replied to."""
    me = await bot.me()
    mentioned = _mentions(message, me.username)
    if not mentioned and not (message.reply_to_message and is_from_bot(message.reply_to_message, me.id)):
        return
    links = links_from(message, me.id)
    if not links:
        if mentioned:
            await message.reply(NO_LINKS)
        return
    await handle_links(message, links, db)


# --- Inline messages ("⏳ downloading" placeholders that turn into the video) ---

# Links behind placeholder buttons, by short id (callback data is limited to 64 bytes)
_placeholders: OrderedDict[str, Link] = OrderedDict()


def _placeholder_id(link: Link) -> str:
    pid = hashlib.sha1(link.key.encode()).hexdigest()[:16]
    _placeholders[pid] = link
    _placeholders.move_to_end(pid)
    while len(_placeholders) > 1000:
        _placeholders.popitem(last=False)
    return pid


def _loading_text(link: Link) -> str:
    return f"⏳ Скачиваю из {link.platform}…"


def _shown(cached: Cached, username: str) -> tuple[CachedVideo, InlineKeyboardMarkup | None]:
    """Inline and guest messages hold one file: a post's first one, with a button to the rest."""
    if isinstance(cached, CachedPost):
        return cached.items[0], post_keyboard(username, cached)
    return cached, None


async def _show_error(bot: Bot, inline_message_id: str, text: str) -> None:
    try:
        await bot.edit_message_text(text=f"❌ {text}", inline_message_id=inline_message_id)
    except TelegramAPIError as e:
        log.info("can't show error in inline message: %s", e)


async def fill_inline_message(bot: Bot, db: Database, link: Link, user_id: int, inline_message_id: str) -> None:
    """Turn a placeholder inline message into the video, or into an error."""
    try:
        cached = await fetch_media(bot, db, link, user_id)
        me = await bot.me()
        item, keyboard = _shown(cached, me.username)
        await bot.edit_message_media(media=input_media(item, caption(link, cached.uploader)),
                                     inline_message_id=inline_message_id, reply_markup=keyboard)
    except DownloadError as e:
        await _show_error(bot, inline_message_id, str(e))
    except TelegramBadRequest as e:
        if "not modified" in str(e):  # already filled by a parallel request
            return
        log.exception("failed to put media into inline message for %s", link.url)
        await _show_error(bot, inline_message_id, "Не получилось вставить файл в сообщение. Попробуй ещё раз.")
    except Exception:
        log.exception("unexpected error for %s", link.url)
        await _show_error(bot, inline_message_id, FAILED)


# --- Inline mode: user types "@babichsavebot <link>" and sends the video "via" the bot ---

@router.inline_query()
async def inline_query(query: InlineQuery, bot: Bot, db: Database) -> None:
    links = find_links(query.query)
    if not links:
        await query.answer([], cache_time=3600, button=InlineQueryResultsButton(
            text="Paste a TikTok/Reels/Shorts link · Вставь ссылку", start_parameter="help"))
        return
    link = links[0]
    try:
        cached = await asyncio.wait_for(fetch_media(bot, db, link, query.from_user.id), config.INLINE_WAIT)
    except asyncio.TimeoutError:
        cached = None  # still downloading; fetch_media keeps it going in the background
    except Exception as e:
        if not isinstance(e, DownloadError):
            log.exception("unexpected error for %s", link.url)
        text = str(e) if isinstance(e, DownloadError) else FAILED
        with contextlib.suppress(TelegramAPIError):
            await query.answer([], cache_time=0, is_personal=True,
                               button=InlineQueryResultsButton(text=f"❌ {text}"[:64], start_parameter="help"))
        return

    try:
        if cached:
            me = await bot.me()
            item, keyboard = _shown(cached, me.username)
            post = isinstance(cached, CachedPost)
            description = " · ".join(filter(None, [link.platform, cached.uploader, post and cached.summary]))
            await query.answer([cached_result(item, caption(link, cached.uploader),
                                              title="📥 Отправить" if post else "📥 Отправить видео",
                                              description=description, reply_markup=keyboard)], cache_time=3600)
        else:
            # The keyboard is what makes Telegram hand back inline_message_id for later editing
            pid = _placeholder_id(link)
            await query.answer([InlineQueryResultArticle(
                id=f"load:{pid}",
                title="📥 Отправить",
                description="Ещё скачивается — сообщение обновится само",
                input_message_content=InputTextMessageContent(message_text=_loading_text(link)),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="🔄 Обновить", callback_data=f"load:{pid}")]]),
            )], cache_time=0, is_personal=True)
    except TelegramBadRequest as e:
        log.info("inline query for %s expired: %s", link.key, e)


@router.chosen_inline_result(F.result_id.startswith("load:"))
async def chosen_placeholder(result: ChosenInlineResult, bot: Bot, db: Database) -> None:
    links = find_links(result.query)
    if result.inline_message_id and links:
        await fill_inline_message(bot, db, links[0], result.from_user.id, result.inline_message_id)


@router.callback_query(F.data.startswith("load:"))
async def refresh_placeholder(callback: CallbackQuery, bot: Bot, db: Database) -> None:
    """Fallback for when inline feedback is off: anyone can tap to load the video."""
    link = _placeholders.get(callback.data.removeprefix("load:"))
    if not callback.inline_message_id or not link:
        await callback.answer("Ссылка устарела — отправь её заново.")
        return
    await callback.answer("Загружаю…")
    await fill_inline_message(bot, db, link, callback.from_user.id, callback.inline_message_id)


# --- Guest mode: "@babichsavebot <link>" sent as a message in a chat the bot isn't in ---

def _article(text: str) -> InlineQueryResultArticle:
    return InlineQueryResultArticle(
        id="status", title="Babich Save", input_message_content=InputTextMessageContent(message_text=text)
    )


@router.guest_message()
async def guest_message(message: Message, bot: Bot, db: Database) -> None:
    query_id = message.guest_query_id
    me = await bot.me()
    links = links_from(message, me.id)
    if not links:
        # Replies to the bot's messages also arrive here; only answer explicit mentions
        if _mentions(message, me.username):
            await bot.answer_guest_query(query_id, _article(help_text(me.username)))
        return
    link = links[0]

    if cached := db.get_media(link.key):
        item, keyboard = _shown(cached, me.username)
        try:
            await bot.answer_guest_query(query_id, cached_result(item, caption(link, cached.uploader),
                                                                 reply_markup=keyboard))
            return
        except TelegramBadRequest as e:
            log.warning("cached file for %s is unusable in guest mode (%s)", link.key, e)
            db.forget_media(cached)

    sent = await bot.answer_guest_query(query_id, _article(_loading_text(link)))
    await fill_inline_message(bot, db, link, _requester(message), sent.inline_message_id)
