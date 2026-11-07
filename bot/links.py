import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from aiogram.types import Message

_LINK_RE = re.compile(
    r"(?:https?://)?(?:[\w-]+\.)*(?:tiktok\.com|instagram\.com|youtube\.com|youtu\.be)"
    r"(?:/[^\s<>\"'«»]*)?",
    re.IGNORECASE,
)
_ID = r"[\w-]+"


@dataclass(frozen=True)
class Link:
    url: str  # what gets passed to yt-dlp
    platform: str  # human-readable name
    key: str  # stable cache key, identical for different spellings of one video


def _parse(raw: str) -> Link | None:
    raw = raw.rstrip(".,!?;:)]}")
    if not re.match(r"https?://", raw, re.IGNORECASE):
        raw = "https://" + raw
    parts = urlsplit(raw)
    host = (parts.hostname or "").lower()
    path = parts.path

    if host == "tiktok.com" or host.endswith(".tiktok.com"):
        # Slideshows live at /photo/ID, but yt-dlp and the web page only know /video/ID
        if m := re.search(r"/(@[^/]+)/(?:video|photo)/(\d+)", path):
            return Link(f"https://www.tiktok.com/{m[1]}/video/{m[2]}", "TikTok", f"tt:{m[2]}")
        if m := re.search(r"/(?:video|photo)/(\d+)", path):
            return Link(f"https://www.tiktok.com/@/video/{m[1]}", "TikTok", f"tt:{m[1]}")
        # Short share links: vm.tiktok.com/XXXX, vt.tiktok.com/XXXX, tiktok.com/t/XXXX
        if host.startswith(("vm.", "vt.")) and (m := re.fullmatch(rf"/({_ID})/?", path)):
            return Link(f"https://{host}/{m[1]}/", "TikTok", f"tt-short:{m[1]}")
        if m := re.fullmatch(rf"/t/({_ID})/?", path):
            return Link(f"https://www.tiktok.com/t/{m[1]}/", "TikTok", f"tt-short:{m[1]}")
        return None

    if host == "instagram.com" or host.endswith(".instagram.com"):
        if m := re.match(rf"/share/(?:(?:reels?|p)/)?({_ID})", path):
            return Link(f"https://www.instagram.com{m[0]}/", "Instagram", f"ig-share:{m[1]}")
        if m := re.search(rf"/(reels?|p|tv)/({_ID})", path):
            kind = "reel" if m[1].startswith("reel") else m[1]
            return Link(f"https://www.instagram.com/{kind}/{m[2]}/", "Instagram", f"ig:{m[2]}")
        return None

    if host == "youtu.be":
        video_id = path.strip("/").split("/")[0]
    elif host == "youtube.com" or host.endswith(".youtube.com"):
        if m := re.match(rf"/(?:shorts|embed|live|v)/({_ID})", path):
            video_id = m[1]
        elif path.rstrip("/") == "/watch":
            video_id = parse_qs(parts.query).get("v", [""])[0]
        else:
            return None
    else:
        return None
    if not re.fullmatch(r"[\w-]{11}", video_id):
        return None
    return Link(f"https://www.youtube.com/watch?v={video_id}", "YouTube", f"yt:{video_id}")


def find_links(text: str | None) -> list[Link]:
    seen: set[str] = set()
    links = []
    for match in _LINK_RE.finditer(text or ""):
        link = _parse(match.group(0))
        if link and link.key not in seen:
            seen.add(link.key)
            links.append(link)
    return links


def canonical_key(keys: list[str]) -> str | None:
    """The tt:/ig: key among a media's cache keys (short links resolve to it)."""
    return next((k for k in keys if k.startswith(("tt:", "ig:"))), None)


def to_payload(key: str) -> str | None:
    """Deep link payload (t.me/bot?start=...) for a post: letters, digits, _ and - only."""
    prefix, _, ident = key.partition(":")
    if prefix in ("tt", "ig") and re.fullmatch(r"[\w-]{1,60}", ident):
        return f"{prefix}_{ident}"
    return None


def from_payload(payload: str) -> Link | None:
    prefix, _, ident = payload.partition("_")
    if prefix == "tt" and ident.isdigit():
        return _parse(f"https://www.tiktok.com/@/video/{ident}")
    if prefix == "ig" and re.fullmatch(_ID, ident):
        return _parse(f"https://www.instagram.com/p/{ident}/")
    return None


def message_text(message: Message | None) -> str:
    """Visible text plus URLs hidden behind text links."""
    if message is None:
        return ""
    text = message.text or message.caption or ""
    hidden = [e.url for e in (message.entities or message.caption_entities or []) if e.url]
    return "\n".join([text, *hidden])


def is_from_bot(message: Message, bot_id: int) -> bool:
    return bool((message.from_user and message.from_user.id == bot_id)
                or (message.via_bot and message.via_bot.id == bot_id))


def links_from(message: Message, bot_id: int) -> list[Link]:
    """Links in the message itself, or else in the message it replies to.

    The bot's own messages are skipped: their captions link to the source, and a
    reply like "thanks" to a downloaded video must not trigger the same download."""
    if links := find_links(message_text(message)):
        return links
    reply = message.reply_to_message
    if reply and not is_from_bot(reply, bot_id):
        return find_links(message_text(reply))
    return []
