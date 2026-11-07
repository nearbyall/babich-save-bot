"""Temporary work dirs: one per download, plus named ones reused between sticker cuts."""
import contextlib
import logging
import shutil
import time
import uuid
from pathlib import Path

from .. import config
from ..errors import UserError

log = logging.getLogger(__name__)

_in_use: set[Path] = set()


def create() -> Path:
    workdir = config.TMP_DIR / uuid.uuid4().hex
    workdir.mkdir(parents=True)
    _in_use.add(workdir)
    return workdir


def remove(workdir: Path) -> None:
    shutil.rmtree(workdir, ignore_errors=True)
    _in_use.discard(workdir)


@contextlib.contextmanager
def reusable(name: str):
    """A named work dir that outlives the job; cleanup_stale removes it once it's unused for a while."""
    workdir = config.TMP_DIR / name
    workdir.mkdir(parents=True, exist_ok=True)
    _in_use.add(workdir)
    try:
        yield workdir
    finally:
        _in_use.discard(workdir)


def free_disk() -> int:
    return shutil.disk_usage(config.TMP_DIR.parent).free


def ensure_free_space() -> None:
    if free_disk() >= config.MIN_FREE_DISK:
        return
    cleanup_stale(max_age=0)
    if free_disk() < config.MIN_FREE_DISK:
        log.warning("only %d MB free on disk, refusing new jobs", free_disk() // config.MB)
        raise UserError("На сервере заканчивается место, загрузки временно приостановлены.")


def cleanup_stale(max_age: float = config.STALE_TMP_AGE) -> int:
    """Remove work dirs left by crashes or unused for max_age seconds; returns bytes freed."""
    if not config.TMP_DIR.is_dir():
        return 0
    freed = 0
    now = time.time()
    for workdir in config.TMP_DIR.iterdir():
        if workdir in _in_use:
            continue
        try:
            if now - workdir.stat().st_mtime < max_age:
                continue
            freed += sum(f.stat().st_size for f in workdir.rglob("*") if f.is_file())
        except OSError:
            pass
        if workdir.is_dir():
            shutil.rmtree(workdir, ignore_errors=True)
        else:
            workdir.unlink(missing_ok=True)
    return freed
