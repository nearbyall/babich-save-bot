"""file_id cache of everything already uploaded to Telegram, the bot owner, whom reports came from, the
languages users picked and the numbers for /stats."""
import datetime
import json
import sqlite3
import time
from dataclasses import asdict, astuple, dataclass, field
from pathlib import Path
from typing import Literal

from . import config, i18n
from .i18n import Lang


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


@dataclass
class Stats:
    since: str | None  # the first day counted
    users: int
    new: int  # today
    returning: int  # users seen on more than one day
    active: tuple[int, int, int]  # users seen today, in 7 and in 30 days
    places: dict[str, int] = field(default_factory=dict)  # users in 7 days by where they used the bot
    sources: dict[str, int] = field(default_factory=dict)  # new users in 30 days by where they came from
    groups: int = 0
    blocked: int = 0
    events: dict[str, int] = field(default_factory=dict)  # in 7 days


def _utc_today() -> datetime.date:
    return datetime.datetime.now(datetime.UTC).date()


def day(days_ago: int = 0) -> str:
    """Stats count UTC days."""
    return (_utc_today() - datetime.timedelta(days=days_ago)).isoformat()

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
CREATE TABLE IF NOT EXISTS reports (message_id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, lang TEXT NOT NULL);
-- Stats: who used the bot on which days and where, never what they sent
CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY,
    first_day TEXT NOT NULL,
    last_day TEXT NOT NULL,
    days INTEGER NOT NULL,
    source TEXT NOT NULL,
    blocked INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS seen (
    day TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    place TEXT NOT NULL,
    PRIMARY KEY (day, user_id, place)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS groups (id INTEGER PRIMARY KEY, present INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS events (
    day TEXT NOT NULL,
    name TEXT NOT NULL,
    count INTEGER NOT NULL,
    PRIMARY KEY (day, name)
) WITHOUT ROWID;
"""


class Database:
    def __init__(self, path: Path = config.DB_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.executescript(_SCHEMA)
        # Marks already written, so that every update doesn't write to the disk
        self._seen_day, self._seen = "", set[tuple[int, str]]()
        self._groups = {row[0] for row in self._db.execute("SELECT id FROM groups WHERE present")}

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

    def remember_report(self, message_id: int, user_id: int) -> None:
        """The report header `message_id` in the owner's chat came from `user_id`."""
        with self._db:
            self._db.execute("INSERT OR REPLACE INTO reports VALUES (?, ?)", (message_id, user_id))

    def reporter(self, message_id: int) -> int | None:
        row = self._db.execute("SELECT user_id FROM reports WHERE message_id = ?", (message_id,)).fetchone()
        return row[0] if row else None

    def lang(self, user_id: int) -> Lang:
        row = self._db.execute("SELECT lang FROM users WHERE id = ?", (user_id,)).fetchone()
        return row[0] if row and row[0] in i18n.LANGS else i18n.DEFAULT

    def set_lang(self, user_id: int, lang: Lang) -> None:
        with self._db:
            self._db.execute("INSERT OR REPLACE INTO users VALUES (?, ?)", (user_id, lang))

    def mark_seen(self, user_id: int, place: str, source: str) -> None:
        """The user used the bot today in `place`; `source` is where they came from, kept if they're new."""
        today = day()
        if self._seen_day != today:
            self._seen_day, self._seen = today, set()
        if (user_id, place) in self._seen:
            return
        with self._db:
            if self._db.execute("INSERT OR IGNORE INTO seen VALUES (?, ?, ?)", (today, user_id, place)).rowcount:
                self._db.execute(
                    "INSERT INTO people (id, first_day, last_day, days, source) VALUES (?, ?, ?, 1, ?) "
                    "ON CONFLICT (id) DO UPDATE SET days = days + (last_day != excluded.last_day), "
                    "last_day = excluded.last_day",
                    (user_id, today, today, source))
        self._seen.add((user_id, place))

    def set_blocked(self, user_id: int, blocked: bool) -> None:
        with self._db:
            self._db.execute("UPDATE people SET blocked = ? WHERE id = ?", (int(blocked), user_id))

    def mark_group(self, chat_id: int, present: bool = True) -> None:
        if present and chat_id in self._groups:
            return
        with self._db:
            self._db.execute("INSERT OR REPLACE INTO groups VALUES (?, ?)", (chat_id, int(present)))
        if present:
            self._groups.add(chat_id)
        else:
            self._groups.discard(chat_id)

    def count(self, event: str, n: int = 1) -> None:
        with self._db:
            self._db.execute("INSERT INTO events VALUES (?, ?, ?) "
                             "ON CONFLICT (day, name) DO UPDATE SET count = count + excluded.count",
                             (day(), event, n))

    def forget_old_visits(self, keep_days: int) -> int:
        """Daily visits are only needed for the 30-day numbers; people keep their totals."""
        with self._db:
            return self._db.execute("DELETE FROM seen WHERE day < ?", (day(keep_days),)).rowcount

    def stats(self) -> Stats:
        def one(sql: str, *args: object) -> int:
            return self._db.execute(sql, args).fetchone()[0] or 0

        def by(sql: str, *args: object) -> dict[str, int]:
            return dict(self._db.execute(sql + " ORDER BY 2 DESC, 1", args).fetchall())

        today, week, month = day(), day(6), day(29)
        visits = "SELECT count(DISTINCT user_id) FROM seen WHERE day >= ?"
        return Stats(
            since=self._db.execute("SELECT min(first_day) FROM people").fetchone()[0],
            users=one("SELECT count(*) FROM people"),
            new=one("SELECT count(*) FROM people WHERE first_day = ?", today),
            returning=one("SELECT count(*) FROM people WHERE days > 1"),
            active=(one(visits, today), one(visits, week), one(visits, month)),
            places=by("SELECT place, count(DISTINCT user_id) FROM seen WHERE day >= ? GROUP BY place", week),
            sources=by("SELECT source, count(*) FROM people WHERE first_day >= ? GROUP BY source", month),
            groups=one("SELECT count(*) FROM groups WHERE present"),
            blocked=one("SELECT count(*) FROM people WHERE blocked"),
            events=by("SELECT name, sum(count) FROM events WHERE day >= ? GROUP BY name", week),
        )
