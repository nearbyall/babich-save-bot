from aiogram import Router
from aiogram.types import CallbackQuery

from ...i18n import t

router = Router(name="fallback")


@router.callback_query()
async def stale_button(callback: CallbackQuery) -> None:
    await callback.answer(t("button_expired"))
