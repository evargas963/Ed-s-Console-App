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

REPO = Path(__file__).resolve().parent.parent


def free_ports(n: int) -> list[int]:
    held = [socket.socket() for _ in range(n)]
    for s in held:
        s.bind(("127.0.0.1", 0))
    ports = [s.getsockname()[1] for s in held]
    for s in held:
        s.close()
    return ports


def program_env(tmp_path: Path) -> tuple[dict, int]:
    """The program's environment on ports of its own, and its pages' port."""
    push, ui, pages = free_ports(3)
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}  # its loops start
    env.update(
        ED_RUNTIME_ROOT=str(tmp_path),
        ED_ARTIFACTS_ROOT=str(tmp_path / "artifacts"),
        ED_LIVE_UI_HOST="127.0.0.1",
        ED_LIVE_PUSH_PORT=str(push),
        ED_LIVE_UI_PORT=str(ui),
        ED_CONSOLE_PORT=str(pages),
        SCHWAB_TOKEN_PATH=str(tmp_path / "missing_schwab_token.json"),
        PYTHONIOENCODING="utf-8",
    )
    return env, pages


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
    env, pages = program_env(tmp_path)
    program = subprocess.Popen(
        [sys.executable, *launch.DAEMON_START],
        cwd=REPO,
        env=env,
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
        while "Live-plane feed started" not in "".join(list(lines)):
            assert program.poll() is None and time_et.elapsed() < end, "".join(lines)
            time.sleep(0.25)
        assert launch.unhealthy_for(pages, 30) is None  # a page request, as the browser makes
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


def test_the_console_says_what_it_waits_for_and_for_how_long(tmp_path):
    """In one program the daemon's heartbeat, with the watchlist, is there before the console's
    loop starts: the console says what it needed and that it had it, in well under a second."""
    env, _pages = program_env(tmp_path)
    over = "done waiting for the capture daemon's heartbeat (it says what the watchlist is) after"
    fed = "Live-plane feed started (source=the capture daemon's bus, this program)"
    text = run_until(env, lambda t: over in t and fed in t)
    assert "stored bars" not in text, "nothing is loaded from a database at the start"
    after = float(re.search(re.escape(over) + r" ([\d.]+) s", text).group(1))
    assert after < 1.0, text
    assert "no capture daemon runs in this program" not in text, "the console found its daemon"
