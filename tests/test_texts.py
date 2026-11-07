import pytest

from bot.telegram.texts import help_text


@pytest.mark.parametrize("feature", [
    "TikTok", "Instagram", "YouTube Shorts", "slideshow", "слайдшоу", "@savebot", "/dl", "Весь пост",
    "Сделать стикер", "×0.25–×8", "круг", "стикерпак", "0:12-0:20",
])
def test_help_lists_every_feature(feature):
    assert feature in help_text("savebot")


def test_help_fits_one_message():
    assert len(help_text("savebot")) < 4096
