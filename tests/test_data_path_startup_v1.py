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
import threading
import time
from pathlib import Path

import psutil
import pytest
from websockets.asyncio.client import connect

import db
import launch
import live_market_plane as lmp
import push_changes
import server
from app.market_data.schwab.streaming import capture, live_ui
from app.market_data.schwab.streaming.live_ui import serve_live_ui
from calibration.complete_chain_capture import (
    CAPTURE_BASIS,
    chain_messages,
    persist_complete_chain_capture,
)
from schwab_client import build_client_from_token
from stream_spine import CaptureWriter, HealthRegistry, MessageBus, quote_msg
from tests.real_chains import CRWD, MRVL, NFLX

REPO = Path(__file__).resolve().parent.parent


async def _until(cond, limit: float = 10.0) -> None:
    end = time.monotonic() + limit
    while not cond():
        assert time.monotonic() < end, "timed out"
        await asyncio.sleep(0.05)


@pytest.mark.skipif(
    sys.platform != "win32", reason="the daemon's window is a Windows console window"
)
def test_the_daemons_window_closes_when_its_batch_ends(tmp_path):
    """The launcher's command for the daemon's window (launch.daemon_window) runs the batch in a
    window of its own; when the batch ends (the daemon stopped on request), the window's cmd ends
    too, so no empty window stays open."""
    window_pid = tmp_path / "window.pid"
    bat = tmp_path / "daemon.bat"
    bat.write_text(
        f'@"{sys.executable}" -c "import psutil; window = next(p for p in psutil.Process().parents() '
        f"if p.name().lower() == 'cmd.exe'); open(r'{window_pid}', 'w').write(str(window.pid))\"\r\n",
        encoding="utf-8",
    )
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
    ours, theirs = (
        subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", mark], cwd=cwd)
        for cwd in (launch.ROOT, tmp_path)
    )
    try:
        found: set = set()
        end = time.monotonic() + 10
        while ours.pid not in found and time.monotonic() < end:
            found = {p.pid for p in launch.running(mark)}
            time.sleep(0.05)
        theirs_tree = {theirs.pid} | {
            c.pid for c in psutil.Process(theirs.pid).children(recursive=True)
        }
        assert ours.pid in found, f"this checkout's process {ours.pid} was not found: {found}"
        assert not found & theirs_tree, (
            f"another checkout's process was taken for this one's: {found & theirs_tree}"
        )
    finally:
        for p in (ours, theirs):
            for c in psutil.Process(p.pid).children(recursive=True):
                c.kill()
            p.kill()


def test_a_chain_sweep_that_ends_on_an_error_is_logged(tmp_path, caplog):
    """A forced thread error: the sweep's client raises an error the sweep does not catch (one
    not an Exception), its thread ends, the daemon's log has it with its traceback (a thread
    has no error output under pythonw), and run_chains ends with it, before any stop (run then
    ends the daemon)."""

    class ForcedThreadError(BaseException):
        pass

    def client():
        raise ForcedThreadError("forced in a chain sweep thread")

    sqlite3.connect(tmp_path / "ed_console.db").close()
    daemon = capture.Daemon(MessageBus(), HealthRegistry(), ["SPY"])

    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(
            capture.run_chains(
                daemon,
                tmp_path / "ed_console.db",
                client,
                stop,
                failures=CaptureWriter(tmp_path / "stream_capture.db"),
            )
        )
        await asyncio.wait_for(task, timeout=30)  # the sweep's end ends it, with no stop
        assert not stop.is_set()

    with caplog.at_level("ERROR", logger="capture"):
        asyncio.run(go())
    record = next(r for r in caplog.records if "chain sweep: ended" in r.getMessage())
    assert (
        record.getMessage()
        == "chain sweep: ended on ForcedThreadError: forced in a chain sweep thread"
    )
    assert record.exc_info is not None and record.exc_info[0] is ForcedThreadError


def test_a_market_follower_that_ends_on_an_error_carries_it_out(tmp_path):
    """Induced condition: SPY's same-day chain captured 2026-09-22 with one contract's symbol taken
    out, so the option rule's strike ladders raise. follow_market ends on that error."""
    fixture = json.loads(
        (REPO / "tests" / "fixtures" / "real_spy_0dte_chain.json").read_text(encoding="utf-8")
    )
    contracts = [dict(c) for c in fixture["chain"]]
    del contracts[0]["symbol"]
    bus = MessageBus()
    daemon = capture.Daemon(bus, HealthRegistry(), ["SPY"])

    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(daemon.follow_market(stop))
        await asyncio.sleep(0)
        for topic, msg in chain_messages("SPY", contracts, time.time(), None, None):
            bus.publish(topic, msg)
        await asyncio.wait_for(task, timeout=10)

    with pytest.raises(KeyError, match="symbol"):
        asyncio.run(go())


def test_an_option_rule_error_on_a_price_ends_the_market_follower(tmp_path):
    """Induced condition: SPY's same-day chain captured 2026-09-22 16:46 UTC, at that time, with one
    contract's putCall taken out, arriving before SPY has a price, so the option rule fails only
    when SPY's price comes. follow_market ends on that error, instead of the plane swallowing it."""
    fixture = json.loads(
        (REPO / "tests" / "fixtures" / "real_spy_0dte_chain.json").read_text(encoding="utf-8")
    )
    contracts = [dict(c) for c in fixture["chain"]]
    del contracts[0]["putCall"]
    bus = MessageBus()
    now = fixture["ts_utc"]
    daemon = capture.Daemon(bus, HealthRegistry(), ["SPY"], clock=lambda: now)

    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(daemon.follow_market(stop))
        await asyncio.sleep(0)
        for topic, msg in chain_messages("SPY", contracts, now, None, None):
            bus.publish(topic, msg)
        await asyncio.sleep(0.1)
        bus.publish(
            "quote.SPY",
            quote_msg(
                symbol="SPY",
                last=fixture["spot"],
                src="schwab_l1",
                ts_recv=now,
                native={"key": "SPY", "LAST_PRICE": fixture["spot"]},
            ),
        )
        await asyncio.wait_for(task, timeout=10)

    lmp._by_ticker.pop("SPY", None)
    try:
        with pytest.raises(KeyError, match="putCall"):
            asyncio.run(go())
    finally:
        lmp._by_ticker.pop("SPY", None)  # the plane row its price wrote
        lmp._fields_by_ticker.pop("SPY", None)


def test_a_plane_row_listener_that_fails_ends_the_market_follower():
    """Induced condition: a row listener that raises, added through the plane's own
    add_row_listener. SPY's price (its 2026-09-22 capture's) reaches the plane: follow_market ends
    on the listener's error instead of the plane swallowing it."""
    fixture = json.loads(
        (REPO / "tests" / "fixtures" / "real_spy_0dte_chain.json").read_text(encoding="utf-8")
    )
    bus = MessageBus()
    daemon = capture.Daemon(bus, HealthRegistry(), ["SPY"])

    def failing(ticker):
        raise RuntimeError(f"a listener that fails on {ticker}")

    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(daemon.follow_market(stop))
        await asyncio.sleep(0)
        bus.publish(
            "quote.SPY",
            quote_msg(
                symbol="SPY",
                last=fixture["spot"],
                src="schwab_l1",
                ts_recv=fixture["ts_utc"],
                native={"key": "SPY", "LAST_PRICE": fixture["spot"]},
            ),
        )
        await asyncio.wait_for(task, timeout=10)

    lmp.add_row_listener(failing)
    try:
        with pytest.raises(RuntimeError, match="a listener that fails on SPY"):
            asyncio.run(go())
    finally:
        lmp.remove_row_listener(failing)
        lmp._by_ticker.pop("SPY", None)  # the plane row its price wrote
        lmp._fields_by_ticker.pop("SPY", None)


def test_why_schwab_is_not_connected_reaches_the_log_and_api_health(tmp_path, caplog):
    """The daemon's one client, built by the real builder from a token file that does not exist:
    the connection fails; the daemon's log has why, and its heartbeat, taken from the daemon's
    price socket as the console takes it, gives /api/health the same words with since when."""
    schwab_client = capture.one_schwab_client(
        lambda: build_client_from_token(
            str(tmp_path / "missing_token.json"), "LiveLookingKey", "LiveLookingSecret"
        )
    )
    bus = MessageBus()
    daemon = capture.Daemon(bus, HealthRegistry(), ["SPY"])
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    async def go():
        stop = asyncio.Event()
        ui = asyncio.create_task(
            serve_live_ui(stop, heartbeat_fn=daemon.status, host="127.0.0.1", port=port)
        )
        run = asyncio.create_task(daemon.run(schwab_client, stop))
        await _until(lambda: daemon.status(time.time())["schwab_down"].startswith("NOT CONNECTED"))
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
    logged = [
        r.getMessage()
        for r in caplog.records
        if r.getMessage().startswith("schwab: connection ended")
    ]
    assert logged and logged[0].startswith(
        "schwab: connection ended (ConnectionError: no Schwab client (Token file not found"
    ), logged
    lmp.record_feed_heartbeat(feed)
    reason = server.health()["capabilities"]["schwab_reason"]
    assert re.fullmatch(
        r"NOT CONNECTED since \w{3} \d\d/\d\d \d\d:\d\d [AP]M CT: "
        r"ConnectionError: no Schwab client \(Token file not found.*",
        reason,
        re.S,
    ), reason


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
            stop, heartbeat_fn=lambda now: {**daemon.status(now), "pad": "x" * 2_000_000},
            host="127.0.0.1", port=0, stats=stats))
        await _until(lambda: stats.get("listening"), 5)
        beats: list[float] = []
        async with (
            connect(stats["listening"], max_size=None) as reading,
            connect(stats["listening"], max_queue=1, max_size=None, close_timeout=1),
        ):

            async def read_all():
                async for frame in reading:
                    if json.loads(frame)["type"] == "feed":
                        beats.append(time.monotonic())

            reader = asyncio.create_task(read_all())
            await _until(lambda: stats.get("beat_send_failures"), 15)
            await _until(lambda: stats.get("clients") == 1, 3)
            dropped_at = time.monotonic()
            await _until(
                lambda: sum(t > dropped_at for t in beats) >= 4, 10 * live_ui.HEARTBEAT_SEC
            )
            failures = stats["beat_send_failures"]
            stop.set()
            await asyncio.wait_for(daemon_side, 5)
            reader.cancel()
        return failures

    failures = asyncio.run(asyncio.wait_for(go(), 40))
    assert failures == 1, (
        f"{failures} beats were not taken: the reading browser missed {failures - 1}"
    )


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
        "sys.meta_path.insert(0, _Missing())\n",
        encoding="utf-8",
    )
    env = {**os.environ, "PYTHONPATH": str(site), "ED_RUNTIME_ROOT": str(tmp_path)}
    module = ["-m", "app.market_data.schwab.streaming.capture"]
    if sys.platform == "win32":
        cmd = [str(Path(sys.executable).with_name("pythonw.exe")), *module]
    else:
        cmd = ["sh", "-c", 'exec "$0" "$@" 2>&-', sys.executable, *module]
    done = subprocess.run(cmd, cwd=REPO, env=env, timeout=120)  # no handle passed: pythonw has none
    (path,) = (tmp_path / "logs").glob("stream_capture.*.log")
    log = path.read_text(encoding="utf-8")
    assert done.returncode == 1
    assert "capture daemon loading (pid " in log
    assert "ModuleNotFoundError: No module named 'schwab'" in log, log


def test_a_daemon_whose_live_ui_port_is_held_ends_at_once_with_why_and_its_window_restarts_it(
    tmp_path,
):
    """Another socket holds the live UI's port: the daemon, run as its window runs it, ends with
    the bind's error in its log and an exit code its window restarts on (not EXIT_STOPPED), instead
    of running with no browser served."""
    with socket.socket() as held:
        held.bind(("127.0.0.1", 0))
        held.listen()
        env = {
            **os.environ,
            "ED_RUNTIME_ROOT": str(tmp_path),
            "ED_LIVE_UI_HOST": "127.0.0.1",
            "ED_LIVE_UI_PORT": str(held.getsockname()[1]),
            "ED_LIVE_PUSH_PORT": "0",
            "SCHWAB_TOKEN_PATH": str(tmp_path / "missing_token.json"),
        }
        done = subprocess.run(
            [sys.executable, "-m", "app.market_data.schwab.streaming.capture"],
            cwd=REPO,
            env=env,
            capture_output=True,
            timeout=60,
        )
    (path,) = (tmp_path / "logs").glob("stream_capture.*.log")
    log = path.read_text(encoding="utf-8")
    assert done.returncode == 1, (done.returncode, log)
    assert "capture daemon: ended by an error" in log, log
    assert "RuntimeError: the capture daemon's live ui ended before the stop" in log, log
    assert "OSError" in log, log


def test_the_stored_levels_are_priced_while_a_page_on_another_ticker_takes_ticks():
    """At a console start, the stored captures of the tickers the daemon has not delivered yet are
    priced while a page views a ticker whose options stream. Through the real code, on Schwab's
    captures (tests/real_chains.py): CRWD's chain delivered and priced, a page open on it
    (push_changes); MRVL's and NFLX's captures stored as the daemon writes them (one row per
    expiry, at each capture's time) and queued by the startup load. Induced test condition: one
    of CRWD's contracts ticks back to back (_on_stream_tick, a reprice on each), so a tick lands
    during every pricing. Both stored captures are priced within 10 s, and CRWD is repriced
    meanwhile."""
    tk, stored = "CRWD", (MRVL, NFLX)
    names = tuple(c.ticker for c in stored)
    contracts = [dict(ct) for ct in CRWD.chain]
    for chain in stored:
        by_expiry: dict = {}
        for ct in chain.chain:
            by_expiry.setdefault(ct["expirationDate"][:10], []).append(dict(ct))
        for expiry, cts in by_expiry.items():
            persist_complete_chain_capture(
                server.get_db().db_path,
                ticker=chain.ticker,
                expiry=expiry,
                contracts=cts,
                spot=chain.spot,
                completeness_basis=CAPTURE_BASIS,
                ts_utc=chain.now.timestamp(),
            )
    with server._terrain_cache_lock:  # held by another test on this worker
        for name in names:
            server._terrain_cache.pop(name, None)
    with server._chains_waiting_lock:
        server._chains_delivered.difference_update(names)
    push_changes.bind(None)  # no event loop: another test's may be closed
    page = push_changes.subscribe(tk)
    ticking = threading.Event()

    def ticks():
        while not ticking.is_set():
            server._on_stream_tick(contracts[0]["symbol"])
            time.sleep(0)

    ticker = threading.Thread(target=ticks, daemon=True)

    def priced() -> "set[str]":
        with server._terrain_cache_lock:
            return {name for name in names if name in server._terrain_cache}

    try:
        server._on_chain(
            tk, contracts, CRWD.now.timestamp(), None, (CRWD.spot, CRWD.now.timestamp())
        )
        server._chain_pricing.submit(lambda: None).result(timeout=60)
        before = server._gamma_surface_seq[tk]
        ticker.start()
        try:
            assert server._load_stored_levels(list(names)) == 2
            deadline = time.monotonic() + 10
            while priced() != set(names) and time.monotonic() < deadline:
                time.sleep(0.05)
            done = priced()
            repriced = server._gamma_surface_seq[tk] - before
        finally:
            ticking.set()
            ticker.join(10)
    finally:
        push_changes.unsubscribe(tk, page)
        while True:  # what still waits is priced
            server._chain_pricing.submit(lambda: None).result(timeout=60)
            with server._chains_waiting_lock:
                if not server._chains_waiting:
                    break
        with server._terrain_cache_lock:
            for name in (tk, *names):
                server._terrain_cache.pop(name, None)
        with server._chains_waiting_lock:
            server._chains_delivered.discard(tk)
        with sqlite3.connect(
            server.get_db().db_path
        ) as conn:  # later tests read the newest capture
            conn.executemany(
                "DELETE FROM complete_chain_captures WHERE ticker=? AND ts_utc=?",
                [(c.ticker, c.now.timestamp()) for c in stored],
            )
    assert repriced > 0, "CRWD took no reprice from its ticks"
    assert done == set(names), f"priced while the page's ticker took ticks: {sorted(done)}"


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
        tables = {
            name for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert "level_crosses" in tables
    assert "logging_universe" not in tables, "the console still creates the former ticker board"
