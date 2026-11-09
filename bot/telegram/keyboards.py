from dataclasses import replace
from urllib.parse import quote

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ..db import CachedPost
from ..links import to_payload
from ..media.shazam import Track
from ..media.sticker import LENGTH, MAX_SPEED, MIN_SPEED, Cut, Shape, format_time
from .texts import post_summary


class LoadButton(CallbackData, prefix="load"):
    """Fills an inline placeholder when inline feedback is off."""
    placeholder: str


class CutButton(CallbackData, prefix="stk"):
    start: float
    length: float
    speed: float
    shape: Shape | None = None

    @classmethod
    def of(cls, cut: Cut) -> "CutButton":
        return cls(start=cut.start, length=cut.length, speed=cut.speed, shape=cut.shape)

    def cut(self) -> Cut:
        return Cut(max(0.0, self.start), min(self.length, LENGTH), min(max(self.speed, MIN_SPEED), MAX_SPEED),
                   self.shape)


class TrackButton(CallbackData, prefix="trk"):
    """Recognizes the music in the video it's under."""


class SoundButton(CallbackData, prefix="snd"):
    """Sends the sound of the video it's under as an audio file."""


class KeepButton(CallbackData, prefix="stp"):
    """Adds the sticker it's under to the user's pack."""


class CurrentButton(CallbackData, prefix="stn"):
    """The option already applied to the sticker."""


_SHAPE_LABELS = {Shape.ORIGINAL: "Ориг", Shape.SQUARE: "1:1", Shape.WIDE: "16:9", Shape.TALL: "9:16",
                 Shape.ROUND: "⚪ Круг"}


def placeholder_keyboard(placeholder: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔄 Обновить", callback_data=LoadButton(placeholder=placeholder).pack())]])


def post_keyboard(username: str, post: CachedPost) -> InlineKeyboardMarkup | None:
    """Inline and guest messages hold one file; this button opens the whole post in the bot's DM."""
    payload = to_payload(post.key)
    if not payload or (len(post.items) < 2 and not post.audio):
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=f"🖼 Весь пост: {post_summary(post)}", url=f"https://t.me/{username}?start={payload}")]])


def video_keyboard(sound: bool) -> InlineKeyboardMarkup:
    """Under a single video in DMs; silent ones get only the sticker button."""
    buttons = [InlineKeyboardButton(text="🎭 Стикер", callback_data=CutButton.of(Cut()).pack())]
    if sound:
        buttons[:0] = [InlineKeyboardButton(text="🎵 Шазам", callback_data=TrackButton().pack()),
                       InlineKeyboardButton(text="🎧 Аудио", callback_data=SoundButton().pack())]
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


def track_keyboard(track: Track) -> InlineKeyboardMarkup:
    query = quote(f"{track.artist} {track.title}")
    links = [("Shazam", track.shazam_url), ("Apple Music", track.apple_music_url),
             ("Spotify", f"https://open.spotify.com/search/{query}"),
             ("YouTube Music", f"https://music.youtube.com/search?q={query}")]
    buttons = [InlineKeyboardButton(text=label, url=url) for label, url in links if url]
    return InlineKeyboardMarkup(inline_keyboard=[buttons[i:i + 2] for i in range(0, len(buttons), 2)])


def describe(cut: Cut, duration: int | None) -> str:
    end = cut.start + cut.span
    text = f"{format_time(cut.start)}–{format_time(min(end, duration) if duration else end)}"
    return text + (f" · ×{cut.speed:g}" if cut.speed != 1 else "")


def _button(text: str, cut: Cut) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=CutButton.of(cut).pack())


def _move_row(cut: Cut, duration: int | None) -> list[InlineKeyboardButton]:
    # A third and a whole sticker's worth of video, so the steps scale with the speed
    small, big = cut.speed, 3 * cut.speed
    moves: dict[float, float] = {}
    for step in (-small, -big, small, big):  # the small step back goes first: near 0 both land on 0
        start = max(0.0, round(cut.start + step, 2))
        if start != cut.start and start not in moves and not (duration and start > duration - 0.5):
            moves[start] = step
    buttons = []
    for start, step in sorted(moves.items()):
        arrow = ("⏪" if step < 0 else "⏩") if abs(step) == big else ("◀️" if step < 0 else "▶️")
        label = f"{arrow} {-step:g}с" if step < 0 else f"{step:g}с {arrow}"
        buttons.append(_button(label, replace(cut, start=start)))
    return buttons


def _speed_row(cut: Cut) -> list[InlineKeyboardButton]:
    buttons = []
    if cut.speed > MIN_SPEED:
        buttons.append(_button(f"🐢 ×{cut.speed / 2:g}", replace(cut, speed=cut.speed / 2)))
    if cut.speed < MAX_SPEED:
        buttons.append(_button(f"🐇 ×{cut.speed * 2:g}", replace(cut, speed=cut.speed * 2)))
    return buttons


def _shape_row(cut: Cut, width: int | None, height: int | None) -> list[InlineKeyboardButton]:
    buttons = []
    for shape, label in _SHAPE_LABELS.items():
        frame = shape.frame
        if shape != Shape.ROUND and frame and width and height and abs(width / height - frame[0] / frame[1]) < 0.03:
            continue  # same as the original
        if shape == cut.shape:
            buttons.append(InlineKeyboardButton(text=f"✓ {label}", callback_data=CurrentButton().pack()))
        else:
            buttons.append(_button(label, replace(cut, shape=shape)))
    return buttons


def sticker_keyboard(cut: Cut, duration: int | None, width: int | None, height: int | None) -> InlineKeyboardMarkup:
    keep = InlineKeyboardButton(text=f"➕ В мой пак · {describe(cut, duration)}", callback_data=KeepButton().pack())
    rows = [_move_row(cut, duration), _speed_row(cut), _shape_row(cut, width, height), [keep]]
    return InlineKeyboardMarkup(inline_keyboard=[row for row in rows if row])


def kept_keyboard(markup: InlineKeyboardMarkup | None, pack: str) -> InlineKeyboardMarkup:
    """The sticker's keyboard with the "add to pack" button turned into a link to the pack."""
    rows = markup.inline_keyboard[:-1] if markup else []
    opened = InlineKeyboardButton(text="✅ В паке — открыть", url=f"https://t.me/addstickers/{pack}")
    return InlineKeyboardMarkup(inline_keyboard=[*rows, [opened]])


def is_kept(markup: InlineKeyboardMarkup | None) -> bool:
    return bool(markup and any(button.url for row in markup.inline_keyboard for button in row))
