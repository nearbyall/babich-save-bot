import asyncio
import logging

import yt_dlp
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats

from . import config, housekeeping
from .db import Database
from .media import workspace
from .telegram.handlers import router
from .telegram.languages import LanguageMiddleware, dm_commands, group_commands

log = logging.getLogger("bot")

# Menus by the language of the user's Telegram app (None is any other one); the bot itself speaks Russian
# until the user picks English with /lang, which also sets their own menu
MENUS = {None: "ru", "ru": "ru", "en": "en"}


async def setup_commands(bot: Bot) -> None:
    """The bot's description and "about" text are managed by hand in @BotFather."""
    try:
        for language_code, lang in MENUS.items():
            await bot.set_my_commands(dm_commands(lang), scope=BotCommandScopeAllPrivateChats(),
                                      language_code=language_code)
            await bot.set_my_commands(group_commands(lang), scope=BotCommandScopeAllGroupChats(),
                                      language_code=language_code)
    except TelegramAPIError:
        log.warning("failed to set bot commands", exc_info=True)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    workspace.reset()

    bot = Bot(config.TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True))
    db = Database()
    dp = Dispatcher()
    dp["db"] = db
    dp.update.outer_middleware(LanguageMiddleware())
    dp.include_router(router)

    me = await bot.me()
    log.info("starting @%s, yt-dlp %s, inline mode %s, guest mode %s", me.username, yt_dlp.version.__version__,
             "on" if me.supports_inline_queries else "OFF", "on" if me.supports_guest_queries else "OFF")
    await setup_commands(bot)
    background = [
        asyncio.create_task(housekeeping.restart_on_ytdlp_update(dp)),
        asyncio.create_task(housekeeping.run(bot, db)),
    ]
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        for task in background:
            task.cancel()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
