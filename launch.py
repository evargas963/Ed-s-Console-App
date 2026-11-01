"""Ed Console's launcher, the one start of the program (program.py):
start_ed_console.bat runs it with the project's .venv Python. Its start stops nothing.

0. With it not running, the checkout brought to origin/main (bring_to_origin_main), so it starts
   from the newest merged commit: moved, it runs the new launch.py as its child and ends with it.
   With local changes, not on main, split from origin/main or origin out of reach, it starts from
   the commit the checkout is at, the check not passed and why said: whether the app starts is
   never the repository's to decide.
1. The program on port 8000, unless the port is in use: then it says so and opens the browser to
   it. It reads .env (the Schwab credentials); its log, and /api/health, say whether Schwab took
   them.
2. The default browser, at URL, once the program answers healthy.

`python launch.py stop` is the clean stop (stop): the program, in a process group of its own, gets
Ctrl+Break and runs its shutdown, the writer writing what it holds; start_ed_console.bat then ends
and its window closes.
"""

from __future__ import annotations

import ctypes
import logging
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

log = logging.getLogger("launch")
ROOT = Path(__file__).resolve().parent
CONSOLE_PORT = 8000
URL = f"http://127.0.0.1:{CONSOLE_PORT}/"
#: what it runs right after its Python
CONSOLE_START = ["-m", "uvicorn", "program:app"]
#: --timeout-graceful-shutdown: Ctrl+C ends it while pages hold their change streams open
CONSOLE = [
    sys.executable,
    *CONSOLE_START,
    "--host",
    "0.0.0.0",
    "--port",
    str(CONSOLE_PORT),
    "--timeout-graceful-shutdown",
    "10",
]
#: how long a clean stop waits for the program to end (its shutdown is bounded at 12 s)
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


def running(start: list[str]) -> list[psutil.Process]:
    """This checkout's processes that run `start` right after their program: those whose folder is
    ROOT, so another checkout's (a test's) is never taken for one, nor a process that only names
    it, as a search does (one whose line or folder cannot be read is none)."""
    return [
        p
        for p in psutil.process_iter(["cmdline", "cwd", "ppid"])
        if p.info["cmdline"] is not None
        and p.info["cmdline"][1 : len(start) + 1] == start
        and p.info["cwd"] is not None
        and Path(p.info["cwd"]).resolve() == ROOT
    ]


def start_console(argv: list[str], env: dict) -> subprocess.Popen:
    """The console process `argv`, in a process group of its own on this window, so a stop
    (ctrl_break) reaches it alone: the window's cmd, which would ask "Terminate batch job (Y/N)?"
    after an interrupt, and this launcher never get one."""
    return subprocess.Popen(
        argv, cwd=ROOT, env=env, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
    )


def ctrl_break(group: int) -> None:
    """Ctrl+Break to process group `group` (the console's, start_console) on its window, from a
    process without a window of its own: the console's handler runs its shutdown
    (server._install_signal_handlers). A group gone is no error: stop reports what is left."""
    subprocess.run(
        [sys.executable, str(Path(__file__)), "ctrl-break", str(group)],
        creationflags=subprocess.CREATE_NO_WINDOW,
        timeout=30,
    )


def _send_ctrl_break(group: int) -> int:
    kernel = ctypes.windll.kernel32
    kernel.FreeConsole()
    if not kernel.AttachConsole(group):
        return 1
    return 0 if kernel.GenerateConsoleCtrlEvent(1, group) else 1  # 1: CTRL_BREAK_EVENT


def group_leader(console: list[psutil.Process]) -> int:
    """The console process whose parent is not one: the launcher started it, so its id is the
    group's. Read from what `running` took, so a process gone since raises nothing."""
    pids = {p.pid for p in console}
    return next(p.pid for p in console if p.info["ppid"] not in pids)


def stop() -> int:
    """The clean stop: ctrl_break to the program's group (group_leader). Waits up to STOP_WAIT_SEC;
    0 when it ended."""
    console = running(CONSOLE_START)
    if console:
        ctrl_break(group_leader(console))
    _gone, alive = psutil.wait_procs(console, timeout=STOP_WAIT_SEC)
    left = [p.pid for p in alive]
    print(
        "Program: "
        + ("not running" if not console else f"still running ({left})" if left else "stopped")
    )
    return 1 if alive else 0


def unhealthy_for(port: int, seconds: float) -> str | None:
    """None once the console on `port` answers /api/health with 200 within `seconds`; else the
    last answer it gave instead (an error status, a refused connection, a timeout)."""
    deadline = time.monotonic() + seconds
    why = f"no answer in {seconds:.0f} s"
    while (left := deadline - time.monotonic()) > 0:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/health", timeout=min(left, 2.0)
            ) as r:
                if r.status == 200:
                    return None
                why = f"HTTP {r.status}"
        except OSError as e:
            why = f"{type(e).__name__}: {e}"
        time.sleep(min(0.25, max(deadline - time.monotonic(), 0)))
    return why


def main() -> int:
    if in_use(CONSOLE_PORT):
        print(f"Program: port {CONSOLE_PORT} is already in use; not started. Opening {URL}.")
        webbrowser.open(URL)  # the default browser
        return 0
    check, commit, why = bring_to_origin_main(ROOT)
    print(f"Commit check: {check}: {why}")
    if commit is not None:
        print(f"Commit: {commit}")
    if check == COMMIT_MOVED:  # this process loaded the old code: the new one starts it
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        return subprocess.call([sys.executable, str(ROOT / "launch.py")], cwd=ROOT)
    print(
        f"Program: starting on port {CONSOLE_PORT}; the browser opens at {URL} once it answers. "
        "Ctrl+C stops it."
    )
    console = start_console(CONSOLE, dict(os.environ))
    signal.signal(
        signal.SIGINT, signal.SIG_IGN
    )  # Ctrl+C is the console's: it stops, then this ends
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
    if sys.argv[1:2] == ["ctrl-break"]:
        raise SystemExit(_send_ctrl_break(int(sys.argv[2])))
    raise SystemExit(main())
