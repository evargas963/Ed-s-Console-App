"""Production is never behind origin/main, the daemon says which commit it started from, and its
log keeps the days the database keeps.

STAND-INS: local git repositories for GitHub's origin and the production checkout; a free local
port for the daemon's browser socket (8800).
"""
from __future__ import annotations

import asyncio
import logging
import socket
import subprocess
import threading
from datetime import date, timedelta
from pathlib import Path

from app.market_data.schwab.streaming import capture
from app.market_data.schwab.streaming.live_ui import serve_live_ui
from stream_spine import HealthRegistry, MessageBus
from tools.check_never_behind import check


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def _commit(repo: Path, name: str) -> None:
    (repo / name).write_text(name, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", name)
    _git(repo, "push", "-q", "origin", "HEAD:main")


def test_production_behind_origin_main_or_a_daemon_from_another_commit_is_reported(tmp_path):
    """The real daemon's heartbeat (Daemon.status on serve_live_ui) carries the commit it started
    from; a checkout behind origin/main, or a daemon started from another commit, is behind."""
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", "origin.git")
    _git(tmp_path, "clone", "-q", "origin.git", "work")
    _commit(tmp_path / "work", "first")
    _git(tmp_path, "clone", "-q", "origin.git", "prod")
    prod = tmp_path / "prod"
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        url = f"ws://127.0.0.1:{s.getsockname()[1]}"
    daemon, ready, done = capture.Daemon(MessageBus(), HealthRegistry()), threading.Event(), threading.Event()

    async def serve():
        stop = asyncio.Event()
        task = asyncio.create_task(serve_live_ui(daemon.bus, stop, heartbeat_fn=daemon.status,
                                                 host="127.0.0.1", port=int(url.rsplit(":", 1)[1])))
        await asyncio.sleep(0.3)
        ready.set()
        await asyncio.to_thread(done.wait)
        stop.set()
        await task
    server = threading.Thread(target=asyncio.run, args=(serve(),))
    server.start()
    try:
        ready.wait(10)
        daemon.start_commit = _git(prod, "rev-parse", "HEAD")
        at = check(prod, url)
        _commit(tmp_path / "work", "merged on GitHub")
        behind = check(prod, url)
        _git(prod, "pull", "-q", "--ff-only")
        old_daemon = check(prod, url)
    finally:
        done.set()
        server.join(10)
    assert at == []
    assert len(behind) == 1 and behind[0].startswith(f"the checkout {prod} is at ")
    assert len(old_daemon) == 1 and old_daemon[0].startswith(f"the capture daemon started from {daemon.start_commit}")
    assert capture.start_commit() == _git(Path(capture.ROOT), "rev-parse", "HEAD")


def test_the_daemon_log_keeps_a_file_a_day_for_45_days(tmp_path):
    """50 earlier days' files beside the log; at the next midnight's rollover the 45 newest stay."""
    days = [date(2026, 8, 1) + timedelta(days=i) for i in range(50)]
    for d in days:
        (tmp_path / f"stream_capture.log.{d:%Y-%m-%d}").write_text(f"{d}\n", encoding="utf-8")
    handler = capture.log_file(tmp_path / "stream_capture.log")
    handler.emit(logging.LogRecord("capture", logging.INFO, __file__, 0, "today", None, None))
    handler.doRollover()
    handler.close()
    kept = sorted(p.name for p in tmp_path.iterdir() if p.name.startswith("stream_capture.log."))
    assert len(kept) == capture.LOG_DAYS_KEPT == 45 and f"stream_capture.log.{days[0]:%Y-%m-%d}" not in kept
