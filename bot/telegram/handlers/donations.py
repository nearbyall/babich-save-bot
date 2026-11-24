"""/donate in DMs: support the bot with Telegram Stars."""
import html
import logging

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery

from ...db import Database
from ...i18n import t
from ..keyboards import DonateButton, donate_keyboard
from ..texts import who

log = logging.getLogger(__name__)
router = Router(name="donations")

STARS = "XTR"  # the currency of Telegram Stars, paid without a payment provider
PAYLOAD = "donate"
MIN_STARS, MAX_STARS = 1, 10_000


def valid(stars: int) -> bool:
    return MIN_STARS <= stars <= MAX_STARS


def amount(args: str | None) -> int | None:
    """The number of Stars in `/donate 300`, if there is one Telegram takes."""
    args = (args or "").strip()
    return int(args) if args.isdecimal() and valid(int(args)) else None


@router.message(F.chat.type == ChatType.PRIVATE, Command("donate"))
async def donate_command(message: Message, bot: Bot, command: CommandObject) -> None:
    """/donate shows the amounts; /donate 300 asks for that many Stars at once."""
    if stars := amount(command.args):
        await _invoice(bot, message.chat.id, stars)
    else:
        await message.answer(t("donate_choose", max=MAX_STARS), reply_markup=donate_keyboard())


@router.callback_query(DonateButton.filter())
async def donate_pressed(callback: CallbackQuery, callback_data: DonateButton, bot: Bot) -> None:
    await callback.answer()
    if valid(callback_data.stars):
        await _invoice(bot, callback.from_user.id, callback_data.stars)


@router.pre_checkout_query()
async def checkout(query: PreCheckoutQuery) -> None:
    """Telegram asks before charging; anything but a donation of ours is turned down."""
    if query.currency == STARS and query.invoice_payload == PAYLOAD and valid(query.total_amount):
        await query.answer(ok=True)
    else:
        log.warning("unexpected payment from %s turned down: %s %s %r", query.from_user.id, query.total_amount,
                    query.currency, query.invoice_payload)
        await query.answer(ok=False, error_message=t("donate_failed"))


@router.message(F.successful_payment.invoice_payload == PAYLOAD)
async def donated(message: Message, bot: Bot, db: Database) -> None:
    payment = message.successful_payment
    log.info("donation of %s stars from %s", payment.total_amount, message.from_user.id)
    db.count("donation")
    db.count("stars", payment.total_amount)
    await message.answer(t("donate_thanks", stars=payment.total_amount))
    if not (owner := db.owner_id()):
        return
    try:
        await bot.send_message(owner, t("donation", db.lang(owner), stars=payment.total_amount,
                                        who=who(message.from_user),
                                        charge=html.escape(payment.telegram_payment_charge_id)))
    except TelegramAPIError:
        log.warning("failed to tell the owner about a donation from %s", message.from_user.id, exc_info=True)


async def _invoice(bot: Bot, chat_id: int, stars: int) -> None:
    await bot.send_invoice(chat_id, title=t("donate_title"), description=t("donate_description"), payload=PAYLOAD,
                           currency=STARS, prices=[LabeledPrice(label=t("donate_label"), amount=stars)])
