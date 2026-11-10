import pytest

from bot.media.shazam import Track
from bot.telegram.texts import help_text, sound_names, track_caption


@pytest.mark.parametrize("feature", [
    "TikTok", "Instagram", "YouTube Shorts", "slideshow", "слайдшоу", "@savebot", "/dl", "Весь пост",
    "Шазам", "Аудио", "⚪ Кружок", "forward", "перешли", "🎭 Стикер", "×0.25–×8", "круг", "стикерпак", "0:12-0:20",
])
def test_help_lists_every_feature(feature):
    assert feature in help_text("savebot")


def test_help_fits_one_message():
    assert len(help_text("savebot")) < 4096


def test_track_caption():
    assert track_caption(Track("A & B", "C", album="D", released="2006")) == "🎵 <b>A &amp; B</b>\n👤 C\n💿 D · 2006"
    assert track_caption(Track("A", "C")) == "🎵 <b>A</b>\n👤 C"


def test_sound_names():
    assert sound_names("TikTok · SOFI", None) == ("Звук из TikTok", "SOFI")
    assert sound_names("Instagram", None) == ("Звук из Instagram", None)
    assert sound_names(None, None) == ("Звук из видео", None)
    assert sound_names("TikTok · SOFI", Track("Song", "Artist")) == ("Song", "Artist")
