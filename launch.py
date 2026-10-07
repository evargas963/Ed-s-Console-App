"""Ed Console's launcher: start_ed_console.bat runs it with the project's .venv Python. It stops
nothing.

1. The capture daemon, in its own window (start_capture_daemon.bat restarts it), unless its price
   socket's port is in use. It reads its own .env (the Schwab credentials); its log, and
   /api/health from its heartbeat, say whether Schwab took them.
2. The console on port 8000, with no SCHWAB_* setting (it never calls Schwab), unless the port is
   in use: then it says so and opens the browser to it.
3. The default browser, at URL, once the console it started answers healthy.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

import psutil

from app.market_data.schwab.streaming.live_ui import LIVE_UI_PORT as DAEMON_PORT

ROOT = Path(__file__).resolve().parent
CONSOLE_PORT = 8000
URL = f"http://127.0.0.1:{CONSOLE_PORT}/"
#: --timeout-graceful-shutdown: Ctrl+C ends it while pages hold their change streams open
CONSOLE = [sys.executable, "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", str(CONSOLE_PORT),
           "--timeout-graceful-shutdown", "10"]


def in_use(port: int) -> bool:
    """Whether a process on this machine listens on `port`."""
    return any(c.status == psutil.CONN_LISTEN and c.laddr and c.laddr.port == port
               for c in psutil.net_connections(kind="inet"))


def unhealthy_for(port: int, seconds: float) -> "str | None":
    """None once the console on `port` answers /api/health with 200 within `seconds`; else the
    last answer it gave instead (an error status, a refused connection, a timeout)."""
    deadline = time.monotonic() + seconds
    why = f"no answer in {seconds:.0f} s"
    while (left := deadline - time.monotonic()) > 0:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=min(left, 2.0)) as r:
                if r.status == 200:
                    return None
                why = f"HTTP {r.status}"
        except OSError as e:
            why = f"{type(e).__name__}: {e}"
        time.sleep(min(0.25, max(deadline - time.monotonic(), 0)))
    return why


def main() -> int:
    if in_use(DAEMON_PORT):
        print(f"Capture daemon: port {DAEMON_PORT} is already in use; not started.")
    else:
        subprocess.Popen(["cmd", "/c", "start", "Ed Capture Daemon", "/min", str(ROOT / "start_capture_daemon.bat")],
                         cwd=ROOT)
        print('Capture daemon: started in its own window ("Ed Capture Daemon").')
    if in_use(CONSOLE_PORT):
        print(f"Console: port {CONSOLE_PORT} is already in use; not started. Opening {URL}.")
        webbrowser.open(URL)                       # the default browser
        return 0
    print(f"Console: starting on port {CONSOLE_PORT}; the browser opens at {URL} once it answers. Ctrl+C stops it.")
    console = subprocess.Popen(CONSOLE, cwd=ROOT,
                               env={k: v for k, v in os.environ.items() if not k.upper().startswith("SCHWAB_")})
    signal.signal(signal.SIGINT, signal.SIG_IGN)   # Ctrl+C is the console's: it stops, then this ends
    started = time.monotonic()
    while console.poll() is None and unhealthy_for(CONSOLE_PORT, 1.0) is not None:
        pass
    if console.poll() is None:
        print(f"Console: healthy {time.monotonic() - started:.1f} s after its start.")
        webbrowser.open(URL)
    return console.wait()


if __name__ == "__main__":
    raise SystemExit(main())
