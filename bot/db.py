"""file_id cache of everything already uploaded to Telegram, and the bot owner."""
import json
import sqlite3
import time
from dataclasses import asdict, astuple, dataclass
from pathlib import Path
from typing import Literal

from . import config


@dataclass
class CachedFile:
    file_id: str
    kind: Literal["video", "animation", "photo", "document"]  # Telegram may turn a silent clip into an animation
    uploader: str | None
    width: int | None
    height: int | None
    duration: int | None


@dataclass
class CachedPost:
    """A photo post, carousel or slideshow."""
    key: str  # canonical tt:/ig: key for deep links to the whole post
    items: list[CachedFile]
    audio: str | None
    uploader: str | None


Cached = CachedFile | CachedPost

_SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    key TEXT PRIMARY KEY,
    file_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    uploader TEXT,
    width INTEGER,
    height INTEGER,
    duration INTEGER,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS posts (
    key TEXT PRIMARY KEY,
    post_key TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class Database:
    def __init__(self, path: Path = config.DB_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.executescript(_SCHEMA)

    def get(self, key: str) -> Cached | None:
        row = self._db.execute(
            "SELECT file_id, kind, uploader, width, height, duration FROM videos WHERE key = ?", (key,)
        ).fetchone()
        if row:
            return CachedFile(*row)
        row = self._db.execute("SELECT data FROM posts WHERE key = ?", (key,)).fetchone()
        if row:
            data = json.loads(row[0])
            return CachedPost(data["key"], [CachedFile(**item) for item in data["items"]], data["audio"],
                              data["uploader"])
        return None

    def put(self, keys: list[str], cached: Cached) -> None:
        now = int(time.time())
        with self._db:
            if isinstance(cached, CachedPost):
                data = json.dumps(asdict(cached), ensure_ascii=False)
                self._db.executemany("INSERT OR REPLACE INTO posts VALUES (?, ?, ?, ?)",
                                     [(key, cached.key, data, now) for key in keys])
            else:
                self._db.executemany("INSERT OR REPLACE INTO videos VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                     [(key, *astuple(cached), now) for key in keys])

    def forget(self, cached: Cached) -> None:
        with self._db:
            if isinstance(cached, CachedPost):
                self._db.execute("DELETE FROM posts WHERE post_key = ?", (cached.key,))
            else:
                self._db.execute("DELETE FROM videos WHERE file_id = ?", (cached.file_id,))

    def prune(self, max_age_days: int, max_rows: int) -> int:
        """Drop old records; returns how many were removed."""
        cutoff = int(time.time()) - max_age_days * 86400
        removed = 0
        with self._db:
            for table in ("videos", "posts"):
                removed += self._db.execute(f"DELETE FROM {table} WHERE created_at < ?", (cutoff,)).rowcount
                removed += self._db.execute(
                    f"DELETE FROM {table} WHERE key NOT IN "
                    f"(SELECT key FROM {table} ORDER BY created_at DESC LIMIT ?)",
                    (max_rows,),
                ).rowcount
        if removed > 1000:
            self._db.execute("VACUUM")
        return removed

    def owner_id(self) -> int | None:
        if config.OWNER_ID:
            return config.OWNER_ID
        row = self._db.execute("SELECT value FROM meta WHERE key = 'owner_id'").fetchone()
        return int(row[0]) if row else None

    def remember_owner(self, user_id: int) -> bool:
        """The first user to write the bot becomes its owner; returns True if that's this one."""
        with self._db:
            cur = self._db.execute("INSERT OR IGNORE INTO meta VALUES ('owner_id', ?)", (str(user_id),))
        return cur.rowcount > 0
