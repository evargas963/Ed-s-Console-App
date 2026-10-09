"""Ed Console's launcher: start_ed_console.bat runs it with the project's .venv Python. Its start
stops nothing.

1. The capture daemon, in its own window (start_capture_daemon.bat restarts it), unless its price
   socket's port is in use. It reads its own .env (the Schwab credentials); its log, and
   /api/health from its heartbeat, say whether Schwab took them.
2. The console on port 8000, with no SCHWAB_* setting (it never calls Schwab), unless the port is
   in use: then it says so and opens the browser to it.
3. The default browser, at URL, once the console it started answers healthy.

`python launch.py stop` is the clean stop of both (stop): the daemon is asked to stop on its local
socket and writes what it holds before it exits; the console gets Ctrl+C on its own console window
and runs its shutdown.
"""
from __future__ import annotations

import ctypes
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

import psutil
from websockets.sync.client import connect

from app.market_data.schwab.streaming.live_push import LIVE_PUSH_PORT
from app.market_data.schwab.streaming.live_ui import LIVE_UI_PORT as DAEMON_PORT

ROOT = Path(__file__).resolve().parent
CONSOLE_PORT = 8000
URL = f"http://127.0.0.1:{CONSOLE_PORT}/"
#: --timeout-graceful-shutdown: Ctrl+C ends it while pages hold their change streams open
CONSOLE = [sys.executable, "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", str(CONSOLE_PORT),
           "--timeout-graceful-shutdown", "10"]
#: what each process's command line carries: the daemon's module, the console's app
DAEMON_MARK, CONSOLE_MARK = "streaming.capture", "server:app"
#: how long a clean stop waits for each process to end (the console's shutdown is bounded at 12 s)
STOP_WAIT_SEC = 30.0


def in_use(port: int) -> bool:
    """Whether a process on this machine listens on `port`: it takes a connection on 127.0.0.1."""
    with socket.socket() as probe:
        probe.settimeout(2.0)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def running(mark: str) -> "list[psutil.Process]":
    """The processes whose command line carries `mark`."""
    return [p for p in psutil.process_iter(["cmdline"]) if mark in " ".join(p.info["cmdline"] or ())]


def ctrl_c(pid: int) -> None:
    """Ctrl+C on the console window of process `pid`, from a process without a window of its own,
    as the operator's key press there: every process on that window gets it."""
    subprocess.run([sys.executable, str(Path(__file__)), "ctrl-c", str(pid)],
                   creationflags=subprocess.CREATE_NO_WINDOW, check=True, timeout=30)


def _send_ctrl_c(pid: int) -> int:
    kernel = ctypes.windll.kernel32
    kernel.FreeConsole()
    if not kernel.AttachConsole(pid):
        return 1
    kernel.SetConsoleCtrlHandler(None, True)        # this process ignores the Ctrl+C it sends
    return 0 if kernel.GenerateConsoleCtrlEvent(0, 0) else 1


def ask_daemon_to_stop(port: int = LIVE_PUSH_PORT) -> None:
    """The daemon's clean stop, asked on its local socket at `port` ({"op": "stop"}: it writes
    what it holds, then exits and start_capture_daemon.bat does not restart it)."""
    with connect(f"ws://127.0.0.1:{port}", open_timeout=10) as ws:
        ws.send(json.dumps({"op": "stop"}))


def stop() -> int:
    """The clean stop of the daemon (ask_daemon_to_stop) and the console (Ctrl+C on its window:
    server._install_signal_handlers, then its shutdown). Waits up to STOP_WAIT_SEC for each; 0
    when both ended."""
    daemon, console = running(DAEMON_MARK), running(CONSOLE_MARK)
    if daemon:
        ask_daemon_to_stop()
    if console:
        ctrl_c(console[0].pid)
    _gone, alive = psutil.wait_procs(daemon + console, timeout=STOP_WAIT_SEC)
    for name, procs in (("Capture daemon", daemon), ("Console", console)):
        left = [p.pid for p in procs if p in alive]
        print(f"{name}: " + ("not running" if not procs else f"still running ({left})" if left else "stopped"))
    return 1 if alive else 0


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
    if sys.argv[1:] == ["stop"]:
        raise SystemExit(stop())
    if sys.argv[1:2] == ["ctrl-c"]:
        raise SystemExit(_send_ctrl_c(int(sys.argv[2])))
    raise SystemExit(main())
