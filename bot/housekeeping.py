import asyncio
import logging
import shutil
import time

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from . import config, downloader
from .db import Database

log = logging.getLogger(__name__)


def _remove_old_files(directory, max_age_days: int) -> int:
    if not directory.is_dir():
        return 0
    cutoff = time.time() - max_age_days * 86400
    removed = 0
    for f in directory.rglob("*"):
        try:
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink()
                removed += 1
        except OSError:
            pass
    return removed


def sweep(db: Database) -> None:
    """Drop leftovers: crashed downloads, old cache records, stale yt-dlp cache."""
    freed = downloader.cleanup_stale()
    pruned = db.prune(config.CACHE_TTL_DAYS, config.CACHE_MAX_ROWS)
    old_files = _remove_old_files(config.YTDLP_CACHE_DIR, config.YTDLP_CACHE_TTL_DAYS)
    if downloader.free_disk() < config.MIN_FREE_DISK:
        freed += downloader.cleanup_stale(max_age=0)
        shutil.rmtree(config.YTDLP_CACHE_DIR, ignore_errors=True)
    if freed or pruned or old_files:
        log.info("housekeeping: freed %d KB of temp files, pruned %d cache records, %d yt-dlp cache files",
                 freed // 1024, pruned, old_files)


async def _notify_owner(bot: Bot, db: Database, text: str) -> None:
    if owner := db.owner_id():
        try:
            await bot.send_message(owner, text)
        except TelegramAPIError:
            log.warning("failed to notify owner", exc_info=True)


async def run(bot: Bot, db: Database) -> None:
    disk_low = False
    while True:
        try:
            sweep(db)
            free_mb = downloader.free_disk() // config.MB
            if (free_mb * config.MB < config.MIN_FREE_DISK) != disk_low:
                disk_low = not disk_low
                if disk_low:
                    log.warning("disk almost full: %d MB free", free_mb)
                    await _notify_owner(bot, db, f"⚠️ На сервере осталось {free_mb} МБ — загрузки приостановлены, "
                                                 "пока место не освободится.")
                else:
                    await _notify_owner(bot, db, f"✅ Место на диске освободилось ({free_mb} МБ), загрузки снова работают.")
        except Exception:
            log.exception("housekeeping failed")
        await asyncio.sleep(config.HOUSEKEEPING_INTERVAL)
