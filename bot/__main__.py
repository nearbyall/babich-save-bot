import asyncio
import logging
import shutil

import aiohttp
import yt_dlp
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats

from . import config, delivery, handlers, housekeeping, stickers
from .db import Database

log = logging.getLogger("bot")

UPDATE_CHECK_INTERVAL = 6 * 3600


COMMANDS = {
    # language_code: (private chats, groups); None is the default for everyone else
    None: ("How to use", "Download a video by link"),
    "ru": ("Как пользоваться", "Скачать видео по ссылке"),
}


async def setup_commands(bot: Bot) -> None:
    # Description and "about" text are managed by hand in @BotFather; don't touch them
    try:
        for language, (start, dl) in COMMANDS.items():
            await bot.set_my_commands([BotCommand(command="start", description=start)],
                                      scope=BotCommandScopeAllPrivateChats(), language_code=language)
            await bot.set_my_commands([BotCommand(command="dl", description=dl)],
                                      scope=BotCommandScopeAllGroupChats(), language_code=language)
    except TelegramAPIError:
        log.warning("failed to set bot commands", exc_info=True)


async def restart_when_ytdlp_outdated(dp: Dispatcher) -> None:
    """Sites break old yt-dlp versions; exit when a new one is out so Docker restarts
    the container and the entrypoint installs it."""
    current = yt_dlp.version.__version__
    while True:
        await asyncio.sleep(UPDATE_CHECK_INTERVAL)
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                async with session.get("https://pypi.org/pypi/yt-dlp/json") as resp:
                    latest = (await resp.json())["info"]["version"]
        except Exception:
            log.warning("yt-dlp update check failed", exc_info=True)
            continue
        if latest == current:
            continue
        log.info("yt-dlp %s is available (running %s), restarting once idle", latest, current)
        while delivery.active_jobs:
            await asyncio.sleep(5)
        await dp.stop_polling()
        return


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    shutil.rmtree(config.TMP_DIR, ignore_errors=True)

    bot = Bot(
        config.TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )
    db = Database()
    dp = Dispatcher()
    dp["db"] = db
    dp.include_router(stickers.router)  # before handlers: they take any DM text as a link
    dp.include_router(handlers.router)

    me = await bot.me()
    log.info("starting @%s, yt-dlp %s, inline mode %s, guest mode %s", me.username, yt_dlp.version.__version__,
             "on" if me.supports_inline_queries else "OFF", "on" if me.supports_guest_queries else "OFF")
    await setup_commands(bot)
    background = [
        asyncio.create_task(restart_when_ytdlp_outdated(dp)),
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
