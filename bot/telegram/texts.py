"""Texts put together from data; the words come from i18n."""
import datetime
import html

from aiogram.types import User

from ..db import CachedPost, Stats
from ..i18n import TEXTS, t
from ..links import Link
from ..media.shazam import Track


def help_text(username: str) -> str:
    """Every feature of the bot (i18n's HELP_RU and HELP_EN). Update it with each new feature."""
    return t("help", username=username)


def caption(link: Link, uploader: str | None) -> str:
    text = f'<a href="{html.escape(link.url)}">{link.platform}</a>'
    if uploader:
        text += f" · {html.escape(uploader[:100])}"
    return text


def loading(link: Link) -> str:
    return t("loading", platform=link.platform)


def post_summary(post: CachedPost) -> str:
    photos = sum(item.kind == "photo" for item in post.items)
    parts = [t("photo" if photos == 1 else "photos", n=photos)] if photos else []
    if videos := len(post.items) - photos:
        parts.append(t("video" if videos == 1 else "videos", n=videos))
    return t("and").join(parts) + (t("with_sound") if post.audio else "")


def who(user: User) -> str:
    """The user as the owner sees them: a link to the profile, @username and the language of their app."""
    parts = [f'<a href="tg://user?id={user.id}">{html.escape(user.full_name)}</a>']
    if user.username:
        parts.append(f"@{html.escape(user.username)}")
    if user.language_code:
        parts.append(html.escape(user.language_code))
    return " · ".join(parts)


def track_caption(track: Track) -> str:
    lines = [f"🎵 <b>{html.escape(track.title)}</b>", f"👤 {html.escape(track.artist)}"]
    if details := " · ".join(html.escape(part) for part in (track.album, track.released) if part):
        lines.append(f"💿 {details}")
    return "\n".join(lines)


def sound_names(video_caption: str | None, track: Track | None) -> tuple[str, str | None]:
    """Title and performer for the sound of a video sent with caption()."""
    if track:
        return track.title, track.artist
    platform, _, uploader = (video_caption or "").partition(" · ")
    return (t("sound_from", source=platform) if platform else t("sound_from_video")), uploader or None


FEATURES = ("shazam", "audio", "round", "sticker", "pack")


def stats(s: Stats) -> str:
    """/stats for the owner."""
    if not s.since:
        return t("stats_empty")
    events = s.events
    platforms = {name.removeprefix("link:"): n for name, n in events.items() if name.startswith("link:")}
    links = sum(platforms.values())
    fails = sum(n for name, n in events.items() if name.startswith("fail:"))
    lines = [
        t("stats_title", since=datetime.date.fromisoformat(s.since).strftime("%d.%m.%Y")),
        "",
        t("stats_users", users=s.users, new=s.new, returning=s.returning),
        t("stats_active", today=s.active[0], week=s.active[1], month=s.active[2]),
        t("stats_groups", groups=s.groups, blocked=s.blocked),
        "",
        f"<b>{t('stats_week')}</b>",
        t("stats_places", places=_counts(s.places)),
        t("stats_links", links=links, fails=f"{fails} ({fails * 100 // links}%)" if links else fails),
    ]
    if platforms:
        lines.append(f"      {_counts(platforms)}")
    lines += [
        t("stats_features", **{name: events.get(name, 0) for name in FEATURES}),
        t("stats_support", reports=events.get("report", 0), donations=events.get("donation", 0),
          stars=events.get("stars", 0)),
        "",
        f"<b>{t('stats_sources')}</b>",
        _counts(s.sources),
    ]
    return "\n".join(lines)


def _counts(counts: dict[str, int]) -> str:
    """Places and sources by name, ads by their /start parameter."""
    def name(key: str) -> str:
        return t(f"place_{key}") if f"place_{key}" in TEXTS else html.escape(key)
    return " · ".join(f"{name(key)} {n}" for key, n in counts.items()) or "—"
