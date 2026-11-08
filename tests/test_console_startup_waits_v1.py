"""The program's start, as its window shows it: the console says what it waits for (the daemon's
heartbeat, which says what the watchlist is) and for how long, then that the wait is over. The
real program (capture_main: the daemon and the console's pages in one process) on ports of its own,
with no Schwab token (Schwab is not reached)."""

from __future__ import annotations

import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import launch
import time_et
from app.market_data.schwab.streaming import capture
from app.market_data.schwab.streaming.program_lock import Ports, program_ports

REPO = Path(__file__).resolve().parent.parent


def held_ports(tmp_path: Path) -> Ports | None:
    """Return the ports the program wrote in its lock, as launch.py reads them."""
    return program_ports(tmp_path / "data" / "stream_capture.db")


def answered(tmp_path: Path) -> Ports | TimeoutError:
    """Return the ports once the program's pages answer, as launch.py waits, or why they did not."""
    try:
        return launch.wait_for_pages(30, tmp_path / "data" / "stream_capture.db")
    except TimeoutError as e:
        return e


def program_env(tmp_path: Path) -> dict:
    """The program's environment on ports the system picks as it binds them (port 0), which the
    program writes in its lock (held_ports): a port found free and released before the program
    binds it can be taken in between, by any other program's outgoing connection among them."""
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}  # its loops start
    env.update(
        ED_RUNTIME_ROOT=str(tmp_path),
        ED_LIVE_UI_HOST="127.0.0.1",
        ED_LIVE_PUSH_PORT="0",
        ED_LIVE_UI_PORT="0",
        ED_CONSOLE_PORT="0",
        SCHWAB_TOKEN_PATH=str(tmp_path / "missing_schwab_token.json"),
        PYTHONIOENCODING="utf-8",
    )
    return env


def run_until(env: dict, done) -> str:
    """Run the program until `done(window text)` (120 s at most), then stop it: its window."""
    program = subprocess.Popen(
        [sys.executable, *launch.DAEMON_START],
        cwd=REPO,
        env=env,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    lines: list = []
    threading.Thread(target=lambda: lines.extend(program.stdout), daemon=True).start()
    try:
        end = time_et.elapsed() + 120
        while not done("".join(list(lines))):
            assert program.poll() is None and time_et.elapsed() < end, "".join(lines)
            time.sleep(0.25)
    finally:
        program.kill()
        program.wait(30)
    return "".join(lines)


def test_an_interrupt_in_the_window_is_the_programs_clean_stop(tmp_path):
    """Ctrl+C or Ctrl+Break in the program's window asks for its one clean stop, as
    `launch.py stop` does: it says so, writes what it holds, and exits EXIT_STOPPED, which its
    window does not restart. The real program in a process group of its own, sent Ctrl+Break on
    Windows (Windows sends a console event to another program's group as Ctrl+Break, not
    Ctrl+C; both take the same handler, capture.INTERRUPTS), Ctrl+C's SIGINT elsewhere."""
    windows = sys.platform == "win32"
    program = subprocess.Popen(
        [sys.executable, *launch.DAEMON_START],
        cwd=REPO,
        env=program_env(tmp_path),
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if windows else 0,
    )
    lines: list = []
    threading.Thread(target=lambda: lines.extend(program.stdout), daemon=True).start()
    try:
        end = time_et.elapsed() + 120
        while (ports := held_ports(tmp_path)) is None:
            assert program.poll() is None and time_et.elapsed() < end, "".join(lines)
            time.sleep(0.25)
        answer = answered(tmp_path)  # a page request, as the browser makes
        assert answer == ports, (answer, "".join(lines))
        os.kill(program.pid, signal.CTRL_BREAK_EVENT if windows else signal.SIGINT)
        code = program.wait(90)
    finally:
        if program.poll() is None:
            program.kill()
            program.wait(30)
    text = "".join(lines)
    assert "Ctrl+C: stopping cleanly" in text, text
    assert code == capture.EXIT_STOPPED, (code, text)
    assert '"GET /api/health' not in text, "a page request is not the window's"


def test_a_stop_with_a_page_open_ends_its_stream_and_does_not_wait_it_out(tmp_path):
    """A page open on the console (its /api/changes stream, as the browser holds it) when the
    program stops: the stop ends that stream itself, so the web server closes at once, not after
    its 10 s graceful timeout, and no stream is cancelled (each was logged as a traceback)."""
    windows = sys.platform == "win32"
    program = subprocess.Popen(
        [sys.executable, *launch.DAEMON_START],
        cwd=REPO,
        env=program_env(tmp_path),
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if windows else 0,
    )
    lines: list = []
    threading.Thread(target=lambda: lines.extend(program.stdout), daemon=True).start()
    page = socket.socket()
    try:
        end = time_et.elapsed() + 120
        while (ports := held_ports(tmp_path)) is None:
            assert program.poll() is None and time_et.elapsed() < end, "".join(lines)
            time.sleep(0.25)
        pages = ports.console
        answer = answered(tmp_path)
        assert answer == ports, (answer, "".join(lines))
        page.settimeout(30)
        page.connect(("127.0.0.1", pages))
        page.sendall(b"GET /api/changes?ticker=SPY HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
        got = b""
        while b"event: session" not in got:  # the page's stream is open: its first event
            chunk = page.recv(4096)
            assert chunk, got
            got += chunk
        asked = time_et.elapsed()
        os.kill(program.pid, signal.CTRL_BREAK_EVENT if windows else signal.SIGINT)
        code = program.wait(90)
        took = time_et.elapsed() - asked
    finally:
        page.close()
        if program.poll() is None:
            program.kill()
            program.wait(30)
    text = "".join(lines)
    assert code == capture.EXIT_STOPPED, (code, text)
    assert "timeout graceful shutdown exceeded" not in text, text
    assert took < 8.0, f"the stop took {took:.1f} s with a page open"


def test_the_console_says_what_it_waits_for_and_for_how_long(tmp_path):
    """In one program the daemon's heartbeat, with the watchlist, is there before the console's
    loop starts: the console says what it needed and that it had it, in well under a second."""
    env = program_env(tmp_path)
    over = "done waiting for the capture daemon's heartbeat (it says what the watchlist is) after"
    fed = "Live-plane feed started (source=the capture daemon's bus, this program)"
    text = run_until(env, lambda t: over in t and fed in t)
    assert "stored bars" not in text, "nothing is loaded from a database at the start"
    after = float(re.search(re.escape(over) + r" ([\d.]+) s", text).group(1))
    assert after < 1.0, text
    assert "no capture daemon runs in this program" not in text, "the console found its daemon"
