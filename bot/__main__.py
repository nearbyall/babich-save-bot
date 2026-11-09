import asyncio
import logging

import yt_dlp
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats

from . import config, housekeeping
from .db import Database
from .media import workspace
from .telegram.handlers import router

log = logging.getLogger("bot")

# language_code: (description of /start in DMs, of /dl in groups); None is everyone else
COMMANDS = {
    None: ("How to use", "Download a video by link"),
    "ru": ("Как пользоваться", "Скачать видео по ссылке"),
}


async def setup_commands(bot: Bot) -> None:
    """The bot's description and "about" text are managed by hand in @BotFather."""
    try:
        for language, (start, dl) in COMMANDS.items():
            await bot.set_my_commands([BotCommand(command="start", description=start)],
                                      scope=BotCommandScopeAllPrivateChats(), language_code=language)
            await bot.set_my_commands([BotCommand(command="dl", description=dl)],
                                      scope=BotCommandScopeAllGroupChats(), language_code=language)
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
