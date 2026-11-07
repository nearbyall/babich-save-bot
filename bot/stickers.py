"""Video stickers: a 3-second cut of any video, collected into the user's own pack."""
import asyncio
import contextlib
import itertools
import logging
import re
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, replace
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputSticker,
    Message,
    ReplyParameters,
    User,
)
from aiogram.utils.chat_action import ChatActionSender

from . import config, downloader
from .delivery import tracked
from .downloader import Album, DownloadError, download
from .links import find_links, message_text

log = logging.getLogger(__name__)
router = Router()

# Telegram's rules for video stickers: WEBM/VP9 without sound, up to 3 s and 256 KB, one side 512 px
LENGTH = 3.0
MAX_SIZE = 256 * 1024
EMOJI = "🎬"
PACK_SIZE = 120
# Bots can fetch files only up to 20 MB from Telegram; bigger videos are downloaded again by their link
MAX_TELEGRAM_FILE = 20 * config.MB
# Speed goes up and down by doubling: x8 packs 24 s of video into a sticker, x0.25 stretches 0.75 s
MIN_SPEED, MAX_SPEED = 0.25, 8.0
# Shapes: code in callback data -> (button label, frame size); "o" keeps the video's own proportions
SHAPES = {"o": ("Ориг", None), "1": ("1:1", (512, 512)), "w": ("16:9", (512, 288)), "t": ("9:16", (288, 512)),
          "r": ("⚪ Круг", (512, 512))}
# Round stickers get their corners cut out with an alpha mask, drawn once and looped
# (computing it for every frame doubles the encoding time)
_CIRCLE = ("color=black:s=512x512:d=1,format=gray,geq=lum='255*clip(256.5-hypot(X-255.5,Y-255.5),0,1)',"
           "trim=end_frame=1,loop=loop=-1:size=1")

_encoders = asyncio.Semaphore(config.MAX_PARALLEL_STICKERS)
# One sticker at a time per user; repeated taps get "wait"
_busy: set[int] = set()

_TIME = r"(?:(\d{1,2}):)?(\d{1,3}(?:[.,]\d+)?)"
_TIME_RE = re.compile(rf"\s*{_TIME}(?:\s*[-–—]\s*{_TIME})?\s*")
HINT = "Под ним — сдвиг, скорость и форма. Точный момент — ответь на видео временем, например 0:12 или 0:12-0:14"


@dataclass
class Clip:
    file_id: str
    unique_id: str
    size: int | None
    duration: int | None
    width: int | None
    height: int | None
    round: bool  # video note: round stickers by default


def _clip(message: Message | None) -> Clip | None:
    if message is None:
        return None
    if media := message.video or message.animation:
        return Clip(media.file_id, media.file_unique_id, media.file_size, media.duration,
                    media.width, media.height, False)
    if note := message.video_note:
        return Clip(note.file_id, note.file_unique_id, note.file_size, note.duration, note.length, note.length, True)
    doc = message.document
    if doc and (doc.mime_type or "").startswith("video/"):
        return Clip(doc.file_id, doc.file_unique_id, doc.file_size, None, None, None, False)
    return None


@dataclass(frozen=True)
class Cut:
    """`length` seconds of sticker from `start` of the video, played at `speed`, framed as `shape`.

    Lives in callback data, so every button under a sticker knows the whole cut."""
    start: float = 0.0
    length: float = LENGTH
    speed: float = 1.0
    shape: str | None = None  # key of SHAPES; None: round for video notes, the original for the rest

    @property
    def span(self) -> float:
        """Seconds of the video that go into the sticker."""
        return self.length * self.speed

    @property
    def data(self) -> str:
        return f"stk:{self.start:g}:{self.length:g}:{self.speed:g}:{self.shape or ''}"

    @classmethod
    def from_data(cls, data: str) -> "Cut":
        # Buttons sent before speed and shape existed carry only start and length
        start, length, speed, shape = (data.split(":")[1:] + ["1", ""])[:4]
        return cls(max(0.0, float(start)), min(float(length), LENGTH),
                   min(max(float(speed), MIN_SPEED), MAX_SPEED), shape if shape in SHAPES else None)

    @classmethod
    def from_range(cls, start: float, span: float) -> "Cut":
        """A typed range longer than a sticker gets sped up to fit."""
        speed = 1.0
        while span / speed > LENGTH and speed < MAX_SPEED:
            speed *= 2
        return cls(start, min(span / speed, LENGTH), speed)


def parse_time(text: str | None) -> tuple[float, float] | None:
    """"12", "0:12", "1:02.5" or a range "0:12-0:14" -> (start, seconds of video)."""
    m = _TIME_RE.fullmatch(text or "")
    if not m:
        return None
    start = int(m[1] or 0) * 60 + float(m[2].replace(",", "."))
    if not m[4]:
        return start, LENGTH
    end = int(m[3] or 0) * 60 + float(m[4].replace(",", "."))
    return (start, end - start) if end > start else None


def _fmt(seconds: float) -> str:
    minutes, seconds = divmod(seconds, 60)
    return f"{int(minutes)}:{seconds:05.2f}".rstrip("0").rstrip(".")


def _describe(cut: Cut, duration: int | None) -> str:
    end = cut.start + cut.span
    text = f"{_fmt(cut.start)}–{_fmt(min(end, duration) if duration else end)}"
    return text + (f" · ×{cut.speed:g}" if cut.speed != 1 else "")


def sticker_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🎭 Сделать стикер", callback_data=Cut().data)]])


def _move_label(step: float, big: float) -> str:
    if step < 0:
        return f"{'⏪' if -step == big else '◀️'} {-step:g}с"
    return f"{step:g}с {'⏩' if step == big else '▶️'}"


def _keyboard(cut: Cut, duration: int | None, width: int | None, height: int | None) -> InlineKeyboardMarkup:
    """Move the cut, change its speed or shape, or keep it."""
    # Steps of a third and of a whole sticker's worth of video, so they scale with the speed
    small, big = cut.speed, 3 * cut.speed
    moves = {}
    for step in (-small, -big, small, big):  # back by the small step first: near 0 both land on 0
        new = max(0.0, round(cut.start + step, 2))
        if new != cut.start and new not in moves and not (duration and new > duration - 0.5):
            moves[new] = step
    nav = [InlineKeyboardButton(text=_move_label(step, big), callback_data=replace(cut, start=new).data)
           for new, step in sorted(moves.items())]

    speed = []
    if cut.speed > MIN_SPEED:
        speed.append(InlineKeyboardButton(text=f"🐢 ×{cut.speed / 2:g}",
                                          callback_data=replace(cut, speed=cut.speed / 2).data))
    if cut.speed < MAX_SPEED:
        speed.append(InlineKeyboardButton(text=f"🐇 ×{cut.speed * 2:g}",
                                          callback_data=replace(cut, speed=cut.speed * 2).data))

    shapes = []
    for code, (label, size) in SHAPES.items():
        if code in "1wt" and width and height and abs(width / height - size[0] / size[1]) < 0.03:
            continue  # same as the original
        current = code == cut.shape
        shapes.append(InlineKeyboardButton(text=f"✓ {label}" if current else label,
                                           callback_data="stn" if current else replace(cut, shape=code).data))

    keep = InlineKeyboardButton(text=f"➕ В мой пак · {_describe(cut, duration)}", callback_data="stp")
    return InlineKeyboardMarkup(inline_keyboard=[row for row in (nav, speed, shapes, [keep]) if row])


def _in_pack(message: Message) -> bool:
    markup = message.reply_markup
    return bool(markup and any(b.url for row in markup.inline_keyboard for b in row))


# --- Making the sticker ---

def _encode(source: Path, dest: Path, cut: Cut) -> None:
    chain = [f"setpts=(PTS-STARTPTS)/{cut.speed:g}"] if cut.speed != 1 else []
    chain.append("fps=30")
    if size := SHAPES[cut.shape][1]:
        chain.append(f"scale={size[0]}:{size[1]}:force_original_aspect_ratio=increase,crop={size[0]}:{size[1]}")
    else:
        chain.append("scale=512:512:force_original_aspect_ratio=decrease:force_divisible_by=2")
    graph = "[0:v]" + ",".join(chain)
    if cut.shape == "r":
        graph += f",format=yuva420p[v];{_CIRCLE}[m];[v][m]alphamerge=shortest=1"
    pix_fmt = "yuva420p" if cut.shape == "r" else "yuv420p"
    # VP9 overshoots the bitrate by ~20% on busy footage; aim low so most cuts fit on the first try
    bitrate = MAX_SIZE * 8 * 0.65 / cut.length
    for _ in range(3):
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-nostats", "-progress", "pipe:1", "-y",
             "-ss", f"{cut.start:.2f}", "-t", f"{cut.span:.3f}", "-i", str(source),
             "-filter_complex", graph, "-t", f"{cut.length:.3f}", "-an", "-sn", "-map_metadata", "-1",
             "-c:v", "libvpx-vp9", "-pix_fmt", pix_fmt, "-crf", "30", "-b:v", str(int(bitrate)),
             "-deadline", "good", "-cpu-used", "4", "-row-mt", "1", str(dest)],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode:
            log.warning("sticker encoding failed: %s", result.stderr.strip()[-500:])
            raise DownloadError("Не получилось сделать стикер из этого видео.")
        frames = re.findall(r"^frame=(\d+)", result.stdout, re.MULTILINE)
        if not frames or frames[-1] == "0":
            raise DownloadError("На этом месте в видео уже нет кадров.")
        size = dest.stat().st_size
        if size <= MAX_SIZE:
            return
        bitrate *= MAX_SIZE * 0.85 / size
    raise DownloadError("Тут слишком много движения — не влезает в 256 КБ. Попробуй другой момент.")


async def _source(bot: Bot, message: Message, clip: Clip, user_id: int, workdir: Path) -> Path:
    """The video file, kept for a while so moving the cut doesn't fetch it again."""
    path = workdir / "source"
    if path.is_file():
        return path
    if downloader.free_disk() < config.MIN_FREE_DISK:
        raise DownloadError("На сервере заканчивается место, попробуй позже.")
    part = workdir / "source.part"
    if (clip.size or 0) <= MAX_TELEGRAM_FILE:
        try:
            await bot.download(clip.file_id, destination=part, timeout=120)
            return part.rename(path)
        except TelegramBadRequest as e:  # "file is too big" when the size wasn't known
            log.info("can't fetch %s from Telegram: %s", clip.unique_id, e)
    links = find_links(message_text(message))
    if not links:
        raise DownloadError("Видео больше 20 МБ — такие бот не может забрать из Telegram. "
                            "Пришли ссылку на него или файл поменьше.")
    media = await download(links[0], user_id)
    try:
        if isinstance(media, Album):
            video = next((item.path for item in media.items if item.kind == "video"), None)
            if video is None:
                raise DownloadError("В этом посте нет видео.")
        else:
            video = media.path
        shutil.move(video, path)
    finally:
        media.cleanup()
    return path


def busy(user_id: int) -> bool:
    return user_id in _busy


async def make(bot: Bot, source: Message | None, user: User, cut: Cut) -> Message | None:
    """Cut a sticker out of the video in `source` and send it in reply; errors go to the chat."""
    chat_id = user.id  # stickers are a DM feature
    reply = source and ReplyParameters(message_id=source.message_id, allow_sending_without_reply=True)
    clip = _clip(source)
    if clip is None:
        await bot.send_message(chat_id, "❌ Не вижу видео — пришли его заново.")
        return None
    workdir = config.TMP_DIR / f"sticker-{clip.unique_id}"
    dest = workdir / f"{uuid.uuid4().hex}.webm"
    _busy.add(user.id)
    try:
        with tracked(), downloader.in_use(workdir):
            async with ChatActionSender.choose_sticker(bot=bot, chat_id=chat_id):
                workdir.mkdir(parents=True, exist_ok=True)
                path = await _source(bot, source, clip, user.id, workdir)
                duration, width, height = clip.duration, clip.width, clip.height
                if not (duration and width and height):
                    width, height, duration = await asyncio.to_thread(downloader.probe, path)
                if duration and cut.start >= duration:
                    raise DownloadError(f"В видео всего {_fmt(duration)}.")
                cut = replace(cut, shape=cut.shape or ("r" if clip.round else "o"))
                started = time.monotonic()
                async with _encoders:
                    await asyncio.to_thread(_encode, path, dest, cut)
                log.info("sticker from %s, %s %s: %d KB, %.1fs", clip.unique_id, _describe(cut, duration), cut.shape,
                         dest.stat().st_size // 1024, time.monotonic() - started)
                return await bot.send_sticker(chat_id, FSInputFile(dest), emoji=EMOJI, reply_parameters=reply,
                                              reply_markup=_keyboard(cut, duration, width, height),
                                              request_timeout=60)
    except DownloadError as e:
        await bot.send_message(chat_id, f"❌ {e}", reply_parameters=reply)
    except TelegramAPIError:
        log.exception("failed to send sticker from %s", clip.unique_id)
        await bot.send_message(chat_id, "❌ Telegram не принял стикер. Попробуй другой момент.", reply_parameters=reply)
    except Exception:
        log.exception("failed to make sticker from %s", clip.unique_id)
        await bot.send_message(chat_id, "❌ Не получилось сделать стикер.", reply_parameters=reply)
    finally:
        dest.unlink(missing_ok=True)
        _busy.discard(user.id)
    return None


# --- The user's pack ---

async def add_to_pack(bot: Bot, user: User, file_id: str) -> str:
    """Add a sticker to the user's pack (u<id>_by_<bot>, then _2, _3… once full); returns the pack name."""
    me = await bot.me()
    sticker = InputSticker(sticker=file_id, format="video", emoji_list=[EMOJI])
    for n in itertools.count(1):
        name = f"u{user.id}{f'_{n}' if n > 1 else ''}_by_{me.username}"
        try:
            pack = await bot.get_sticker_set(name=name)
        except TelegramBadRequest:  # no such pack yet
            title = f"{user.first_name[:30]} · @{me.username}" + (f" {n}" if n > 1 else "")
            await bot.create_new_sticker_set(user_id=user.id, name=name, title=title, stickers=[sticker])
            return name
        if len(pack.stickers) < PACK_SIZE:
            await bot.add_sticker_to_set(user_id=user.id, name=name, sticker=sticker)
            return name


# --- Handlers (DMs only); this router goes before the one that treats any DM text as links ---

@router.callback_query(F.data.startswith("stk:"))
async def on_cut(callback: CallbackQuery, bot: Bot) -> None:
    """🎭 under a video, or a move/speed/shape button under a sticker made from it."""
    message = callback.message
    if not isinstance(message, Message):
        await callback.answer("Сообщение устарело — пришли видео заново.", show_alert=True)
        return
    if busy(callback.from_user.id):
        await callback.answer("Подожди, ещё делаю предыдущий стикер.")
        return
    cut = Cut.from_data(callback.data)
    redo = message.sticker is not None
    source = message.reply_to_message if redo else message
    if source is None:
        await callback.answer("Видео удалено — пришли его заново.", show_alert=True)
        return
    if redo:
        clip = _clip(source)
        await callback.answer(f"⏳ {_describe(cut, clip and clip.duration)}")
    else:
        await callback.answer(f"🎭 Делаю стикер из первых {cut.length:g} секунд. {HINT}")
    if await make(bot, source, callback.from_user, cut) and redo and not _in_pack(message):
        with contextlib.suppress(TelegramAPIError):
            await message.delete()  # the new cut replaces this one, unless it's already kept in the pack


@router.callback_query(F.data == "stn")
async def on_current(callback: CallbackQuery) -> None:
    await callback.answer("Уже так")


@router.callback_query(F.data == "stp")
async def on_keep(callback: CallbackQuery, bot: Bot) -> None:
    message = callback.message
    if not isinstance(message, Message) or not message.sticker:
        await callback.answer("Стикер не найден.")
        return
    if busy(callback.from_user.id):
        await callback.answer("Секунду…")
        return
    _busy.add(callback.from_user.id)
    try:
        name = await add_to_pack(bot, callback.from_user, message.sticker.file_id)
    except TelegramAPIError as e:
        log.warning("failed to add sticker to the pack of %s: %s", callback.from_user.id, e)
        await callback.answer("Не получилось добавить в пак, попробуй ещё раз.", show_alert=True)
        return
    finally:
        _busy.discard(callback.from_user.id)
    rows = message.reply_markup.inline_keyboard[:-1] if message.reply_markup else []
    opened = InlineKeyboardButton(text="✅ В паке — открыть", url=f"https://t.me/addstickers/{name}")
    with contextlib.suppress(TelegramAPIError):
        await message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=[*rows, [opened]]))
    await callback.answer("✅ Добавил в твой пак")


@router.message(F.chat.type == ChatType.PRIVATE, F.text.func(parse_time))
async def on_time(message: Message, bot: Bot) -> None:
    """A time sent in reply to a video: cut the sticker from there."""
    source = message.reply_to_message
    if _clip(source) is None:
        text = "ответь временем на само видео, а не на стикер" if source and source.sticker else \
            "ответь этим временем на видео"
        await message.reply(f"Чтобы сделать стикер с этого момента, {text}.")
        return
    if busy(message.from_user.id):
        await message.reply("Подожди, ещё делаю предыдущий стикер.")
        return
    await make(bot, source, message.from_user, Cut.from_range(*parse_time(message.text)))


@router.message(F.chat.type == ChatType.PRIVATE,
                F.video | F.animation | F.video_note | F.document.mime_type.startswith("video/"))
async def on_video(message: Message, bot: Bot) -> None:
    """Any video, GIF or round video sent or forwarded to the bot becomes a sticker."""
    if busy(message.from_user.id):
        await message.reply("Подожди, ещё делаю предыдущий стикер.")
        return
    await make(bot, message, message.from_user, Cut())
