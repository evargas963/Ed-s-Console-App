"""Production is never behind origin/main, the daemon says which commit it started from, it can
be stopped without a kill, and its log keeps the days the database keeps (the operator,
2026-10-08: the bars of 10-02, 10-05 and 10-06 died with force-killed daemons, the production
checkout was 6 commits behind, and one 50 MB log backup left nothing of those days).

STAND-INS: local git repositories for GitHub's origin and the production checkout; free local
ports for the daemon's sockets (8800, 8799).
"""
from __future__ import annotations

import asyncio
import json
import logging
import socket
import subprocess
import threading
from datetime import date, timedelta
from pathlib import Path

from app.market_data.schwab.streaming import capture
from app.market_data.schwab.streaming.live_push import serve_live_push
from app.market_data.schwab.streaming.live_ui import serve_live_ui
from stream_spine import HealthRegistry, MessageBus
from tools import check_never_behind


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def _commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", name)
    return _git(repo, "rev-parse", "HEAD")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _production(tmp_path: Path) -> "tuple[Path, Path]":
    """(origin, production): a bare origin with one commit on main, and a clone of it."""
    origin, work = tmp_path / "origin.git", tmp_path / "work"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    _git(tmp_path, "clone", "-q", str(origin), str(work))
    _commit(work, "first")
    _git(work, "push", "-q", "origin", "HEAD:main")
    prod = tmp_path / "prod"
    _git(tmp_path, "clone", "-q", str(origin), str(prod))
    return work, prod


def test_a_checkout_behind_origin_main_fails_and_one_at_it_passes(tmp_path, capsys):
    work, prod = _production(tmp_path)
    nobody = f"ws://127.0.0.1:{_free_port()}"            # no daemon running
    _commit(work, "merged on GitHub")
    _git(work, "push", "-q", "origin", "HEAD:main")

    assert check_never_behind.main(["--repo", str(prod), "--daemon", nobody]) == 1
    out, err = capsys.readouterr()
    assert "1 commits behind" in out and "FAIL: the checkout is not at origin/main" in err
    assert "no daemon heartbeat at" in out

    _git(prod, "pull", "-q", "--ff-only")
    assert check_never_behind.main(["--repo", str(prod), "--daemon", nobody]) == 0
    assert "0 commits behind" in capsys.readouterr().out


def test_the_running_daemon_s_start_commit_is_read_from_its_heartbeat(tmp_path, capsys):
    """The daemon's own status, on its own browser socket, carries the commit it started from;
    a daemon started from another commit than the checkout's fails the check."""
    _work, prod = _production(tmp_path)
    head = _git(prod, "rev-parse", "HEAD")
    port = _free_port()
    daemon = capture.Daemon(MessageBus(), HealthRegistry())
    ready, done = threading.Event(), threading.Event()
    results: list = []

    async def serve():
        stop = asyncio.Event()
        task = asyncio.create_task(serve_live_ui(daemon.bus, stop, heartbeat_fn=daemon.status,
                                                 host="127.0.0.1", port=port))
        await asyncio.sleep(0.3)
        ready.set()
        while not done.is_set():
            await asyncio.sleep(0.05)
        stop.set()
        await task
    server = threading.Thread(target=asyncio.run, args=(serve(),))
    server.start()
    try:
        ready.wait(10)
        for started in (head, "0" * 40):
            daemon.start_commit = started
            results.append((check_never_behind.main(["--repo", str(prod), "--daemon", f"ws://127.0.0.1:{port}"]),
                            "".join(capsys.readouterr())))
    finally:
        done.set()
        server.join(10)

    (ok, ok_out), (bad, bad_out) = results
    assert ok == 0 and f"capture daemon: started from {head}" in ok_out
    assert bad == 1 and "FAIL: the running daemon did not start from the checkout's commit" in bad_out


def test_the_daemon_records_the_commit_it_started_from():
    assert capture.start_commit() == _git(Path(capture.ROOT), "rev-parse", "HEAD")


def test_a_stop_on_the_console_socket_stops_the_daemon():
    """{"op": "stop"} on the console socket (8799) sets the daemon's stop: it ends as at Ctrl+C,
    its writer writing everything handed to it (no Stop-Process -Force)."""
    port = _free_port()

    async def go():
        from websockets.asyncio.client import connect
        daemon, stop = capture.Daemon(MessageBus(), HealthRegistry()), asyncio.Event()
        daemon.stop = stop
        server = asyncio.create_task(serve_live_push(daemon.bus, stop, host="127.0.0.1", port=port,
                                                     on_request=daemon.console_frame))
        await asyncio.sleep(0.3)
        async with connect(f"ws://127.0.0.1:{port}") as ws:
            await ws.send(json.dumps({"op": "stop"}))
            await asyncio.wait_for(stop.wait(), timeout=5)
        await server
        return stop.is_set()
    assert asyncio.run(go())


def test_the_daemon_log_keeps_a_file_a_day_for_45_days(tmp_path):
    """50 earlier days' files beside the log; at the next midnight's rollover the log keeps the
    45 newest days and a new file for today; the oldest 5 are gone."""
    path = tmp_path / "stream_capture.log"
    days = [date(2026, 8, 1) + timedelta(days=i) for i in range(50)]
    for d in days:
        (tmp_path / f"stream_capture.log.{d:%Y-%m-%d}").write_text(f"{d}\n", encoding="utf-8")
    handler = capture.log_file(path)
    try:
        handler.emit(logging.LogRecord("capture", logging.INFO, __file__, 0, "today", None, None))
        handler.doRollover()
    finally:
        handler.close()
    kept = sorted(p.name for p in tmp_path.iterdir() if p.name.startswith("stream_capture.log."))
    assert len(kept) == capture.LOG_DAYS_KEPT == 45
    assert f"stream_capture.log.{days[0]:%Y-%m-%d}" not in kept and path.exists()
