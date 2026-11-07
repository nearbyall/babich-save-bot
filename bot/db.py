import json
import sqlite3
import time
from dataclasses import asdict, dataclass

from . import config


@dataclass
class CachedVideo:
    file_id: str
    kind: str  # "video", "animation" (Telegram turns silent clips into these), "photo" or "document"
    uploader: str | None
    width: int | None
    height: int | None
    duration: int | None


@dataclass
class CachedPost:
    """Photo post, carousel or slideshow already uploaded to Telegram."""
    key: str  # canonical tt:/ig: key, used in deep links to the full post
    items: list[CachedVideo]
    audio: str | None  # slideshow soundtrack
    uploader: str | None

    @property
    def summary(self) -> str:
        photos = sum(item.kind == "photo" for item in self.items)
        parts = [f"{photos} фото"] if photos else []
        if videos := len(self.items) - photos:
            parts.append(f"{videos} видео")
        return " и ".join(parts) + (" + звук" if self.audio else "")


class Database:
    def __init__(self) -> None:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(config.DB_PATH)
        self._db.executescript(
            """
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
        )

    def get_video(self, key: str) -> CachedVideo | None:
        row = self._db.execute(
            "SELECT file_id, kind, uploader, width, height, duration FROM videos WHERE key = ?", (key,)
        ).fetchone()
        return CachedVideo(*row) if row else None

    def put_video(self, keys: list[str], video: CachedVideo) -> None:
        now = int(time.time())
        with self._db:
            self._db.executemany(
                "INSERT OR REPLACE INTO videos VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [(k, video.file_id, video.kind, video.uploader, video.width, video.height, video.duration, now)
                 for k in keys],
            )

    def forget_video(self, file_id: str) -> None:
        with self._db:
            self._db.execute("DELETE FROM videos WHERE file_id = ?", (file_id,))

    def get_post(self, key: str) -> CachedPost | None:
        row = self._db.execute("SELECT data FROM posts WHERE key = ?", (key,)).fetchone()
        if not row:
            return None
        data = json.loads(row[0])
        return CachedPost(data["key"], [CachedVideo(**item) for item in data["items"]], data["audio"], data["uploader"])

    def put_post(self, keys: list[str], post: CachedPost) -> None:
        data = json.dumps(asdict(post), ensure_ascii=False)
        now = int(time.time())
        with self._db:
            self._db.executemany("INSERT OR REPLACE INTO posts VALUES (?, ?, ?, ?)",
                                 [(k, post.key, data, now) for k in keys])

    def forget_post(self, post: CachedPost) -> None:
        with self._db:
            self._db.execute("DELETE FROM posts WHERE post_key = ?", (post.key,))

    def get_media(self, key: str) -> CachedVideo | CachedPost | None:
        return self.get_video(key) or self.get_post(key)

    def put_media(self, keys: list[str], media: CachedVideo | CachedPost) -> None:
        if isinstance(media, CachedPost):
            self.put_post(keys, media)
        else:
            self.put_video(keys, media)

    def forget_media(self, media: CachedVideo | CachedPost) -> None:
        if isinstance(media, CachedPost):
            self.forget_post(media)
        else:
            self.forget_video(media.file_id)

    def prune(self, max_age_days: int, max_rows: int) -> int:
        """Drop old file_id records; returns how many were removed."""
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
        """The first person to talk to the bot becomes the fallback upload target."""
        with self._db:
            cur = self._db.execute("INSERT OR IGNORE INTO meta VALUES ('owner_id', ?)", (str(user_id),))
        return cur.rowcount > 0
