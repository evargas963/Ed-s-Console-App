"""The capture daemon's start, Schwab to the screen: its window closes when its batch ends, and the
stop takes only this checkout's processes; why Schwab is not connected reaches the daemon's log and /api/health on its heartbeat; a module that fails to load, and a chain sweep
thread that ends on an error, leave their reason in the daemon's log."""
from __future__ import annotations

import asyncio
import json
import os
import re
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest
from websockets.asyncio.client import connect

import db
import launch
import live_market_plane as lmp
import server
from app.market_data.schwab.streaming import capture, live_ui
from app.market_data.schwab.streaming.live_ui import serve_live_ui
from schwab_client import build_client_from_token
from stream_spine import CaptureWriter, HealthRegistry, MessageBus

REPO = Path(__file__).resolve().parent.parent


async def _until(cond, limit: float = 10.0) -> None:
    end = time.monotonic() + limit
    while not cond():
        assert time.monotonic() < end, "timed out"
        await asyncio.sleep(0.05)


@pytest.mark.skipif(sys.platform != "win32", reason="the daemon's window is a Windows console window")
def test_the_daemons_window_closes_when_its_batch_ends(tmp_path):
    """The launcher's command for the daemon's window (launch.daemon_window) runs the batch in a
    window of its own; when the batch ends (the daemon stopped on request), the window's cmd ends
    too, so no empty window stays open."""
    window_pid = tmp_path / "window.pid"
    bat = tmp_path / "daemon.bat"
    bat.write_text(f'@"{sys.executable}" -c "import psutil; window = next(p for p in psutil.Process().parents() '
                   f'if p.name().lower() == \'cmd.exe\'); open(r\'{window_pid}\', \'w\').write(str(window.pid))"\r\n',
                   encoding="utf-8")
    subprocess.Popen(launch.daemon_window(bat), cwd=launch.ROOT)
    deadline = time.monotonic() + 60.0
    while not window_pid.exists():
        assert time.monotonic() < deadline, "the batch never ran"
        time.sleep(0.1)
    window = int(window_pid.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 30.0
    while psutil.pid_exists(window) and time.monotonic() < deadline:
        time.sleep(0.1)
    still_open = psutil.pid_exists(window)
    if still_open:
        psutil.Process(window).kill()
    assert not still_open, "the daemon's window stayed open after its batch ended"


def test_the_stop_takes_only_this_checkouts_processes(tmp_path):
    """launch.stop finds the daemon and the console by launch.running: of two processes carrying
    the same mark, the one started in this checkout's folder (as its daemon's batch and its
    console are) is found, and the one started in another folder (another checkout's console, a
    test's) is not, so the stop's Ctrl+Break never goes to it instead of this console. Induced
    test condition: two sleeping Pythons carrying a mark of this test's own."""
    mark = f"ed-stop-mark-{os.getpid()}-{time.monotonic_ns()}"
    ours, theirs = (subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", mark], cwd=cwd)
                    for cwd in (launch.ROOT, tmp_path))
    try:
        found: set = set()
        end = time.monotonic() + 10
        while ours.pid not in found and time.monotonic() < end:
            found = {p.pid for p in launch.running(mark)}
            time.sleep(0.05)
        theirs_tree = {theirs.pid} | {c.pid for c in psutil.Process(theirs.pid).children(recursive=True)}
        assert ours.pid in found, f"this checkout's process {ours.pid} was not found: {found}"
        assert not found & theirs_tree, f"another checkout's process was taken for this one's: {found & theirs_tree}"
    finally:
        for p in (ours, theirs):
            for c in psutil.Process(p.pid).children(recursive=True):
                c.kill()
            p.kill()


def test_a_chain_sweep_that_ends_on_an_error_is_logged(tmp_path, caplog):
    """A forced thread error: the sweep's client raises an error the sweep does not catch (one
    not an Exception), its thread ends, and the daemon's log has it with its traceback (a thread
    has no error output under pythonw)."""
    class ForcedThreadError(BaseException):
        pass

    def client():
        raise ForcedThreadError("forced in a chain sweep thread")
    sqlite3.connect(tmp_path / "ed_console.db").close()
    daemon = capture.Daemon(MessageBus(), HealthRegistry(), ["SPY"])

    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(capture.run_chains(daemon, tmp_path / "ed_console.db", client, stop,
                                                      failures=CaptureWriter(tmp_path / "stream_capture.db")))
        await _until(lambda: any("chain sweep: ended" in r.getMessage() for r in caplog.records))
        stop.set()
        await asyncio.wait_for(task, timeout=30)
    with caplog.at_level("ERROR", logger="capture"):
        asyncio.run(go())
    record = next(r for r in caplog.records if "chain sweep: ended" in r.getMessage())
    assert record.getMessage() == "chain sweep: ended on ForcedThreadError: forced in a chain sweep thread"
    assert record.exc_info is not None and record.exc_info[0] is ForcedThreadError


def test_why_schwab_is_not_connected_reaches_the_log_and_api_health(tmp_path, caplog):
    """The daemon's one client, built by the real builder from a token file that does not exist:
    the connection fails; the daemon's log has why, and its heartbeat, taken from the daemon's
    price socket as the console takes it, gives /api/health the same words with since when."""
    schwab_client = capture.one_schwab_client(
        lambda: build_client_from_token(str(tmp_path / "missing_token.json"), "LiveLookingKey", "LiveLookingSecret"))
    bus = MessageBus()
    daemon = capture.Daemon(bus, HealthRegistry(), ["SPY"])
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    async def go():
        stop = asyncio.Event()
        ui = asyncio.create_task(serve_live_ui(bus, stop, heartbeat_fn=daemon.status, host="127.0.0.1", port=port))
        run = asyncio.create_task(daemon.run(schwab_client, stop))
        await _until(lambda: daemon.status()["schwab_down"].startswith("NOT CONNECTED"))
        await asyncio.sleep(0.2)
        async with connect(f"ws://127.0.0.1:{port}", max_size=None) as ws:
            await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY"]}))
            while (msg := json.loads(await asyncio.wait_for(ws.recv(), 5)))["type"] != "feed":
                pass
        stop.set()
        await asyncio.gather(ui, run)
        return msg["feed"]
    with caplog.at_level("WARNING", logger="capture"):
        feed = asyncio.run(go())
    assert feed["schwab_socket_open"] is False
    logged = [r.getMessage() for r in caplog.records if r.getMessage().startswith("schwab: connection ended")]
    assert logged and logged[0].startswith(
        "schwab: connection ended (ConnectionError: no Schwab client (Token file not found"), logged
    lmp.record_feed_heartbeat(feed)
    reason = server.health()["capabilities"]["schwab_reason"]
    assert re.fullmatch(r"NOT CONNECTED since \w{3} \d\d/\d\d \d\d:\d\d [AP]M CT: "
                        r"ConnectionError: no Schwab client \(Token file not found.*", reason, re.S), reason


def test_a_browser_that_stopped_reading_is_dropped_the_others_keep_their_beats_and_the_stop_is_not_held():
    """The daemon's price socket (serve_live_ui, its heartbeat the daemon's own status) and two
    real browser sockets: one reads every frame, one stops reading once its one-message queue is
    full. The one that stopped reading is found once (its beat not taken within HEARTBEAT_SEC),
    dropped (its connection aborted: a close frame cannot be written to a browser that does not
    read), and its handler ends; the reading browser takes each of the next four beats in time
    (no other beat fails); the daemon's stop ends
    the server with no error. Induced test condition: each beat carries a 2 MB pad, so the
    stalled socket's buffers fill in seconds (the real status, a few KB, takes far longer)."""
    daemon = capture.Daemon(MessageBus(), HealthRegistry(), ["SPY"])

    async def go():
        stop = asyncio.Event()
        stats: dict = {}
        daemon_side = asyncio.create_task(serve_live_ui(
            MessageBus(), stop, heartbeat_fn=lambda: {**daemon.status(), "pad": "x" * 2_000_000},
            host="127.0.0.1", port=0, stats=stats))
        await _until(lambda: stats.get("listening"), 5)
        beats: list[float] = []
        async with connect(stats["listening"], max_size=None) as reading, \
                connect(stats["listening"], max_queue=1, max_size=None, close_timeout=1):

            async def read_all():
                async for frame in reading:
                    if json.loads(frame)["type"] == "feed":
                        beats.append(time.monotonic())
            reader = asyncio.create_task(read_all())
            await _until(lambda: stats.get("beat_send_failures"), 15)
            await _until(lambda: stats.get("clients") == 1, 3)
            dropped_at = time.monotonic()
            await _until(lambda: sum(t > dropped_at for t in beats) >= 4, 10 * live_ui.HEARTBEAT_SEC)
            failures = stats["beat_send_failures"]
            stop.set()
            await asyncio.wait_for(daemon_side, 5)
            reader.cancel()
        return failures

    failures = asyncio.run(asyncio.wait_for(go(), 40))
    assert failures == 1, f"{failures} beats were not taken: the reading browser missed {failures - 1}"


def test_a_module_that_fails_to_load_leaves_its_reason_in_the_daemons_log(tmp_path):
    """The daemon run with no error output (pythonw on Windows; elsewhere its fd 2 closed), with
    schwab-py missing: the log file under its runtime root has why."""
    site = tmp_path / "site"
    site.mkdir()
    (site / "sitecustomize.py").write_text(
        "import sys\n"
        "class _Missing:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name == 'schwab' or name.startswith('schwab.'):\n"
        "            raise ModuleNotFoundError(f\"No module named '{name}'\", name=name)\n"
        "sys.meta_path.insert(0, _Missing())\n", encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(site), "ED_RUNTIME_ROOT": str(tmp_path)}
    module = ["-m", "app.market_data.schwab.streaming.capture"]
    if sys.platform == "win32":
        cmd = [str(Path(sys.executable).with_name("pythonw.exe")), *module]
    else:
        cmd = ["sh", "-c", 'exec "$0" "$@" 2>&-', sys.executable, *module]
    done = subprocess.run(cmd, cwd=REPO, env=env, timeout=120)   # no handle passed: pythonw has none
    (path,) = (tmp_path / "logs").glob("stream_capture.*.log")
    log = path.read_text(encoding="utf-8")
    assert done.returncode == 1
    assert "capture daemon loading (pid " in log
    assert "ModuleNotFoundError: No module named 'schwab'" in log, log


def test_a_database_path_under_backups_is_refused_as_any_other_non_canonical_path(tmp_path):
    """No database backups are kept (operator 2026-10-10): a path under backups/db/ is no class
    of its own. The console's database (db.EdDB) refuses it as it refuses every path but the
    canonical one, named unknown."""
    with pytest.raises(ValueError, match=r"classification=unknown"):
        db.EdDB(tmp_path / "backups" / "db" / "ed_console.db", allow_noncanonical=False)


def test_the_console_database_starts_without_the_former_ticker_board(tmp_path):
    """One watchlist, kept by the daemon (#486): the console's database (db.EdDB) creates only
    the level crosses at its start, never the former ticker board's logging_universe."""
    path = tmp_path / "ed_console.db"
    db.EdDB(path, allow_noncanonical=True)
    with sqlite3.connect(path) as conn:
        tables = {name for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "level_crosses" in tables
    assert "logging_universe" not in tables, "the console still creates the former ticker board"
