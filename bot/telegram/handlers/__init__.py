from aiogram import Router

from . import chats, fallback, inline, reports, rounds, sounds, stickers

router = Router(name="handlers")
# Reports and stickers go before chats, which takes any DM text as a link and any video as one to work on;
# fallback catches buttons nobody else knows
router.include_routers(reports.router, stickers.router, sounds.router, rounds.router, chats.router,
                       inline.router, fallback.router)
