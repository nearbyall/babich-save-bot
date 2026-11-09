import html

from ..db import CachedPost
from ..links import Link
from ..media.shazam import Track

NO_LINKS = (
    "Send me a TikTok, Instagram or YouTube Shorts link.\n"
    "Пришли ссылку на TikTok, Instagram или YouTube Shorts."
)
FAILED = "Не удалось скачать видео. Попробуй ещё раз чуть позже."
STICKER_BUSY = "Подожди, ещё делаю предыдущий стикер."
NO_TRACK = "🤷 Не узнал трек — похоже, это оригинальный звук или речь."


def help_text(username: str) -> str:
    """Every feature of the bot, in English and Russian. Update it with each new feature."""
    return (
        "🇬🇧 <b>Videos and photos from TikTok, Instagram and YouTube Shorts</b>\n"
        "📥 Send me a link — I'll send back the video, photo post, carousel or slideshow with its sound.\n"
        f"💬 Any chat: type <code>@{username} link</code> and tap the result, or just send it. "
        "Photo posts show the first photo and a button for the whole post.\n"
        "👥 Groups I'm in: <code>/dl link</code>, or reply <code>/dl</code> to a message with a link.\n"
        "🎵 Under a video in our chat: «🎵 Шазам» finds out what track is playing, "
        "«🎧 Аудио» sends its sound as an audio file.\n"
        "🎭 Video stickers: tap «🎭 Стикер» under a video, or send me any video, GIF or round video. "
        "Buttons under the sticker move it, change the speed (×0.25–×8) and the shape (1:1, 16:9, 9:16, circle), "
        "and add it to your own sticker pack. Reply to the video with <code>0:12</code> or "
        "<code>0:12-0:20</code> to cut from that moment.\n\n"
        "🇷🇺 <b>Видео и фото из TikTok, Instagram и YouTube Shorts</b>\n"
        "📥 Пришли ссылку — пришлю видео, фото-пост, карусель или слайдшоу со звуком.\n"
        f"💬 Любой чат: набери <code>@{username} ссылка</code> и нажми на результат или просто отправь. "
        "У фото-постов — первое фото и кнопка «Весь пост».\n"
        "👥 Группы, где я есть: <code>/dl ссылка</code> или ответь <code>/dl</code> на сообщение со ссылкой.\n"
        "🎵 Под видео в личке: «🎵 Шазам» — узнать, что за трек, «🎧 Аудио» — звук отдельным файлом.\n"
        "🎭 Видеостикеры: «🎭 Стикер» под видео или пришли любое видео, GIF или кружок. "
        "Кнопки под стикером двигают его, меняют скорость (×0.25–×8) и форму (1:1, 16:9, 9:16, круг) "
        "и добавляют в твой стикерпак. Ответь на видео <code>0:12</code> или <code>0:12-0:20</code> — "
        "вырежу с этого места."
    )


def caption(link: Link, uploader: str | None) -> str:
    text = f'<a href="{html.escape(link.url)}">{link.platform}</a>'
    if uploader:
        text += f" · {html.escape(uploader[:100])}"
    return text


def loading(link: Link) -> str:
    return f"⏳ Скачиваю из {link.platform}…"


def post_summary(post: CachedPost) -> str:
    photos = sum(item.kind == "photo" for item in post.items)
    parts = [f"{photos} фото"] if photos else []
    if videos := len(post.items) - photos:
        parts.append(f"{videos} видео")
    return " и ".join(parts) + (" + звук" if post.audio else "")


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
    return f"Звук из {platform or 'видео'}", uploader or None
