"""DMs and groups the bot is a member of: files are uploaded straight into the chat."""
import logging

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import InlineKeyboardMarkup, Message
from aiogram.utils.chat_action import ChatActionSender

from ... import config, jobs
from ...db import Cached, CachedFile, Database
from ...errors import UserError
from ...links import Link, from_payload
from ...media.downloader import download
from ...media.models import Download, Video
from .. import texts
from ..delivery import send_cached, upload
from ..keyboards import sticker_button
from ..messages import is_from_bot, links_from, mentions, requester, topic

log = logging.getLogger(__name__)
router = Router(name="chats")

GROUP_CHATS = {ChatType.GROUP, ChatType.SUPERGROUP}


def _sticker_markup(message: Message, media: Download | Cached) -> InlineKeyboardMarkup | None:
    """Stickers go into the user's own pack, so they're made in DMs only, from single clips."""
    if message.chat.type != ChatType.PRIVATE:
        return None
    clip = isinstance(media, Video) or (isinstance(media, CachedFile) and media.kind in ("video", "animation"))
    return sticker_button() if clip else None


async def _send_from_cache(message: Message, link: Link, db: Database) -> bool:
    if not (cached := db.get(link.key)):
        return False
    try:
        await send_cached(message.bot, message.chat.id, cached, texts.caption(link, cached.uploader),
                          message_thread_id=topic(message), reply_markup=_sticker_markup(message, cached),
                          reply_parameters=message.as_reply_parameters(allow_sending_without_reply=True))
        return True
    except TelegramBadRequest as e:
        log.warning("cached file for %s is unusable (%s), downloading again", link.key, e)
        db.forget(cached)
        return False


async def _download_and_send(message: Message, link: Link, db: Database) -> None:
    async with ChatActionSender.upload_video(bot=message.bot, chat_id=message.chat.id,
                                             message_thread_id=message.message_thread_id):
        try:
            media = await download(link, requester(message))
        except UserError as e:
            await message.reply(f"❌ {e}")
            return
        except Exception:
            log.exception("unexpected error downloading %s", link.url)
            await message.reply(f"❌ {texts.FAILED}")
            return
        try:
            _, cached = await upload(message.bot, message.chat.id, media, texts.caption(link, media.uploader),
                                     reply_markup=_sticker_markup(message, media), message_thread_id=topic(message),
                                     reply_parameters=message.as_reply_parameters(allow_sending_without_reply=True))
        except TelegramAPIError:
            log.exception("failed to upload %s", link.url)
            await message.reply("❌ Telegram не принял файл. Попробуй ещё раз.")
            return
        finally:
            media.cleanup()
    db.put(media.keys, cached)


async def handle_links(message: Message, links: list[Link], db: Database) -> None:
    with jobs.tracked():
        for link in links[: config.MAX_LINKS_PER_MESSAGE]:
            if not await _send_from_cache(message, link, db):
                await _download_and_send(message, link, db)


def _remember_owner(message: Message, db: Database) -> None:
    if message.chat.type == ChatType.PRIVATE and db.remember_owner(message.from_user.id):
        log.info("owner set to %s (%s)", message.from_user.id, message.from_user.username)


@router.message(CommandStart())
@router.message(Command("help"))
async def start(message: Message, bot: Bot, db: Database, command: CommandObject) -> None:
    _remember_owner(message, db)
    # The "whole post" button under inline and guest photos opens t.me/bot?start=<post>
    if command.args and (link := from_payload(command.args)):
        await handle_links(message, [link], db)
        return
    me = await bot.me()
    await message.answer(texts.help_text(me.username))


@router.message(Command("dl", "save", "download"))
async def download_command(message: Message, bot: Bot, db: Database) -> None:
    if not (links := links_from(message, bot.id)):
        await message.reply(f"{texts.NO_LINKS}\n<code>/dl https://vm.tiktok.com/…</code>")
        return
    await handle_links(message, links, db)


@router.message(F.chat.type == ChatType.PRIVATE)
async def private_message(message: Message, bot: Bot, db: Database) -> None:
    _remember_owner(message, db)
    if not (links := links_from(message, bot.id)):
        await message.reply(texts.NO_LINKS)
        return
    await handle_links(message, links, db)


@router.message(F.chat.type.in_(GROUP_CHATS))
async def group_message(message: Message, bot: Bot, db: Database) -> None:
    """Only mentions of the bot and replies to it count in groups."""
    me = await bot.me()
    mentioned = mentions(message, me.username)
    if not mentioned and not (message.reply_to_message and is_from_bot(message.reply_to_message, me.id)):
        return
    if links := links_from(message, me.id):
        await handle_links(message, links, db)
    elif mentioned:
        await message.reply(texts.NO_LINKS)
