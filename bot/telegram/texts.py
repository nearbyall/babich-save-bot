"""Texts put together from data; the words come from i18n."""
import html

from ..db import CachedPost
from ..i18n import t
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
