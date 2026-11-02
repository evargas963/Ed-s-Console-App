"""The capture daemon's start, Schwab to the screen: the stop takes only this checkout's processes;
why Schwab is not connected reaches the daemon's log and /api/health on its heartbeat; a chain sweep
thread that ends on an error leaves its reason in the daemon's log."""

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
)
from schwab_client import build_client_from_token
from stream_spine import CaptureWriter, HealthRegistry, MessageBus, quote_msg
from tests.capture_store import store_capture
from tests.feed_live_helper import connect, page_socket, reads_to_the_close
from tests.real_chains import CRWD, MRVL, NFLX

REPO = Path(__file__).resolve().parent.parent


async def _until(cond, limit: float = 10.0) -> None:
    end = time.monotonic() + limit
    while not cond():
        assert time.monotonic() < end, "timed out"
        await asyncio.sleep(0.05)


def test_the_stop_takes_only_this_checkouts_processes(tmp_path):
    """launch.stop finds the daemon and the console by launch.running: of two processes started
    the same way, the one started in this checkout's folder (as its daemon's batch and its
    console are) is found, and the one started in another folder
    (another checkout's console, a test's) is not, so the stop's Ctrl+Break never goes to it
    instead of this console. Induced test condition: two sleeping Pythons started by a script of
    this test's own."""
    start = ["-c", f"import time; time.sleep(60)  # {os.getpid()}-{time.monotonic_ns()}"]
    ours, theirs = (
        subprocess.Popen([sys.executable, *start], cwd=cwd) for cwd in (launch.ROOT, tmp_path)
    )
    try:
        found: set = set()
        end = time.monotonic() + 10
        while ours.pid not in found and time.monotonic() < end:
            found = {p.pid for p in launch.running(start)}
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

    async def go():
        stop = asyncio.Event()
        ui = asyncio.create_task(serve_live_ui(stop, heartbeat_fn=daemon.status))
        run = asyncio.create_task(daemon.run(schwab_client, stop))
        await _until(lambda: daemon.status(time.time())["schwab_down"].startswith("NOT CONNECTED"))
        await asyncio.sleep(0.2)
        async with page_socket() as url, connect(url, max_size=None) as ws:
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


def test_a_browser_that_stopped_reading_is_dropped_others_keep_beats_and_the_stop_is_not_held():
    """The daemon's price socket (serve_live_ui, its heartbeat the daemon's own status) and two
    real browser sockets: one reads every frame, one stops reading once its one-message queue is
    full. The one that stopped reading is found once (its beat not taken within HEARTBEAT_SEC),
    dropped (its handler ends, and no more is written to it); the reading browser takes each of
    the next four beats in time (no other beat fails); the daemon's stop ends the server with no
    error. Induced test condition: each beat carries a 2 MB pad, so the
    stalled socket's buffers fill in seconds (the real status, a few KB, takes far longer)."""
    daemon = capture.Daemon(MessageBus(), HealthRegistry(), ["SPY"])

    async def go():
        stop = asyncio.Event()
        stats: dict = {}
        daemon_side = asyncio.create_task(
            serve_live_ui(
                stop,
                heartbeat_fn=lambda now: {**daemon.status(now), "pad": "x" * 2_000_000},
                stats=stats,
            )
        )
        beats: list[float] = []
        async with (
            page_socket() as url,
            connect(url, max_size=None) as reading,
            connect(url, max_queue=1, max_size=None, close_timeout=1) as stalled,
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
            await asyncio.wait_for(reads_to_the_close(stalled), 10)  # it can reconnect
            stop.set()
            await asyncio.wait_for(daemon_side, 5)
            reader.cancel()
        return failures

    failures = asyncio.run(asyncio.wait_for(go(), 40))
    assert failures == 1, (
        f"{failures} beats were not taken: the reading browser missed {failures - 1}"
    )


def _end(process: subprocess.Popen) -> None:
    if process.poll() is None:
        for child in psutil.Process(process.pid).children(recursive=True):
            child.kill()
    process.kill()
    process.wait(30)


def test_the_console_group_is_known_after_its_processes_have_gone():
    """The console ended between the stop finding it and the signal: its group is still named, so
    the stop goes on to what is left. Induced test condition: a Python of this test's own."""
    start = ["-c", f"import time; time.sleep(60)  # {os.getpid()}-{time.monotonic_ns()}"]
    console = subprocess.Popen([sys.executable, *start], cwd=launch.ROOT)
    found: list = []
    try:
        end = time.monotonic() + 10
        while console.pid not in {p.pid for p in found} and time.monotonic() < end:
            found = launch.running(start)
            time.sleep(0.05)
    finally:
        _end(console)
    assert launch.group_leader(found) == console.pid


def test_a_process_that_only_names_the_console_is_not_the_console():
    """A shell and Pythons in the checkout that name the console, in their text or as an argument
    of their own, as a process search does, are not taken for the console."""
    named = launch.CONSOLE_START[-1]
    wait = ["cmd", "/c", f"ping -n 30 127.0.0.1 >nul & rem {named}"]
    if sys.platform != "win32":
        wait = ["sh", "-c", f"sleep 30; echo {named}"]
    sleep = "import time; time.sleep(30)"
    searches = [
        subprocess.Popen(argv, cwd=launch.ROOT)
        for argv in (
            wait,
            [sys.executable, "-c", f"{sleep}  # {named}"],
            [sys.executable, "-c", sleep, named],
            [sys.executable, "-c", sleep, *launch.CONSOLE_START],
        )
    ]
    try:
        end = time.monotonic() + 10
        for p in searches:
            while time.monotonic() < end and named not in " ".join(psutil.Process(p.pid).cmdline()):
                time.sleep(0.05)
            assert named in " ".join(psutil.Process(p.pid).cmdline())
        found = {p.pid for p in launch.running(launch.CONSOLE_START)}
        assert not found & {p.pid for p in searches}
    finally:
        for p in searches:
            _end(p)


def test_a_daemon_whose_console_reader_fails_ends_with_why_and_starts_again(tmp_path):
    """The console's reader of the bus fails: the daemon ends with its error in the log, instead
    of running with no screen served, and keep_running goes on until the stop. Induced test
    condition: a reader that raises."""
    script = (
        "import asyncio\n"
        "from app.market_data.schwab.streaming import capture\n"
        "async def fails(bus, daemon):\n"
        "    raise OSError('the reader failed')\n"
        "async def go():\n"
        "    stop = asyncio.Event()\n"
        "    asyncio.get_running_loop().call_later(capture.RESTART_WAIT_SEC + 3, stop.set)\n"
        "    await capture.keep_running(stop, fails)\n"
        "capture.start_log()\n"
        "asyncio.run(go())\n"
    )
    env = {
        **os.environ,
        "ED_RUNTIME_ROOT": str(tmp_path),
        "SCHWAB_TOKEN_PATH": str(tmp_path / "missing_token.json"),
    }
    done = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO,
        env=env,
        capture_output=True,
        timeout=60,
    )
    (path,) = (tmp_path / "logs").glob("stream_capture.*.log")
    log = path.read_text(encoding="utf-8")
    assert done.returncode == 0, (done.returncode, log)
    assert log.count("capture daemon: ended by an error") >= 2, log
    assert "RuntimeError: the capture daemon's console ended before the stop" in log, log
    assert "OSError: the reader failed" in log, log


def test_a_page_stays_on_through_a_daemon_restart_in_the_one_program(tmp_path):
    """`program:app` over a real socket, a page connected. A daemon run ends with an error; the
    page's connection stands, its beat carries the daemon's status, then none between the runs,
    then the next run's. Induced test condition: the console's reader of each run fails after 3 s.
    """
    script = (
        "import asyncio, sys\n"
        "import uvicorn\n"
        "import program\n"
        "follow = program.follow\n"
        "async def fails(bus, daemon):\n"
        "    reader = asyncio.create_task(follow(bus, daemon))\n"
        "    await asyncio.sleep(3)\n"
        "    reader.cancel()\n"
        "    await asyncio.gather(reader, return_exceptions=True)\n"
        "    raise OSError('the reader failed')\n"
        "program.follow = fails\n"
        "uvicorn.run(program.app, host='127.0.0.1', port=int(sys.argv[1]))\n"
    )
    with socket.create_server(("127.0.0.1", 0)) as s:
        port = s.getsockname()[1]
    env = {
        **os.environ,
        "ED_RUNTIME_ROOT": str(tmp_path),
        "SCHWAB_TOKEN_PATH": str(tmp_path / "missing_token.json"),
    }
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(port)],
        cwd=REPO,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    async def go() -> None:
        beats: list[bool] = []  # each change in whether a beat carried the daemon's status
        async with connect(f"ws://127.0.0.1:{port}/ws", max_size=None) as page:
            while beats[-3:] != [True, False, True]:
                frame = json.loads(await asyncio.wait_for(page.recv(), 10))
                has_status = frame["type"] == "feed" and frame["feed"] is not None
                if frame["type"] == "feed" and beats[-1:] != [has_status]:
                    beats.append(has_status)

    try:
        assert launch.unhealthy_for(port, 120.0) is None
        asyncio.run(asyncio.wait_for(go(), 40))
    finally:
        _end(process)


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
            store_capture(
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

    def priced() -> set[str]:
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
        push_changes.unsubscribe(page)
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
