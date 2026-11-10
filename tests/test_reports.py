from aiogram.types import User

from bot.telegram import reports


def test_header_names_the_reporter_and_escapes_the_text():
    user = User(id=42, is_bot=False, first_name="Vlad <3", username="vlad", language_code="ru<b>")
    text = reports.header(user, " видео & звук не скачались \n")
    assert text.startswith(f"{reports.MARK} #u42\n")
    assert '<a href="tg://user?id=42">Vlad &lt;3</a> · @vlad · ru&lt;b&gt;' in text
    assert "<blockquote expandable>видео &amp; звук не скачались</blockquote>" in text


def test_header_without_username_or_text():
    text = reports.header(User(id=7, is_bot=False, first_name="A"), "  ")
    assert '<a href="tg://user?id=7">A</a>\n' in text
    assert "<i>без описания</i>" in text


def test_header_cuts_long_reports():
    assert len(reports.header(User(id=7, is_bot=False, first_name="A"), "x" * 10_000)) < 4096


def test_too_soon_lets_one_report_through_per_interval(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(reports.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(reports, "_last_report", {})
    assert not reports.too_soon(1)
    assert reports.too_soon(1)
    assert not reports.too_soon(2)
    clock[0] += reports.INTERVAL
    assert not reports.too_soon(1)
