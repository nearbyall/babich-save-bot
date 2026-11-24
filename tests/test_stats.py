import asyncio
import datetime

import pytest
from aiogram.types import (CallbackQuery, Chat, ChosenInlineResult, InlineQuery, Message, PreCheckoutQuery, Update,
                           User)

from bot import db as db_module
from bot.db import Database, Stats
from bot.telegram import texts
from bot.telegram.stats import place, source

BOT = User(id=1, is_bot=True, first_name="Bot", username="SaveBot")
USER = User(id=42, is_bot=False, first_name="A")
DM = Chat(id=42, type="private")
GROUP = Chat(id=-100, type="supergroup", title="g")
NOW = datetime.datetime(2026, 11, 24)


class FakeBot:
    id = BOT.id

    async def me(self):
        return BOT


def at(monkeypatch, date):
    monkeypatch.setattr(db_module, "_utc_today", lambda: datetime.date.fromisoformat(date))


def message(chat=DM, text=None, **fields):
    return Message(message_id=1, date=NOW, chat=chat, from_user=USER, text=text, **fields)


def where(**update):
    return asyncio.run(place(Update(update_id=1, **update), FakeBot()))


def test_visits_make_users_active_and_returning(tmp_path, monkeypatch):
    db = Database(tmp_path / "db.sqlite3")
    at(monkeypatch, "2026-10-01")
    db.mark_seen(1, "dm", "ad_x")
    at(monkeypatch, "2026-11-20")
    db.mark_seen(1, "dm", "dm")
    db.mark_seen(2, "inline", "inline")
    at(monkeypatch, "2026-11-24")
    db.mark_seen(2, "dm", "dm")
    db.mark_seen(2, "dm", "dm")
    db.mark_seen(2, "inline", "inline")
    db.mark_seen(3, "group", "group")
    db.mark_seen(4, "dm", "post")

    s = db.stats()
    assert (s.since, s.users, s.new, s.returning) == ("2026-10-01", 4, 2, 2)
    assert s.active == (3, 4, 4)
    assert s.places == {"dm": 3, "group": 1, "inline": 1}
    assert s.sources == {"group": 1, "inline": 1, "post": 1}, "the first visit decides, and only 30 days count"


def test_days_count_once_per_day(tmp_path, monkeypatch):
    db = Database(tmp_path / "db.sqlite3")
    at(monkeypatch, "2026-11-23")
    db.mark_seen(1, "dm", "dm")
    db.mark_seen(1, "inline", "inline")
    assert db.stats().returning == 0
    at(monkeypatch, "2026-11-24")
    db.mark_seen(1, "inline", "inline")
    assert db.stats().returning == 1
    assert Database(tmp_path / "db.sqlite3").stats().users == 1


def test_groups_blocks_and_events(tmp_path, monkeypatch):
    db = Database(tmp_path / "db.sqlite3")
    at(monkeypatch, "2026-11-24")
    db.mark_seen(1, "dm", "dm")
    db.set_blocked(1, True)
    db.set_blocked(99, True)  # never seen: unknown, not counted
    for chat in (-1, -2, -3):
        db.mark_group(chat)
    db.mark_group(-2, present=False)
    db.count("link:TikTok")
    db.count("link:TikTok")
    db.count("stars", 50)
    at(monkeypatch, "2026-11-10")
    db.count("link:YouTube")
    at(monkeypatch, "2026-11-24")

    s = db.stats()
    assert (s.groups, s.blocked) == (2, 1)
    assert s.events == {"stars": 50, "link:TikTok": 2}
    assert Database(tmp_path / "db.sqlite3").stats().groups == 2
    db.set_blocked(1, False)
    assert db.stats().blocked == 0


def test_old_visits_are_forgotten_but_people_stay(tmp_path, monkeypatch):
    db = Database(tmp_path / "db.sqlite3")
    at(monkeypatch, "2026-08-01")
    db.mark_seen(1, "dm", "dm")
    at(monkeypatch, "2026-11-24")
    db.mark_seen(2, "dm", "dm")
    assert db.forget_old_visits(60) == 1
    s = db.stats()
    assert (s.users, s.active) == (2, (1, 1, 1))


def test_where_users_use_the_bot():
    assert where(message=message(text="hi")) == "dm"
    assert where(pre_checkout_query=PreCheckoutQuery(id="1", from_user=USER, currency="XTR", total_amount=1,
                                                     invoice_payload="donate")) == "dm"
    assert where(inline_query=InlineQuery(id="1", from_user=USER, query="", offset="")) == "inline"
    assert where(chosen_inline_result=ChosenInlineResult(result_id="r", from_user=USER, query="q")) == "inline"
    assert where(guest_message=message(GROUP, "@SaveBot x", guest_query_id="g")) == "guest"
    assert where(callback_query=CallbackQuery(id="1", from_user=USER, chat_instance="c", data="x",
                                              inline_message_id="i")) == "inline"
    assert where(callback_query=CallbackQuery(id="1", from_user=USER, chat_instance="c", data="x",
                                              message=message(GROUP))) == "group"


@pytest.mark.parametrize("text, counted", [
    ("/dl https://x", True), ("/dl@savebot https://x", True), ("/start@otherbot", False),
    ("look @SaveBot", True), ("just chatting", False), (None, False),
])
def test_group_messages_count_when_meant_for_the_bot(text, counted):
    assert where(message=message(GROUP, text)) == ("group" if counted else None)


def test_group_replies_to_the_bot_count():
    reply = Message(message_id=2, date=NOW, chat=GROUP, from_user=BOT, text="video")
    assert where(message=message(GROUP, "thanks", reply_to_message=reply)) == "group"


@pytest.mark.parametrize("text, origin", [
    ("/start", None), ("/start ad_nov", "ad_nov"), ("/start tt_7312345678901234567", "post"),
    ("/start help", "inline"), ("/start <b>", "b"), ("/start " + "x" * 64, "x" * 32), ("hello", None),
])
def test_where_new_users_came_from(text, origin):
    assert source(Update(update_id=1, message=message(text=text))) == origin


def test_stats_text():
    s = Stats(since="2026-11-24", users=312, new=14, returning=120, active=(41, 158, 290),
              places={"dm": 98, "inline": 40}, sources={"ad_<nov>": 57, "post": 8}, groups=7, blocked=12,
              events={"link:TikTok": 455, "link:YouTube": 45, "fail:TikTok": 25, "shazam": 85, "stars": 150,
                      "donation": 3})
    text = texts.stats(s)
    assert "с 24.11.2026" in text
    assert "👥 Пользователи: 312 · новых сегодня 14 · возвращались 120" in text
    assert "📈 Активные: сегодня 41 · за 7 дней 158 · за 30 дней 290" in text
    assert "💬 Где: личка 98 · инлайн 40" in text
    assert "📥 Ссылок: 500 · ошибок 25 (5%)\n      TikTok 455 · YouTube 45" in text
    assert "🎵 Шазам 85 · 🎧 Аудио 0" in text and "⭐ Донаты 3 на 150 ⭐" in text
    assert text.endswith("ad_&lt;nov&gt; 57 · кнопка «Весь пост» 8")


def test_stats_text_when_empty(english):
    assert texts.stats(Stats(None, 0, 0, 0, (0, 0, 0))).startswith("📊 Nothing to show yet")
    text = texts.stats(Stats("2026-11-24", 1, 1, 0, (1, 1, 1)))
    assert "💬 Where: —" in text and "📥 Links: 0 · errors 0" in text and text.endswith("—")
