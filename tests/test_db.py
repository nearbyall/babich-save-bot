import time

from bot.db import CachedFile, CachedPost, Database


def test_files_and_posts_round_trip(tmp_path):
    db = Database(tmp_path / "db.sqlite3")
    video = CachedFile("vid", "video", "user", 720, 1280, 10)
    post = CachedPost("tt:2", [CachedFile("p1", "photo", "user", 1080, 1350, None)], "aud", "user")
    db.put(["tt:1", "tiktok:1"], video)
    db.put(["tt-short:x", "tt:2"], post)
    assert db.get("tiktok:1") == video
    assert db.get("tt-short:x") == post
    assert db.get("tt:3") is None

    db.forget(video)
    db.forget(post)
    assert db.get("tt:1") is None and db.get("tt:2") is None


def test_prune_drops_old_and_extra_records(tmp_path, monkeypatch):
    db = Database(tmp_path / "db.sqlite3")
    monkeypatch.setattr(time, "time", lambda: 1_000_000)
    db.put(["old"], CachedFile("a", "video", None, None, None, None))
    for i in range(3):
        monkeypatch.setattr(time, "time", lambda: 1_000_000 + 40 * 86400 + i)
        db.put([f"new{i}"], CachedFile(f"b{i}", "video", None, None, None, None))
    assert db.prune(max_age_days=30, max_rows=2) == 2
    assert db.get("old") is None and db.get("new0") is None and db.get("new2")


def test_reports_remember_their_sender(tmp_path):
    db = Database(tmp_path / "db.sqlite3")
    db.remember_report(10, 42)
    assert db.reporter(10) == 42
    assert db.reporter(11) is None


def test_first_user_becomes_the_owner(tmp_path):
    db = Database(tmp_path / "db.sqlite3")
    assert db.remember_owner(1) and not db.remember_owner(2)
    assert db.owner_id() == 1
