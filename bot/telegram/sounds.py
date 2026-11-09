"""The music in videos in the chat (Shazam) and their sound as audio files."""
import asyncio
import contextlib
import logging
import re
import uuid
from collections import OrderedDict

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile, LinkPreviewOptions, Message, ReplyParameters, User
from aiogram.utils.chat_action import ChatActionSender

from .. import jobs
from ..errors import UserError
from ..media import audio, ffmpeg, shazam
from ..media.shazam import Track
from . import clips, texts
from .clips import Clip
from .keyboards import track_keyboard

log = logging.getLogger(__name__)

# Results by clip, found or not: Shazam allows only a few requests a minute
KNOWN_TRACKS = 1000
_known: OrderedDict[str, Track | None] = OrderedDict()
_listening = jobs.Busy()
_extracting = jobs.Busy()


def busy(user_id: int) -> bool:
    return user_id in _listening or user_id in _extracting


async def identify(bot: Bot, source: Message, clip: Clip, user: User) -> None:
    """Reply to the video with the track playing in it."""
    reply = _reply_to(source)
    async with _errors_in_reply(bot, user.id, reply, "Не получилось распознать трек."):
        with jobs.tracked(), _listening.hold(user.id):
            track = await _recognize(bot, source, clip, user.id)
            await _send_track(bot, user.id, track, reply)


async def send_sound(bot: Bot, source: Message, clip: Clip, user: User) -> None:
    """Reply to the video with its sound as an audio file."""
    reply = _reply_to(source)
    async with _errors_in_reply(bot, user.id, reply, "Не получилось достать звук."):
        with jobs.tracked(), _extracting.hold(user.id), clips.workdir(clip) as workdir:
            async with ChatActionSender.upload_voice(bot=bot, chat_id=user.id):
                path = await clips.fetch(bot, source, clip, user.id, workdir)
                title, performer = texts.sound_names(source.caption, _known.get(clip.unique_id))
                name = uuid.uuid4().hex
                try:
                    sound = await asyncio.to_thread(audio.extract, path, workdir / f"{name}.m4a", title, performer)
                    cover = await asyncio.to_thread(ffmpeg.thumbnail, path, clip.width, clip.height,
                                                    workdir / f"{name}.jpg")
                    await bot.send_audio(user.id, FSInputFile(sound.path, filename=_filename(title, performer)),
                                         title=title, performer=performer, duration=sound.duration,
                                         thumbnail=FSInputFile(cover) if cover else None,
                                         reply_parameters=reply, request_timeout=300)
                finally:
                    for file in workdir.glob(f"{name}.*"):
                        file.unlink(missing_ok=True)


async def _recognize(bot: Bot, source: Message, clip: Clip, user_id: int) -> Track | None:
    if clip.unique_id in _known:
        _known.move_to_end(clip.unique_id)
        return _known[clip.unique_id]
    with clips.workdir(clip) as workdir:
        async with ChatActionSender.typing(bot=bot, chat_id=user_id):
            path = await clips.fetch(bot, source, clip, user_id, workdir)
            track = await shazam.recognize(path)
    log.info("Shazam on %s: %s", clip.unique_id, track and f"{track.artist} – {track.title}")
    _known[clip.unique_id] = track
    if len(_known) > KNOWN_TRACKS:
        _known.popitem(last=False)
    return track


async def _send_track(bot: Bot, chat_id: int, track: Track | None, reply: ReplyParameters) -> None:
    if track is None:
        await bot.send_message(chat_id, texts.NO_TRACK, reply_parameters=reply)
        return
    caption, markup = texts.track_caption(track), track_keyboard(track)
    if track.cover:
        try:
            await bot.send_photo(chat_id, track.cover, caption=caption, reply_markup=markup, reply_parameters=reply)
            return
        except TelegramBadRequest as e:
            log.info("Telegram didn't take the cover of %s: %s", track.title, e)
    await bot.send_message(chat_id, caption, reply_markup=markup, reply_parameters=reply,
                           link_preview_options=LinkPreviewOptions(is_disabled=True))


def _reply_to(message: Message) -> ReplyParameters:
    return ReplyParameters(message_id=message.message_id, allow_sending_without_reply=True)


def _filename(title: str, performer: str | None) -> str:
    name = f"{performer} - {title}" if performer else title
    return re.sub(r'[\\/:*?"<>|\n]+', " ", name)[:80].strip() + ".m4a"


@contextlib.asynccontextmanager
async def _errors_in_reply(bot: Bot, chat_id: int, reply: ReplyParameters, failure: str):
    """Errors of a job on a video go to the chat in reply to it."""
    try:
        yield
        return
    except UserError as e:
        text = str(e)
    except Exception:
        log.exception(failure)
        text = failure
    await bot.send_message(chat_id, f"❌ {text}", reply_parameters=reply)
