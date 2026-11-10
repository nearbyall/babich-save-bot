import ast
import re
import string
from pathlib import Path

import pytest

from bot import i18n
from bot.errors import UserError
from bot.i18n import TEXTS, t

SOURCES = [path for path in Path("bot").rglob("*.py") if path != Path("bot/i18n.py")]
CYRILLIC = re.compile("[А-Яа-яЁё]")


def _fields(text):
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def _strings(tree):
    """String constants of the code, f-string parts included."""
    return [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]


def _keys_asked_for(tree):
    """Literal keys passed to t(), variants() and UserError()."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name in ("t", "variants", "UserError") and isinstance(node.args[0].value, str):
                yield node.args[0].value


TREES = {path: ast.parse(path.read_text()) for path in SOURCES}


@pytest.mark.parametrize("key", TEXTS)
def test_both_languages_take_the_same_placeholders(key):
    ru, en = TEXTS[key]
    assert ru.strip() and en.strip()
    assert _fields(ru) == _fields(en)


def test_every_key_asked_for_exists():
    missing = {(str(path), key) for path, tree in TREES.items() for key in _keys_asked_for(tree) if key not in TEXTS}
    assert not missing


def test_every_text_is_used():
    used = {s for tree in TREES.values() for s in _strings(tree)}
    unused = [key for key in TEXTS if key != "help" and key not in used and not any(
        key.startswith(prefix) for prefix in ("cmd_",))]
    assert not unused


def test_no_russian_outside_the_catalog():
    found = [(str(path), s) for path, tree in TREES.items() for s in _strings(tree) if CYRILLIC.search(s)]
    assert not found, "put user-facing texts into bot/i18n.py"


def test_language_comes_from_the_context_unless_given():
    assert t("send") == "📥 Отправить"
    assert t("send", "en") == "📥 Send"
    token = i18n.current.set("en")
    try:
        assert t("loading", platform="TikTok") == "⏳ Downloading from TikTok…"
        assert t("loading", "ru", platform="TikTok") == "⏳ Скачиваю из TikTok…"
    finally:
        i18n.current.reset(token)


def test_user_errors_speak_the_language_of_whoever_shows_them(english):
    error = UserError("too_long", minutes=10)
    assert str(error) == "The video is longer than 10 min, I don't download those."
    token = i18n.current.set("ru")
    try:
        assert str(error) == "Видео длиннее 10 мин — такие не качаю."
    finally:
        i18n.current.reset(token)
