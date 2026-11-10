import datetime

from aiogram.types import Chat, Message, Sticker, User, Video, VideoNote

from bot.telegram.clips import clip_of, video_message

_DM = Chat(id=1, type="private")
_BOT = User(id=2, is_bot=True, first_name="bot")


def _message(message_id, **content):
    return Message(message_id=message_id, date=datetime.datetime.now(), chat=_DM, **content)


def _video(message_id=10):
    return _message(message_id, video=Video(file_id="v", file_unique_id="uv", width=720, height=1280, duration=9))


def test_round_video_is_a_square_clip():
    note = _message(1, video_note=VideoNote(file_id="n", file_unique_id="un", length=384, duration=5))
    clip = clip_of(note)
    assert (clip.width, clip.height, clip.duration, clip.round) == (384, 384, 5, True)


def test_buttons_work_on_the_video_they_are_under_or_reply_to():
    video = _video()
    prompt = _message(11, from_user=_BOT, text="?", reply_to_message=video)
    sticker = _message(12, from_user=_BOT, reply_to_message=video, sticker=Sticker(
        file_id="s", file_unique_id="us", type="regular", width=512, height=512, is_animated=False, is_video=True))
    assert video_message(video) is video
    assert video_message(prompt) is video and video_message(sticker) is video


def test_no_video_when_it_was_deleted():
    assert video_message(_message(11, text="?")) is None
    assert video_message(_message(11, text="?", reply_to_message=_message(10, text="hi"))) is None
    assert video_message(None) is None
