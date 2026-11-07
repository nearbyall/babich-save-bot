from aiogram import Router
from aiogram.types import CallbackQuery

router = Router(name="fallback")


@router.callback_query()
async def stale_button(callback: CallbackQuery) -> None:
    await callback.answer("Кнопка устарела — пришли ссылку или видео заново.")
