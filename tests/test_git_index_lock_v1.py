"""Seams for stale git index.lock defense."""
import time

from tools.check_git_index_lock import clear_stale_index_lock, stale_index_lock_info


def test_fresh_lock_not_cleared(tmp_path, monkeypatch):
    gd = tmp_path / "git"
    gd.mkdir()
    lock = gd / "index.lock"
    lock.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        "tools.check_git_index_lock._git_dir",
        lambda repo=None: gd,
    )
    assert stale_index_lock_info(tmp_path, stale_sec=60) is None
    assert clear_stale_index_lock(tmp_path, stale_sec=60) is None
    assert lock.is_file()


def test_stale_lock_cleared(tmp_path, monkeypatch):
    gd = tmp_path / "git"
    gd.mkdir()
    lock = gd / "index.lock"
    lock.write_text("", encoding="utf-8")
    old = time.time() - 120
    # touch mtime into the past
    import os
    os.utime(lock, (old, old))
    monkeypatch.setattr(
        "tools.check_git_index_lock._git_dir",
        lambda repo=None: gd,
    )
    info = stale_index_lock_info(tmp_path, stale_sec=60)
    assert info is not None
    msg = clear_stale_index_lock(tmp_path, stale_sec=60)
    assert msg and "cleared" in msg
    assert not lock.is_file()
