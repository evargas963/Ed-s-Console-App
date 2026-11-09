"""The capture daemon's start, Schwab to the screen.

Its window closes when its batch ends, and the
stop takes only this checkout's processes; why Schwab is not connected reaches the daemon's log and
/api/health on its heartbeat; a module that fails to load, and a chain sweep thread that ends on an
error, leave their reason in the daemon's log.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import site
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
import venv
from dataclasses import asdict
from pathlib import Path

import psutil
import pytest
import uvicorn
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

import db
import launch
import live_market_plane as lmp
import push_changes
import server
import time_et
from app.market_data.schwab.streaming import capture, live_ui
from app.market_data.schwab.streaming.program_lock import Ports, program_ports
from calibration.complete_chain_capture import (
    CAPTURE_BASIS,
    chain_messages,
)
from schwab_client import build_client_from_token
from stream_spine import CaptureWriter, HealthRegistry, MessageBus, quote_msg
from tests.capture_store import store_capture
from tests.real_chains import CRWD, MRVL, NFLX
from tests.test_live_push_channel_v1 import listener, serve_page_socket

REPO = Path(__file__).resolve().parent.parent
#: Windows console input mode: selecting text with the mouse (SetConsoleMode)
QUICK_EDIT = 0x40
#: prints the input mode of the console window process `argv[1]` runs in, read from that window
WINDOW_MODE = (
    "import ctypes, sys\n"
    "k = ctypes.windll.kernel32\n"
    "k.CreateFileW.restype = ctypes.c_void_p\n"
    "k.FreeConsole()\n"
    "assert k.AttachConsole(int(sys.argv[1])), 'no window to attach to'\n"
    "h = k.CreateFileW('CONIN$', 0xC0000000, 3, None, 3, 0, None)\n"
    "m = ctypes.c_uint32()\n"
    "assert k.GetConsoleMode(ctypes.c_void_p(h), ctypes.byref(m)), 'no console mode'\n"
    "sys.stdout.write(str(m.value))\n"
)


async def _until(cond, limit: float = 10.0) -> None:
    end = time_et.elapsed() + limit
    while not cond():
        assert time_et.elapsed() < end, "timed out"
        await asyncio.sleep(0.05)


def test_a_page_is_refused_while_the_program_serves_no_prices():
    """The program's web server answers the page's price socket (/ws) only while it serves prices.

    The program serves prices in live_ui.serve_live_ui: a page that comes before is refused, and
    its reconnect keeps its schedule, never served rows nobody produces.
    """

    async def go():
        sock, url = listener()
        web = capture._PagesServer(
            uvicorn.Config(server.app, **{**capture.PAGES, "lifespan": "off"})
        )
        serving = asyncio.create_task(web.serve(sockets=[sock]))
        try:
            with pytest.raises(InvalidStatus) as refused:
                async with connect(f"{url}/ws"):
                    pass
        finally:
            web.should_exit = True
            await serving
        return refused.value.response.status_code

    assert asyncio.run(asyncio.wait_for(go(), 30)) == 403


@pytest.mark.skipif(
    sys.platform != "win32", reason="the daemon's window is a Windows console window"
)
def test_the_daemons_window_closes_when_its_batch_ends(tmp_path):
    """The launcher's command for the daemon's window runs the batch in a window of its own.

    The command is launch.daemon_window. When the batch ends (the daemon stopped on request),
    the window's cmd ends too, so no empty window stays open.
    """
    window_pid = tmp_path / "window.pid"
    bat = tmp_path / "daemon.bat"
    bat.write_text(
        f'@"{sys.executable}" -c "import psutil; '
        "window = next(p for p in psutil.Process().parents() "
        "if p.name().lower() == 'cmd.exe'); "
        f"open(r'{window_pid}', 'w').write(str(window.pid))\"\r\n",
        encoding="utf-8",
    )
    subprocess.Popen(launch.daemon_window(bat), cwd=launch.ROOT)
    deadline = time_et.elapsed() + 60.0
    # the file exists from its open, before its write: the pid is in it once its digits are
    while not (window_pid.exists() and window_pid.read_text(encoding="utf-8").isdigit()):
        assert time_et.elapsed() < deadline, "the batch never ran"
        time.sleep(0.1)
    window = int(window_pid.read_text(encoding="utf-8"))
    deadline = time_et.elapsed() + 30.0
    while psutil.pid_exists(window) and time_et.elapsed() < deadline:
        time.sleep(0.1)
    still_open = psutil.pid_exists(window)
    if still_open:
        psutil.Process(window).kill()
    assert not still_open, "the daemon's window stayed open after its batch ended"


@pytest.mark.skipif(
    sys.platform != "win32", reason="the daemon's batch and its window are Windows'"
)
def test_the_stop_finds_and_ends_the_daemon_its_batch_started(tmp_path):
    """The real start_capture_daemon.bat in a folder of its own starts the real daemon.

    With launch.py and a virtual environment beside it, it starts the real daemon in its window
    (no Schwab token, ports of its own). The stop finds it by launch.DAEMON_START and ends it,
    exit 0, and the batch does not restart it. A batch line apart from DAEMON_START would read
    "not running", leaving it up. The daemon has an error output, its window, where an error
    while it loads shows (operator 2026-11-04: "i would rather run capture main on python
    instead of pythonw"; under pythonw it had none): induced, a sitecustomize notes it for each
    process by its id.
    """
    home = tmp_path / "checkout"
    home.mkdir()
    for name in ("launch.py", "start_capture_daemon.bat"):
        shutil.copy(launch.ROOT / name, home)
    venv.create(home / ".venv")
    notes = tmp_path / "error_output"
    notes.mkdir()
    probe = tmp_path / "site"
    probe.mkdir()
    (probe / "sitecustomize.py").write_text(
        "import os, sys\n"
        f"with open(os.path.join({str(notes)!r}, str(os.getpid())), 'w') as f:\n"
        "    f.write(str(sys.stderr is not None))\n",
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(probe), str(launch.ROOT), *site.getsitepackages()]),
        "ED_RUNTIME_ROOT": str(tmp_path),
        "SCHWAB_TOKEN_PATH": str(tmp_path / "missing_token.json"),
    }
    bat = home / "start_capture_daemon.bat"
    subprocess.Popen(launch.daemon_window(bat), cwd=home, env=env)
    try:
        end = time_et.elapsed() + 60
        while program_ports(tmp_path / "data" / "stream_capture.db") is None:
            assert time_et.elapsed() < end, "the batch's daemon never served its port"
            time.sleep(0.1)
        noted = [
            (notes / str(p.pid)).read_text(encoding="utf-8")
            for p in launch.running(launch.DAEMON_START, home)
            if (notes / str(p.pid)).exists()
        ]
        assert noted == ["True"], noted
        daemon = launch.running(launch.DAEMON_START, home)[0].pid
        window_mode = subprocess.run(
            [sys.executable, "-c", WINDOW_MODE, str(daemon)],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=30,
        )
        assert window_mode.returncode == 0, window_mode.stderr
        # selecting text holds only the window, written by a thread of its own, never the program:
        # the daemon log test of a window that holds its writes shows it
        assert int(window_mode.stdout) & QUICK_EDIT, "the operator can select text to read it"
        stopped = subprocess.run(
            [sys.executable, "launch.py", "stop"],
            cwd=home,
            env=env,
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert (stopped.returncode, stopped.stdout) == (0, "Ed Console: stopped\n"), stopped.stderr
        end = time_et.elapsed() + 8  # past the batch's 5 s restart wait
        while time_et.elapsed() < end:
            started = [
                p.pid
                for p in psutil.process_iter(["name", "cwd"])
                if p.info["name"] == "python.exe"
                and p.info["cwd"]
                and Path(p.info["cwd"]).resolve() == home.resolve()
            ]
            assert not started, f"the batch restarted a daemon stopped on request: {started}"
            time.sleep(0.2)
    finally:
        for p in psutil.process_iter(["cmdline"]):
            if str(home) in " ".join(p.info["cmdline"] or []):
                p.kill()


def test_the_stop_takes_only_this_checkouts_processes(tmp_path):
    """launch.stop finds the program by launch.running.

    Of two processes started the same way, the
    one started in this checkout's folder (as its batch is) is found, and the one started in
    another folder (another checkout's program, a test's) is not, so the stop never waits on it
    instead of this one. Induced test condition: two sleeping Pythons started by a script of this
    test's own.
    """
    start = ["-c", f"import time; time.sleep(60)  # {os.getpid()}-{uuid.uuid4().hex}"]
    ours, theirs = (
        subprocess.Popen([sys.executable, *start], cwd=cwd) for cwd in (launch.ROOT, tmp_path)
    )
    try:
        found: set = set()
        end = time_et.elapsed() + 10
        while ours.pid not in found and time_et.elapsed() < end:
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
    """A forced thread error ends the sweep's thread and run_chains, logged with its traceback.

    The sweep's client raises an error the sweep does not catch (one
    not an Exception), its thread ends, the daemon's log has it with its traceback, and
    run_chains ends with it, before any stop (run then ends the daemon).
    """

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


def test_a_market_follower_that_ends_on_an_error_carries_it_out():
    """Induced condition: SPY's 2026-09-22 same-day chain with one contract replaced by text.

    Text, not a contract, so reading the chain raises. follow_market ends on that error.
    """
    fixture = json.loads(
        (REPO / "tests" / "fixtures" / "real_spy_0dte_chain.json").read_text(encoding="utf-8")
    )
    contracts = [dict(c) for c in fixture["chain"]]
    contracts[0] = "not a contract"
    bus = MessageBus()
    daemon = capture.Daemon(bus, HealthRegistry(), ["SPY"])

    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(daemon.follow_market(stop))
        await asyncio.sleep(0)
        for topic, msg in chain_messages("SPY", contracts, time_et.now(), None, None):
            bus.publish(topic, msg)
        await asyncio.wait_for(task, timeout=10)

    with pytest.raises(AttributeError, match="get"):
        asyncio.run(go())


def test_a_contract_with_no_symbol_is_left_out_of_the_recorded_strikes():
    """Induced condition: SPY's 2026-09-22 same-day chain with one contract's symbol taken out.

    On the daemon's bus. The strike ladders the daemon records from hold every other contract
    and no blank symbol (rule 2: no symbol is no contract to stream or record), and
    follow_market keeps running.
    """
    fixture = json.loads(
        (REPO / "tests" / "fixtures" / "real_spy_0dte_chain.json").read_text(encoding="utf-8")
    )
    contracts = [dict(c) for c in fixture["chain"]]
    del contracts[0]["symbol"]
    bus = MessageBus()
    now = fixture["ts_utc"]
    daemon = capture.Daemon(bus, HealthRegistry(), ["SPY"], clock=lambda: now)

    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(daemon.follow_market(stop))
        await asyncio.sleep(0)
        for topic, msg in chain_messages("SPY", contracts, now, None, None):
            bus.publish(topic, msg)
        for _ in range(100):
            if "SPY" in daemon._ladders or task.done():
                break
            await asyncio.sleep(0.05)
        running = not task.done()
        stop.set()
        await asyncio.wait_for(task, timeout=10)
        return running

    assert asyncio.run(go())
    held = [
        s for _exp, _strikes, by in daemon._ladders["SPY"] for syms in by.values() for s in syms
    ]
    assert None not in held
    assert len(held) == len(contracts) - 1


def test_a_contract_with_no_side_is_left_out_of_the_option_rule_on_a_price():
    """Induced condition: SPY's 2026-09-22 same-day chain with one contract's putCall taken out.

    Captured 16:46 UTC, at that time, arriving before SPY has a price. When SPY's price comes
    the option rule orders the chain without it (rule 2: no side is no contract to stream), and
    follow_market keeps running.
    """
    fixture = json.loads(
        (REPO / "tests" / "fixtures" / "real_spy_0dte_chain.json").read_text(encoding="utf-8")
    )
    contracts = [dict(c) for c in fixture["chain"]]
    del contracts[0]["putCall"]
    no_side = contracts[0]["symbol"]
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
        for _ in range(100):
            if "SPY" in daemon._ranked:
                break
            await asyncio.sleep(0.05)
        running = not task.done()
        stop.set()
        await asyncio.wait_for(task, timeout=10)
        return running

    lmp._by_ticker.pop("SPY", None)
    try:
        assert asyncio.run(go())
        assert no_side not in daemon._ranked["SPY"]
        assert len(daemon._ranked["SPY"]) == len(contracts) - 1
    finally:
        lmp._by_ticker.pop("SPY", None)  # the plane row its price wrote
        lmp._fields_by_ticker.pop("SPY", None)


def test_a_plane_row_listener_that_fails_ends_the_market_follower():
    """Induced condition: a row listener that raises, added through the plane's own listener API.

    Added through add_row_listener. SPY's price (its 2026-09-22 capture's) reaches the plane:
    follow_market ends on the listener's error instead of the plane swallowing it.
    """
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
    """The daemon's one client, built by the real builder from a token file that does not exist.

    The connection fails; the daemon's log has why, with its traceback, and its heartbeat, taken
    from the daemon's price socket as the console takes it, gives /api/health the same words with
    since when.
    """
    schwab_client = capture.one_schwab_client(
        lambda: build_client_from_token(
            str(tmp_path / "missing_token.json"), "LiveLookingKey", "LiveLookingSecret"
        )
    )
    bus = MessageBus()
    daemon = capture.Daemon(bus, HealthRegistry(), ["SPY"])
    sock, url = listener()

    async def go():
        stop = asyncio.Event()
        ui = asyncio.create_task(serve_page_socket(stop, sock, {"heartbeat_fn": daemon.status}))
        run = asyncio.create_task(daemon.run(schwab_client, stop))
        await _until(
            lambda: daemon.status(time_et.now())["schwab_down"].startswith("NOT CONNECTED")
        )
        await asyncio.sleep(0.2)
        async with connect(f"{url}/ws", max_size=None) as ws:
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
    ended = next(r for r in caplog.records if r.getMessage().startswith("schwab: connection ended"))
    assert ended.exc_info is not None and ended.exc_info[0] is ConnectionError, ended.exc_info
    lmp.record_feed_heartbeat(feed)
    reason = server.health()["capabilities"]["schwab_reason"]
    assert re.fullmatch(
        r"NOT CONNECTED since \w{3} \d\d/\d\d \d\d:\d\d [AP]M CT: "
        r"ConnectionError: no Schwab client \(Token file not found.*",
        reason,
        re.S,
    ), reason


def test_a_browser_that_stopped_reading_is_dropped_others_keep_beats_and_the_stop_is_not_held(
    caplog,
):
    """The daemon's price socket and two real browser sockets, one of which stops reading.

    The price socket is serve_live_ui, its heartbeat the daemon's own status, at /ws on the
    program's web server. Of the two real browser sockets, one reads every frame, one stops
    reading once its one-message queue is full. The one that stopped reading is found once (its
    buffers full for HEARTBEAT_SEC, so its beat is not taken), dropped (its connection aborted by
    live_ui.PageSocket: a close frame cannot be written to a browser that does not read), and its
    handler ends; the reading browser takes each of the next four beats in time (no other beat
    fails); the daemon's stop ends the server with no error. Induced test condition: each beat
    carries a 2 MB pad, so the stalled socket's buffers fill in seconds (the real status, a few
    KB, takes far longer).
    """
    daemon = capture.Daemon(MessageBus(), HealthRegistry(), ["SPY"])

    async def go():
        stop = asyncio.Event()
        stats: dict = {}
        sock, url = listener()
        daemon_side = asyncio.create_task(
            serve_page_socket(
                stop,
                sock,
                {
                    "heartbeat_fn": lambda now: {**daemon.status(now), "pad": "x" * 2_000_000},
                    "stats": stats,
                },
            )
        )
        beats: list[float] = []
        async with (
            connect(f"{url}/ws", max_size=None) as reading,
            connect(f"{url}/ws", max_queue=1, max_size=None, close_timeout=1),
        ):

            async def read_all():
                async for frame in reading:
                    if json.loads(frame)["type"] == "feed":
                        beats.append(time_et.elapsed())

            reader = asyncio.create_task(read_all())
            await _until(lambda: stats.get("clients") == 2, 3)
            await _until(lambda: stats.get("clients") == 1, 15)  # the stalled one dropped
            dropped_at, at_drop = time_et.elapsed(), stats["beat_send_failures"]
            await _until(
                lambda: sum(t > dropped_at for t in beats) >= 4, 10 * live_ui.HEARTBEAT_SEC
            )
            missed = stats["beat_send_failures"] - at_drop
            stop.set()
            await asyncio.wait_for(daemon_side, 5)
            reader.cancel()
        return at_drop, missed

    at_drop, missed = asyncio.run(asyncio.wait_for(go(), 40))
    # the stalled page's beat that was waiting when it was dropped, if one was, ended with it
    assert at_drop <= 1, f"{at_drop} beats failed before the stalled page was dropped"
    assert missed == 0, f"the reading browser missed {missed} beats"
    dropped = [r.getMessage() for r in caplog.records if "stopped reading" in r.getMessage()]
    assert dropped == ["live ui: a page stopped reading (a beat unread); dropping it"], dropped


def _end(process: subprocess.Popen) -> None:
    if process.poll() is None:
        for child in psutil.Process(process.pid).children(recursive=True):
            child.kill()
    process.kill()
    process.wait(30)


def test_the_stop_ends_the_real_daemon_and_says_when_it_could_not_ask(tmp_path):
    """The real daemon as its batch runs it, in a folder of its own with launch.py beside it.

    So the stop reaches nothing else; no Schwab token, ports the system picks as it binds them.
    Another checkout's stop leaves it alone. A stop from a runtime where no program made its stop
    request (no lock, or a lock whose holder has ended), so another runtime's, cannot ask it: it
    says so and that the daemon is still running, exit 1. A page on the daemon's own pages' port,
    /ws, is answered with what it subscribed to and takes the daemon's beat; a stop in the
    daemon's runtime, that page connected, ends the daemon and the page's socket with it, exit 0.
    Induced test condition: the runtime folders a stop reads, of the test's own.
    """
    home, other = tmp_path / "checkout", tmp_path / "other_checkout"
    for folder in (home, other):
        folder.mkdir()
        shutil.copy(launch.ROOT / "launch.py", folder)
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait(30)
    env = {
        **os.environ,
        "PYTHONPATH": str(launch.ROOT),
        "ED_RUNTIME_ROOT": str(tmp_path),
        "SCHWAB_TOKEN_PATH": str(tmp_path / "missing_token.json"),
    }
    daemon = subprocess.Popen([sys.executable, *launch.DAEMON_START], cwd=home, env=env)

    def stop(folder: Path, runtime: Path = tmp_path) -> subprocess.Popen:
        return subprocess.Popen(
            [sys.executable, "launch.py", "stop"],
            cwd=folder,
            env={**env, "ED_RUNTIME_ROOT": str(runtime)},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def runtime_holding(lock: str | None) -> Path:
        """Make a runtime folder of its own holding `lock` as its lock (None: no lock)."""
        runtime = tmp_path / f"runtime_{uuid.uuid4().hex}"
        (runtime / "data").mkdir(parents=True)
        if lock is not None:
            (runtime / "data" / "stream_capture.lock").write_text(lock, encoding="utf-8")
        return runtime

    try:
        end = time_et.elapsed() + 60
        while program_ports(tmp_path / "data" / "stream_capture.db") is None:
            assert daemon.poll() is None and time_et.elapsed() < end, daemon.poll()
            time.sleep(0.1)
        elsewhere = stop(other)
        out, err = elsewhere.communicate(timeout=60)
        assert (elsewhere.returncode, out) == (0, "Ed Console: not running\n"), err
        assert daemon.poll() is None
        ended_holder = f"{gone.pid}\n{json.dumps(asdict(Ports(console=1)))}\n"
        not_asked = [stop(home, runtime_holding(lock)) for lock in (None, ended_holder)]
        for p in not_asked:
            out, err = p.communicate(timeout=90)
            assert p.returncode == 1, (out, err)
            assert "Ed Console: not asked to stop: " in err
            assert "Ed Console: still running (" in out
        console = program_ports(tmp_path / "data" / "stream_capture.db").console

        async def page_through_the_stop():
            # unread frames queue without bound, so the page still reads the program's close
            async with connect(f"ws://127.0.0.1:{console}/ws", max_queue=None) as page:
                await page.send(json.dumps({"op": "subscribe", "symbols": ["spy"]}))
                frames = [json.loads(await asyncio.wait_for(page.recv(), 30))]
                while frames[-1]["type"] != "feed":
                    frames.append(json.loads(await asyncio.wait_for(page.recv(), 30)))
                stopping = stop(home)
                await asyncio.wait_for(page.wait_closed(), 60)
            return frames, stopping

        frames, stopping = asyncio.run(page_through_the_stop())
        assert frames[0] == {
            "type": "symbols",
            "symbols": [{"requested": "spy", "key": "SPY", "display": "SPY"}],
        }, frames
        assert frames[-1]["feed"]["schwab_socket_open"] is False  # no token: Schwab not reached
        assert daemon.wait(60) == capture.EXIT_STOPPED  # reaped: the stop sees it gone on Linux too
        out, err = stopping.communicate(timeout=60)
        assert (stopping.returncode, out) == (0, "Ed Console: stopped\n"), err
    finally:
        _end(daemon)


def test_the_stop_reads_no_process_parent(tmp_path):
    """A stop in a checkout where nothing runs answers at once.

    It does so though reading a process's parent is slow, as psutil's is on Windows (one
    snapshot of every process per parent): the scan asks no parent. Induced test condition: each
    parent read held for 1 s.
    """
    home, slow = tmp_path / "checkout", tmp_path / "slow"
    for folder in (home, slow):
        folder.mkdir()
    shutil.copy(launch.ROOT / "launch.py", home)
    (slow / "sitecustomize.py").write_text(
        "import time\n\nimport psutil\n\nplatform = psutil._psplatform.Process\n"
        "read = platform.ppid\nplatform.ppid = lambda self: time.sleep(1) or read(self)\n",
        encoding="utf-8",
    )
    stopping = subprocess.run(
        [sys.executable, "launch.py", "stop"],
        cwd=home,
        env={**os.environ, "PYTHONPATH": os.pathsep.join((str(slow), str(launch.ROOT)))},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert (stopping.returncode, stopping.stdout) == (0, "Ed Console: not running\n"), (
        stopping.stderr
    )


def test_a_daemon_that_ends_without_being_asked_is_not_reported_stopped(tmp_path):
    """The real daemon found while it loads, its stop request not made yet, then ending on its own.

    It ends because its pages' port is held, the code its window restarts on: the stop could not ask
    it, so it does not read "stopped" and exits 1. Induced test condition: the daemon's load is
    held until the stop has found it and said it could not ask it, however late the stop starts.
    """
    home, site = tmp_path / "checkout", tmp_path / "site"
    for folder in (home, site):
        folder.mkdir()
    shutil.copy(launch.ROOT / "launch.py", home)
    asked = tmp_path / "the stop asked"
    (site / "sitecustomize.py").write_text(
        "import pathlib, sys, time\n"
        'if "-m" in sys.orig_argv:\n'
        f"    while not pathlib.Path({str(asked)!r}).exists():\n"
        "        time.sleep(0.05)\n",
        encoding="utf-8",
    )
    with socket.create_server((live_ui.CONSOLE_HOST, 0)) as held:  # where the daemon binds
        env = {
            **os.environ,
            "PYTHONPATH": str(launch.ROOT),
            "ED_RUNTIME_ROOT": str(tmp_path),
            "ED_CONSOLE_PORT": str(held.getsockname()[1]),
            "SCHWAB_TOKEN_PATH": str(tmp_path / "missing_token.json"),
        }
        loading = {**env, "PYTHONPATH": os.pathsep.join((str(site), str(launch.ROOT)))}
        daemon = subprocess.Popen([sys.executable, *launch.DAEMON_START], cwd=home, env=loading)
        try:
            stopping = subprocess.Popen(
                [sys.executable, "launch.py", "stop"],
                cwd=home,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            said: list[str] = []

            def take_the_answer():
                # the stop found the daemon and could not ask it (no stop request yet): the
                # daemon's load goes on
                for line in stopping.stderr:
                    said.append(line)
                    if "Ed Console: not asked to stop: " in line:
                        asked.write_text("", encoding="utf-8")

            reader = threading.Thread(target=take_the_answer, daemon=True)
            reader.start()
            assert daemon.wait(60) == 1  # reaped: the stop sees it gone on Linux too
            out = stopping.stdout.read()
            stopping.wait(60)
            reader.join(60)
            err = "".join(said)
        finally:
            _end(daemon)
    assert stopping.returncode == 1, (out, err)
    assert "Ed Console: not asked to stop: " in err
    assert "Ed Console: ended, not asked by this stop\n" in out


def test_a_process_that_only_names_the_console_is_not_the_console():
    """A shell and Pythons in the checkout that name the program are not taken for it.

    They name it (Ed Console, capture_main) in their text or as an argument of their own, as a
    process search does.
    """
    named = launch.DAEMON_START[-1]
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
            [sys.executable, "-c", sleep, *launch.DAEMON_START],
        )
    ]
    try:
        end = time_et.elapsed() + 10
        for p in searches:
            while time_et.elapsed() < end and named not in " ".join(
                psutil.Process(p.pid).cmdline()
            ):
                time.sleep(0.05)
            assert named in " ".join(psutil.Process(p.pid).cmdline())
        found = {p.pid for p in launch.running(launch.DAEMON_START)}
        assert not found & {p.pid for p in searches}
    finally:
        for p in searches:
            _end(p)


def test_a_module_that_fails_to_load_shows_its_reason_in_the_daemons_window(tmp_path):
    """The daemon run as its window runs it (`python`), with schwab-py missing.

    Its error output, the window, has why, and it exits 1, which the window restarts on.
    """
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
    done = subprocess.run(
        [sys.executable, "-m", "app.market_data.schwab.streaming.capture_main"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert done.returncode == 1
    assert "ModuleNotFoundError: No module named 'schwab'" in done.stderr, done.stderr


def test_a_daemon_whose_pages_port_is_held_ends_at_once_with_why_and_its_window_restarts_it(
    tmp_path,
):
    """Another socket holds the pages' port (the page's price socket's too).

    The daemon, run as
    its window runs it, ends as it opens its sockets, with the bind's error naming the port in its
    log and an exit code its window restarts on (not EXIT_STOPPED), instead of running with no
    browser served.
    """
    with socket.create_server((live_ui.CONSOLE_HOST, 0)) as held:  # where the daemon binds
        port = held.getsockname()[1]
        env = {
            **os.environ,
            "ED_RUNTIME_ROOT": str(tmp_path),
            "ED_CONSOLE_PORT": str(port),
            "SCHWAB_TOKEN_PATH": str(tmp_path / "missing_token.json"),
        }
        done = subprocess.run(
            [sys.executable, "-m", "app.market_data.schwab.streaming.capture_main"],
            cwd=REPO,
            env=env,
            capture_output=True,
            timeout=60,
        )
    (path,) = (tmp_path / "logs").glob("stream_capture.*.log")
    log = path.read_text(encoding="utf-8")
    assert done.returncode == 1, (done.returncode, log)
    assert "capture daemon: ended by an error" in log, log
    assert f"({live_ui.CONSOLE_HOST!r}, {port})" in log, log  # the bind names its address
    assert "OSError" in log, log


def test_the_stored_levels_are_priced_while_a_page_on_another_ticker_takes_ticks():
    """At a console start, stored captures are priced while a page views a streamed ticker.

    The stored captures of the tickers the daemon has not delivered yet are priced while a page
    views a ticker whose options stream. Through the real code, on Schwab's
    captures (tests/real_chains.py): CRWD's chain delivered and priced, a page open on it
    (push_changes); MRVL's and NFLX's captures stored as the daemon writes them (one row per
    expiry, at each capture's time) and queued by the startup load. Induced test condition: one
    of CRWD's contracts ticks back to back (_on_stream_tick, a reprice on each), so a tick lands
    during every pricing. Both stored captures are priced within 10 s, and CRWD is repriced
    meanwhile.
    """
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
            server._on_stream_tick(contracts[0]["symbol"], CRWD.now.timestamp())
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
            deadline = time_et.elapsed() + 10
            while priced() != set(names) and time_et.elapsed() < deadline:
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
    """No database backups are kept (operator 2026-10-10).

    A path under backups/db/ is no class of its own. The console's database (db.EdDB) refuses it
    as it refuses every path but the canonical one, named unknown.
    """
    with pytest.raises(ValueError, match=r"classification=unknown"):
        db.EdDB(tmp_path / "backups" / "db" / "ed_console.db", allow_noncanonical=False)


def test_the_console_database_starts_without_the_former_ticker_board(tmp_path):
    """One watchlist, kept by the daemon (#486).

    The console's database (db.EdDB) creates only the level crosses at its start, never the
    former ticker board's logging_universe.
    """
    path = tmp_path / "ed_console.db"
    db.EdDB(path, allow_noncanonical=True)
    with sqlite3.connect(path) as conn:
        tables = {
            name for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert "level_crosses" in tables
    assert "logging_universe" not in tables, "the console still creates the former ticker board"
