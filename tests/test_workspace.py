from bot import jobs
from bot.media import workspace


def test_shared_workdir_survives_cleanup_until_the_last_job_ends():
    with workspace.reusable("clip-x") as first:
        with workspace.reusable("clip-x") as second:
            assert first == second
        (first / "source").write_bytes(b"video")
        workspace.cleanup_stale(max_age=0)
        assert (first / "source").is_file()
    workspace.cleanup_stale(max_age=0)
    assert not first.exists()


def test_busy_holds_a_user_until_the_job_ends():
    busy = jobs.Busy()
    with busy.hold(1):
        assert 1 in busy and 2 not in busy
    assert 1 not in busy


def test_reset_leaves_an_empty_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace.config, "TMP_DIR", tmp_path / "tmp")
    (tmp_path / "tmp" / "old").mkdir(parents=True)
    workspace.reset()
    assert (tmp_path / "tmp").is_dir() and not any((tmp_path / "tmp").iterdir())
