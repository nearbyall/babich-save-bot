from aiogram import Router

from . import chats, fallback, inline, sounds, stickers

router = Router(name="handlers")
# Stickers go before chats, which takes any DM text as a link; fallback catches buttons nobody else knows
router.include_routers(stickers.router, sounds.router, chats.router, inline.router, fallback.router)
