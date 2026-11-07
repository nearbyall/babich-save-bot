import re
from dataclasses import dataclass
from urllib.parse import SplitResult, parse_qs, urlsplit

_LINK_RE = re.compile(
    r"(?:https?://)?(?:[\w-]+\.)*(?:tiktok\.com|instagram\.com|youtube\.com|youtu\.be)"
    r"(?:/[^\s<>\"'«»]*)?",
    re.IGNORECASE,
)
_ID = r"[\w-]+"
# Share and short links redirect to a post; the key prefix of what they expand to
_EXPANDS_TO = {"ig-share:": "ig:", "tt-short:": "tt:"}


@dataclass(frozen=True)
class Link:
    url: str  # what yt-dlp gets
    platform: str  # human-readable name
    key: str  # cache key, the same for every spelling of one post

    @property
    def expands_to(self) -> str | None:
        """Key prefix of the post a share or short link redirects to; None for direct links."""
        return next((full for short, full in _EXPANDS_TO.items() if self.key.startswith(short)), None)


def _on(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def _tiktok(host: str, path: str) -> Link | None:
    # Slideshows live at /photo/ID, but yt-dlp and the web page only know /video/ID
    if m := re.search(r"/(@[^/]+)/(?:video|photo)/(\d+)", path):
        return Link(f"https://www.tiktok.com/{m[1]}/video/{m[2]}", "TikTok", f"tt:{m[2]}")
    if m := re.search(r"/(?:video|photo)/(\d+)", path):
        return Link(f"https://www.tiktok.com/@/video/{m[1]}", "TikTok", f"tt:{m[1]}")
    if host.startswith(("vm.", "vt.")) and (m := re.fullmatch(rf"/({_ID})/?", path)):
        return Link(f"https://{host}/{m[1]}/", "TikTok", f"tt-short:{m[1]}")
    if m := re.fullmatch(rf"/t/({_ID})/?", path):
        return Link(f"https://www.tiktok.com/t/{m[1]}/", "TikTok", f"tt-short:{m[1]}")
    return None


def _instagram(path: str) -> Link | None:
    if m := re.match(rf"/share/(?:(?:reels?|p)/)?({_ID})", path):
        return Link(f"https://www.instagram.com{m[0]}/", "Instagram", f"ig-share:{m[1]}")
    if m := re.search(rf"/(reels?|p|tv)/({_ID})", path):
        kind = "reel" if m[1].startswith("reel") else m[1]
        return Link(f"https://www.instagram.com/{kind}/{m[2]}/", "Instagram", f"ig:{m[2]}")
    return None


def _youtube(host: str, parts: SplitResult) -> Link | None:
    if host == "youtu.be":
        video_id = parts.path.strip("/").split("/")[0]
    elif m := re.match(rf"/(?:shorts|embed|live|v)/({_ID})", parts.path):
        video_id = m[1]
    elif parts.path.rstrip("/") == "/watch":
        video_id = parse_qs(parts.query).get("v", [""])[0]
    else:
        return None
    if not re.fullmatch(r"[\w-]{11}", video_id):
        return None
    return Link(f"https://www.youtube.com/watch?v={video_id}", "YouTube", f"yt:{video_id}")


def parse(raw: str) -> Link | None:
    raw = raw.rstrip(".,!?;:)]}")
    if not re.match(r"https?://", raw, re.IGNORECASE):
        raw = "https://" + raw
    parts = urlsplit(raw)
    host = (parts.hostname or "").lower()
    if _on(host, "tiktok.com"):
        return _tiktok(host, parts.path)
    if _on(host, "instagram.com"):
        return _instagram(parts.path)
    if host == "youtu.be" or _on(host, "youtube.com"):
        return _youtube(host, parts)
    return None


def find_links(text: str | None) -> list[Link]:
    links: dict[str, Link] = {}
    for match in _LINK_RE.finditer(text or ""):
        if (link := parse(match.group(0))) and link.key not in links:
            links[link.key] = link
    return list(links.values())


def canonical_key(keys: list[str]) -> str | None:
    """The tt:/ig: key among the cache keys of a post (short links resolve to it)."""
    return next((k for k in keys if k.startswith(("tt:", "ig:"))), None)


def to_payload(key: str) -> str | None:
    """Deep link payload (t.me/bot?start=...) for a post: only letters, digits, _ and - are allowed."""
    prefix, _, ident = key.partition(":")
    if prefix in ("tt", "ig") and re.fullmatch(r"[\w-]{1,60}", ident):
        return f"{prefix}_{ident}"
    return None


def from_payload(payload: str) -> Link | None:
    prefix, _, ident = payload.partition("_")
    if prefix == "tt" and ident.isdigit():
        return parse(f"https://www.tiktok.com/@/video/{ident}")
    if prefix == "ig" and re.fullmatch(_ID, ident):
        return parse(f"https://www.instagram.com/p/{ident}/")
    return None
