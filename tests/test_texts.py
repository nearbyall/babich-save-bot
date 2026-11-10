import pytest

from bot.i18n import t
from bot.media.shazam import Track
from bot.telegram.texts import help_text, sound_names, track_caption

COMMON = ["TikTok", "Instagram", "YouTube Shorts", "@savebot", "/dl", "×0.25–×8", "0:12-0:20", "/report", "/lang"]


@pytest.mark.parametrize("lang, feature", [("ru", f) for f in COMMON + [
    "слайдшоу", "Весь пост", "🎵 Шазам", "🎧 Аудио", "⚪ Кружок", "перешли", "🎭 Стикер", "круг", "стикерпак",
    "идея", "English",
]] + [("en", f) for f in COMMON + [
    "slideshow", "Whole post", "🎵 Shazam", "🎧 Audio", "⚪ Round video", "forward", "🎭 Sticker", "circle",
    "sticker pack", "idea", "Русский",
]])
def test_help_lists_every_feature(lang, feature):
    assert feature in t("help", lang, username="savebot")


def test_help_names_the_buttons_as_they_are():
    for lang in ("ru", "en"):
        for button in ("btn_shazam", "btn_audio", "btn_sticker", "btn_round"):
            assert t(button, lang) in t("help", lang, username="savebot")


def test_help_fits_one_message():
    assert len(help_text("savebot")) < 4096
    assert len(t("help", "en", username="savebot")) < 4096


def test_track_caption():
    assert track_caption(Track("A & B", "C", album="D", released="2006")) == "🎵 <b>A &amp; B</b>\n👤 C\n💿 D · 2006"
    assert track_caption(Track("A", "C")) == "🎵 <b>A</b>\n👤 C"


def test_sound_names():
    assert sound_names("TikTok · SOFI", None) == ("Звук из TikTok", "SOFI")
    assert sound_names("Instagram", None) == ("Звук из Instagram", None)
    assert sound_names(None, None) == ("Звук из видео", None)
    assert sound_names("TikTok · SOFI", Track("Song", "Artist")) == ("Song", "Artist")


def test_sound_names_in_english(english):
    assert sound_names("TikTok · SOFI", None) == ("Sound from TikTok", "SOFI")
    assert sound_names(None, None) == ("Sound from a video", None)
