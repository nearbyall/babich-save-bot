import pytest

from bot.db import CachedFile, CachedPost
from bot.media.shazam import Track
from bot.media.sticker import Cut, Shape
from bot.telegram.keyboards import (
    CutButton,
    LangButton,
    RoundButton,
    SoundButton,
    TrackButton,
    is_kept,
    kept_keyboard,
    lang_keyboard,
    post_keyboard,
    round_keyboard,
    sticker_keyboard,
    track_keyboard,
    video_keyboard,
)


def _labels(markup):
    return [[button.text for button in row] for row in markup.inline_keyboard]


@pytest.mark.parametrize("data, cut", [
    ("stk:0:3:1:", Cut(0, 3, 1, None)),
    ("stk:6:3:2:r", Cut(6, 3, 2, Shape.ROUND)),
    ("stk:-1:9:64:w", Cut(0, 3, 8, Shape.WIDE)),
])
def test_cut_button_unpacks_sent_buttons(data, cut):
    assert CutButton.unpack(data).cut() == cut


def test_cut_button_round_trip():
    cut = Cut(12.25, 2.5, 0.25, Shape.TALL)
    assert CutButton.unpack(CutButton.of(cut).pack()).cut() == cut
    assert len(CutButton.of(cut).pack()) <= 64


def test_video_keyboard():
    (shazam, sound), (sticker, round_video) = video_keyboard(sound=True).inline_keyboard
    assert [shazam.text, sound.text, sticker.text, round_video.text] == ["🎵 Шазам", "🎧 Аудио", "🎭 Стикер",
                                                                         "⚪ Кружок"]
    assert TrackButton.unpack(shazam.callback_data) and SoundButton.unpack(sound.callback_data)
    assert CutButton.unpack(sticker.callback_data).cut() == Cut()
    assert RoundButton.unpack(round_video.callback_data).start == 0


def test_keyboards_in_english(english):
    assert _labels(video_keyboard(sound=True)) == [["🎵 Shazam", "🎧 Audio"], ["🎭 Sticker", "⚪ Round video"]]
    assert _labels(sticker_keyboard(Cut(0, 3, 1, Shape.ORIGINAL), 20, 1080, 1920)) == [
        ["1s ▶️", "3s ⏩"],
        ["🐢 ×0.5", "🐇 ×2"],
        ["✓ Orig", "1:1", "16:9", "⚪ Circle"],
        ["➕ Add to my pack · 0:00–0:03"],
    ]
    photo = CachedFile("f", "photo", None, None, None, None)
    video = CachedFile("v", "video", None, None, None, None)
    assert post_keyboard("bot", CachedPost("tt:1", [photo, photo, video], "a", None)).inline_keyboard[0][0].text == (
        "🖼 Whole post: 2 photos and 1 video + sound")
    assert post_keyboard("bot", CachedPost("tt:1", [photo, video, video], None, None)).inline_keyboard[0][0].text == (
        "🖼 Whole post: 1 photo and 2 videos")


def test_lang_keyboard_marks_the_current_language():
    assert _labels(lang_keyboard("en")) == [["🇷🇺 Русский", "✓ 🇬🇧 English"]]
    assert LangButton.unpack(lang_keyboard("ru").inline_keyboard[0][1].callback_data).lang == "en"


def test_silent_and_round_videos_get_fewer_buttons():
    assert _labels(video_keyboard(sound=False)) == [["🎭 Стикер", "⚪ Кружок"]]
    assert _labels(video_keyboard(sound=True, round_video=True)) == [["🎵 Шазам", "🎧 Аудио"], ["🎭 Стикер"]]


@pytest.mark.parametrize("start, duration, buttons", [
    (0, 45, None),
    (0, 60, None),
    (0, 150, [("1:00–2:00 ▶️", 60)]),
    (60, 150, [("◀️ 0:00–1:00", 0), ("2:00–2:30 ▶️", 120)]),
    (120, 150, [("◀️ 1:00–2:00", 60)]),
])
def test_round_keyboard_moves_a_minute(start, duration, buttons):
    markup = round_keyboard(start, duration)
    found = markup and [(b.text, RoundButton.unpack(b.callback_data).start) for b in markup.inline_keyboard[0]]
    assert found == buttons


def test_track_keyboard_links():
    full = Track("Monster", "DotEXE", shazam_url="https://shazam/x", apple_music_url="https://apple/x")
    assert [[(b.text, b.url) for b in row] for row in track_keyboard(full).inline_keyboard] == [
        [("Shazam", "https://shazam/x"), ("Apple Music", "https://apple/x")],
        [("Spotify", "https://open.spotify.com/search/DotEXE%20Monster"),
         ("YouTube Music", "https://music.youtube.com/search?q=DotEXE%20Monster")],
    ]
    assert _labels(track_keyboard(Track("T", "A"))) == [["Spotify", "YouTube Music"]]


def test_sticker_keyboard_at_the_start_of_a_vertical_video():
    markup = sticker_keyboard(Cut(0, 3, 1, Shape.ORIGINAL), duration=20, width=1080, height=1920)
    assert _labels(markup) == [
        ["1с ▶️", "3с ⏩"],
        ["🐢 ×0.5", "🐇 ×2"],
        ["✓ Ориг", "1:1", "16:9", "⚪ Круг"],
        ["➕ В мой пак · 0:00–0:03"],
    ]


def test_steps_scale_with_speed_and_stop_at_the_end():
    markup = sticker_keyboard(Cut(6, 3, 2, Shape.SQUARE), duration=12, width=1920, height=1080)
    assert _labels(markup) == [
        ["⏪ 6с", "◀️ 2с", "2с ▶️"],
        ["🐢 ×1", "🐇 ×4"],
        ["Ориг", "✓ 1:1", "9:16", "⚪ Круг"],
        ["➕ В мой пак · 0:06–0:12 · ×2"],
    ]


def test_speed_limits_hide_buttons():
    slowest = sticker_keyboard(Cut(0, 3, 0.25, Shape.ROUND), 20, 640, 640)
    fastest = sticker_keyboard(Cut(0, 3, 8, Shape.ROUND), 20, 640, 640)
    assert _labels(slowest)[1] == ["🐇 ×0.5"]
    assert _labels(fastest)[1] == ["🐢 ×4"]
    assert "1:1" not in _labels(slowest)[2]  # a square video is already 1:1


def test_kept_keyboard_links_to_the_pack():
    markup = kept_keyboard(sticker_keyboard(Cut(0, 3, 1, Shape.ORIGINAL), 20, 1080, 1920), "u1_by_bot")
    assert markup.inline_keyboard[-1][0].url == "https://t.me/addstickers/u1_by_bot"
    assert len(markup.inline_keyboard) == 4 and is_kept(markup)
    assert not is_kept(video_keyboard(sound=True))


def test_post_keyboard():
    photo = CachedFile("f", "photo", None, None, None, None)
    video = CachedFile("v", "video", None, None, None, None)
    post = CachedPost("tt:1", [photo, photo, video], "audio", "user")
    button = post_keyboard("bot", post).inline_keyboard[0][0]
    assert button.text == "🖼 Весь пост: 2 фото и 1 видео + звук"
    assert button.url == "https://t.me/bot?start=tt_1"
    assert post_keyboard("bot", CachedPost("ig:X", [photo], None, None)) is None
