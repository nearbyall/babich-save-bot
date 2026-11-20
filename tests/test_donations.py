import pytest

from bot.telegram.handlers.donations import MAX_STARS, amount
from bot.telegram.keyboards import DONATIONS, DonateButton, donate_keyboard


@pytest.mark.parametrize("args, stars", [
    ("300", 300), (" 1 ", 1), (str(MAX_STARS), MAX_STARS),
    (None, None), ("", None), ("0", None), (str(MAX_STARS + 1), None), ("-5", None), ("1.5", None), ("abc", None),
])
def test_amount(args, stars):
    assert amount(args) == stars


def test_donate_keyboard():
    rows = donate_keyboard().inline_keyboard
    assert [[b.text for b in row] for row in rows] == [["⭐ 50", "⭐ 100", "⭐ 250"], ["⭐ 500", "⭐ 1000"]]
    assert [DonateButton.unpack(b.callback_data).stars for row in rows for b in row] == list(DONATIONS)
    assert all(amount(str(stars)) for stars in DONATIONS)
