"""Ed Console's launcher, the one start of the console and the capture daemon:
start_ed_console.bat runs it with the project's .venv Python. It stops nothing.

0. With neither running, the checkout brought to origin/main (bring_to_origin_main), so both start
   from the same commit, the newest merged: moved, it ends and start_ed_console.bat runs it again
   on the new code; with local changes, not on main or split from origin/main, nothing starts;
   with origin out of reach, both start, the check not passed. With either running it is not run:
   the other starts from the commit the running one loaded.
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
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

from app.market_data.schwab.streaming.live_ui import LIVE_UI_PORT as DAEMON_PORT

ROOT = Path(__file__).resolve().parent
CONSOLE_PORT = 8000
URL = f"http://127.0.0.1:{CONSOLE_PORT}/"
#: --timeout-graceful-shutdown: Ctrl+C ends it while pages hold their change streams open
CONSOLE = [sys.executable, "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", str(CONSOLE_PORT),
           "--timeout-graceful-shutdown", "10"]
#: what the commit check before a start found (bring_to_origin_main)
COMMIT_CURRENT, COMMIT_MOVED, COMMIT_UNKNOWN, COMMIT_REFUSED = "current", "moved", "unknown", "refused"
#: exit codes start_ed_console.bat acts on: the checkout moved (it runs this again, on the new
#: code); the checkout cannot be brought to origin/main (nothing started)
EXIT_MOVED, EXIT_NOT_CURRENT = 10, 11


def bring_to_origin_main(root: Path) -> "tuple[str, str, str]":
    """The checkout at `root` brought to origin/main: (what the check found, the commit it is at,
    why). It fetches origin and fast-forwards main. COMMIT_CURRENT: at origin/main. COMMIT_MOVED:
    fast-forwarded. COMMIT_UNKNOWN: origin out of reach. COMMIT_REFUSED: not on main, local
    changes, or a history split from origin/main; nothing is moved."""
    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=60)
    head = git("rev-parse", "HEAD").stdout.strip()
    try:
        fetched = git("fetch", "--quiet", "origin", "main")
    except subprocess.TimeoutExpired as e:
        return COMMIT_UNKNOWN, head, f"origin did not answer: {e}"
    if fetched.returncode != 0:
        return COMMIT_UNKNOWN, head, f"origin could not be fetched: {fetched.stderr.strip()}"
    if git("symbolic-ref", "--short", "-q", "HEAD").stdout.strip() != "main":
        return COMMIT_REFUSED, head, "the checkout is not on main"
    changed = git("status", "--porcelain", "--untracked-files=no").stdout.strip()
    if changed:
        return COMMIT_REFUSED, head, f"local changes: {changed}"
    merged = git("merge", "--ff-only", "--quiet", "origin/main")
    if merged.returncode != 0:
        return COMMIT_REFUSED, head, f"main cannot fast-forward to origin/main: {merged.stderr.strip()}"
    now = git("rev-parse", "HEAD").stdout.strip()
    return (COMMIT_CURRENT, now, "at origin/main") if now == head else (COMMIT_MOVED, now, f"fast-forwarded from {head}")


def in_use(port: int) -> bool:
    """Whether a process on this machine listens on `port`: it takes a connection on 127.0.0.1."""
    with socket.socket() as probe:
        probe.settimeout(2.0)
        return probe.connect_ex(("127.0.0.1", port)) == 0


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
    running = [name for name, port in (("capture daemon", DAEMON_PORT), ("console", CONSOLE_PORT)) if in_use(port)]
    if running:
        print(f"Commit check: not run; the {' and the '.join(running)} already run from this checkout.")
    else:
        check, commit, why = bring_to_origin_main(ROOT)
        print(f"Commit check: {check} at {commit}: {why}")
        if check == COMMIT_REFUSED:
            print("Not started: this checkout cannot be brought to origin/main.")
            return EXIT_NOT_CURRENT
        if check == COMMIT_MOVED:                  # this process loaded the old code
            return EXIT_MOVED
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
