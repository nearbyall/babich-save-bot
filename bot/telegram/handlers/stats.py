"""/stats for the owner; which groups the bot is in and who blocked it."""
from aiogram import F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.filters import Command
from aiogram.types import ChatMemberUpdated, Message

from ...db import Database
from .. import texts
from ..messages import GROUP_CHATS

router = Router(name="stats")

PRESENT = {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}


async def from_owner(message: Message, db: Database) -> bool:
    """Async: aiogram runs sync filters in a thread, and the database can't be used from one."""
    return message.from_user is not None and message.from_user.id == db.owner_id()


@router.message(F.chat.type == ChatType.PRIVATE, Command("stats"), from_owner)
async def stats_command(message: Message, db: Database) -> None:
    await message.answer(texts.stats(db.stats()))


@router.my_chat_member()
async def membership_changed(update: ChatMemberUpdated, db: Database) -> None:
    """Telegram tells the bot when it's added to a group or removed, and when a user blocks or unblocks it."""
    member = update.new_chat_member
    if update.chat.type == ChatType.PRIVATE:
        db.set_blocked(update.chat.id, member.status == ChatMemberStatus.KICKED)
    elif update.chat.type in GROUP_CHATS:
        db.mark_group(update.chat.id, present=member.status in PRESENT or getattr(member, "is_member", False))


@router.message(F.migrate_to_chat_id)
async def group_upgraded(message: Message, db: Database) -> None:
    """A group that became a supergroup goes on under a new id."""
    db.mark_group(message.chat.id, present=False)
