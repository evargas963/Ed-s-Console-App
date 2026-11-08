"""Ed Console's launcher: start_ed_console.bat runs it with the project's .venv Python. Ed Console
is one program (capture_main): the Schwab connection, the recording and the console's pages. Its
start stops nothing.

0. With it not running, the checkout brought to origin/main (bring_to_origin_main), so it starts
   from the newest merged commit: moved, it runs the new launch.py as its child and ends with it.
   With local changes, not on main, split from origin/main or origin out of reach, it starts from
   the commit the checkout is at, the check not passed and why said: whether the app starts is
   never the repository's to decide. Running, the check is not run.
1. The program, in its own window (start_capture_daemon.bat restarts it). It reads its own .env
   (the Schwab credentials); its log, and /api/health from its heartbeat, say whether Schwab took
   them.
2. The default browser, at URL, once the program's pages answer healthy (START_WAIT_SEC).

`python launch.py stop` is the clean stop (stop): the program is asked to stop on its local socket
and writes what it holds before it exits.
"""

from __future__ import annotations

import json
import logging
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

import psutil
from websockets.exceptions import WebSocketException
from websockets.sync.client import connect

import time_et
from app.market_data.schwab.streaming.live_push import LIVE_PUSH_PORT
from app.market_data.schwab.streaming.live_ui import CONSOLE_PORT
from app.market_data.schwab.streaming.live_ui import LIVE_UI_PORT as DAEMON_PORT

log = logging.getLogger("launch")
ROOT = Path(__file__).resolve().parent
URL = f"http://127.0.0.1:{CONSOLE_PORT}/"
#: what the program runs right after Python (start_capture_daemon.bat's line)
DAEMON_START = ["-m", "app.market_data.schwab.streaming.capture_main"]
#: how long a clean stop waits for the program to end
STOP_WAIT_SEC = 30.0
#: what the commit check before a start found (bring_to_origin_main)
COMMIT_CURRENT, COMMIT_MOVED, COMMIT_UNKNOWN, COMMIT_REFUSED = (
    "current",
    "moved",
    "unknown",
    "refused",
)


def bring_to_origin_main(root: Path) -> tuple[str, str | None, str]:
    """The checkout at `root` brought to origin/main: (what the check found, the commit it is at,
    None when git could not say, why). It fetches origin and fast-forwards main. COMMIT_CURRENT:
    at origin/main. COMMIT_MOVED: fast-forwarded. COMMIT_UNKNOWN: origin out of reach, or git
    itself not answering (absent, hung);
    COMMIT_REFUSED: not on main, local changes, or a history split from origin/main; nothing is
    moved."""
    try:
        return _bring(root)
    except (OSError, subprocess.SubprocessError) as e:
        return COMMIT_UNKNOWN, None, f"git did not answer: {type(e).__name__}: {e}"


def _bring(root: Path) -> tuple[str, str, str]:
    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=60)

    head = git("rev-parse", "HEAD").stdout.strip()
    fetched = git("fetch", "--quiet", "origin", "main")
    if fetched.returncode != 0:
        return COMMIT_UNKNOWN, head, f"origin could not be fetched: {fetched.stderr.strip()}"
    if git("symbolic-ref", "--short", "-q", "HEAD").stdout.strip() != "main":
        return COMMIT_REFUSED, head, "the checkout is not on main"
    changed = git("status", "--porcelain", "--untracked-files=no").stdout.strip()
    if changed:
        return COMMIT_REFUSED, head, f"local changes: {changed}"
    merged = git("merge", "--ff-only", "--quiet", "origin/main")
    if merged.returncode != 0:
        return (
            COMMIT_REFUSED,
            head,
            f"main cannot fast-forward to origin/main: {merged.stderr.strip()}",
        )
    now = git("rev-parse", "HEAD").stdout.strip()
    return (
        (COMMIT_CURRENT, now, "at origin/main")
        if now == head
        else (COMMIT_MOVED, now, f"fast-forwarded from {head}")
    )


def in_use(port: int) -> bool:
    """Whether a process on this machine listens on `port`: it takes a connection on 127.0.0.1."""
    with socket.socket() as probe:
        probe.settimeout(2.0)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def running(start: list[str], root: Path = ROOT) -> list[psutil.Process]:
    """Return the checkout's processes that run `start` right after their program.

    Those whose folder is `root` (this checkout, ROOT, unless a test names another), where its
    daemon's batch and its console run, so another checkout's daemon or console (a test's) is
    never taken for one, nor a process that only names them, as a search does (one whose line or
    folder cannot be read is none).
    """
    return [
        p
        for p in psutil.process_iter(["cmdline", "cwd"])
        if p.info["cmdline"] is not None
        and p.info["cmdline"][1 : len(start) + 1] == start
        and p.info["cwd"] is not None
        and Path(p.info["cwd"]).resolve() == root.resolve()
    ]


def daemon_window(batch: Path) -> list[str]:
    """The command that runs `batch` (start_capture_daemon.bat) in a minimized window of its own
    titled "Ed Capture Daemon", under `cmd /c` so the window closes when the batch ends (`start`
    given a batch file runs it under `cmd /K`, which keeps the window open)."""
    return ["cmd", "/c", "start", "Ed Capture Daemon", "/min", "cmd", "/c", str(batch)]


def ask_daemon_to_stop(port: int = LIVE_PUSH_PORT) -> None:
    """The daemon's clean stop, asked on its local socket at `port` ({"op": "stop"}: it writes
    what it holds, then exits and start_capture_daemon.bat does not restart it)."""
    with connect(f"ws://127.0.0.1:{port}", open_timeout=10) as ws:
        ws.send(json.dumps({"op": "stop"}))


def stop() -> int:
    """The clean stop of the program (ask_daemon_to_stop): the Schwab connection, the recording
    and the console's pages end together. Waits up to STOP_WAIT_SEC; 0 when it ended after being
    asked: one that ended when this stop could not ask it is not reported stopped."""
    program = running(DAEMON_START)
    ended = "stopped"
    if program:
        try:
            ask_daemon_to_stop()
        except (OSError, WebSocketException) as e:
            log.warning("Ed Console: not asked to stop: %s: %s", type(e).__name__, e)
            ended = "ended, not asked by this stop"
    _gone, alive = psutil.wait_procs(program, timeout=STOP_WAIT_SEC)
    left = [p.pid for p in program if p in alive]
    print(
        "Ed Console: "
        + ("not running" if not program else f"still running ({left})" if left else ended)
    )
    return 1 if alive or ended != "stopped" else 0


def unhealthy_for(port: int, seconds: float) -> str | None:
    """None once the console on `port` answers /api/health with 200 within `seconds`; else the
    last answer it gave instead (an error status, a refused connection, a timeout)."""
    deadline = time_et.elapsed() + seconds
    why = f"no answer in {seconds:.0f} s"
    while (left := deadline - time_et.elapsed()) > 0:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/health", timeout=min(left, 2.0)
            ) as r:
                if r.status == 200:
                    return None
                why = f"HTTP {r.status}"
        except OSError as e:
            why = f"{type(e).__name__}: {e}"
        time.sleep(min(0.25, max(deadline - time_et.elapsed(), 0)))
    return why


#: how long the launcher waits for the program's pages to answer before it says they did not
START_WAIT_SEC = 180.0


def main() -> int:
    if in_use(DAEMON_PORT) or in_use(CONSOLE_PORT):
        print("Commit check: not run; Ed Console already runs from this checkout.")
    else:
        check, commit, why = bring_to_origin_main(ROOT)
        print(f"Commit check: {check}: {why}")
        if commit is not None:
            print(f"Commit: {commit}")
        if check == COMMIT_MOVED:  # this process loaded the old code: the new one starts it
            return subprocess.call([sys.executable, str(ROOT / "launch.py")], cwd=ROOT)
        subprocess.Popen(daemon_window(ROOT / "start_capture_daemon.bat"), cwd=ROOT)
        print('Ed Console: started in its own window ("Ed Capture Daemon").')
    started = time_et.elapsed()
    why = unhealthy_for(CONSOLE_PORT, START_WAIT_SEC)
    if why is not None:
        print(f"Ed Console: its pages did not answer in {START_WAIT_SEC:.0f} s: {why}")
        return 1
    print(f"Ed Console: healthy {time_et.elapsed() - started:.1f} s after the start.")
    webbrowser.open(URL)  # the default browser
    return 0


if __name__ == "__main__":
    raise SystemExit(stop() if sys.argv[1:] == ["stop"] else main())
