"""Ed Console's launcher: start_ed_console.cmd runs it with the project's .venv Python.

Ed Console is one program (capture_main): the Schwab connection, the recording and the console's
pages. Its start stops nothing.

0. With it not running, the checkout brought to origin/main (bring_to_origin_main), so it starts
   from the newest merged commit: moved, it runs the new launch.py as its child and ends with it.
   With local changes, not on main, split from origin/main or origin out of reach, it starts from
   the commit the checkout is at, the check not passed and why said: whether the app starts is
   never the repository's to decide. Running, the check is not run.
1. The program, in its own window (start_capture_daemon.cmd, which runs `launch.py window`: it
   runs the program again after it ends on an error, window). It reads its own .env (the Schwab
   credentials); its log, and /api/health from its heartbeat, say whether Schwab took them.
2. The default browser, at the pages' port the program wrote in its lock (program_ports), once
   they answer healthy (START_WAIT_SEC).

`python launch.py stop` is the clean stop (stop): the program is asked to stop by its stop request
(program_lock.ask_to_stop: a named event of this user's session on Windows), which its window
holds too, so a stop between two runs is asked as well; the program writes what it holds before
it exits, and its window does not run it again.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

import psutil

import time_et
from app.market_data.schwab.streaming.program_lock import (
    EXIT_OWNER_LOCK_HELD,
    EXIT_REFUSED,
    EXIT_STOPPED,
    Ports,
    StopRequest,
    ask_to_stop,
    program_ports,
)
from numeric_contract import fixed_text

log = logging.getLogger("launch")
ROOT = Path(__file__).resolve().parent
#: what the program runs right after Python (its window's run of it: window)
DAEMON_START = ["-m", "app.market_data.schwab.streaming.capture_main"]
#: what the program's window runs right after Python (start_capture_daemon.cmd's line)
WINDOW_START = ["launch.py", "window"]
#: how long the window waits after the program ends on an error before it runs it again
RESTART_WAIT_SEC = 5.0
#: the program's exit codes its window does not run it again after, each with why
NOT_RUN_AGAIN = {
    EXIT_REFUSED: "it refused to run here (its reason is above)",
    EXIT_OWNER_LOCK_HELD: "another program already holds the stream",
    EXIT_STOPPED: "it was stopped on request",
}
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
    """Bring the checkout at `root` to origin/main.

    Return (what the check found, the commit it is at, None when git could not say, why). It
    fetches origin and fast-forwards main. COMMIT_CURRENT: at origin/main. COMMIT_MOVED:
    fast-forwarded. COMMIT_UNKNOWN: origin out of reach, or git itself not answering (absent,
    hung); COMMIT_REFUSED: not on main, local changes, or a history split from origin/main;
    nothing is moved.
    """
    try:
        return _bring(root)
    except (OSError, subprocess.SubprocessError) as e:
        return COMMIT_UNKNOWN, None, f"git did not answer: {type(e).__name__}: {e}"


def _bring(root: Path) -> tuple[str, str, str]:
    def git(*args: str) -> subprocess.CompletedProcess[str]:
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


def running(start: list[str], root: Path = ROOT) -> list[psutil.Process]:
    """Return the checkout's processes that run `start` right after their program.

    Those whose folder is `root` (this checkout, ROOT, unless a test names another), where its
    daemon's batch and its console run, so another checkout's daemon or console (a test's) is
    never taken for one, nor a process that only names them, as a search does (one whose line or
    folder cannot be read is none). A folder is read only for a process whose line runs `start`:
    each read of another process's memory can take a second (psutil retries a partial copy, as a
    sandboxed browser's gives), so the scan reads no folder it does not compare.
    """
    return [
        p
        for p in psutil.process_iter(["cmdline"])
        if p.info["cmdline"] is not None
        and p.info["cmdline"][1 : len(start) + 1] == start
        and _folder(p) == root.resolve()
    ]


def _folder(p: psutil.Process) -> Path | None:
    """Return the folder process `p` runs in, or None when it cannot be read or has ended."""
    try:
        return Path(p.cwd()).resolve()
    except psutil.Error as e:
        log.warning("Ed Console: pid %s runs the program; its folder is unknown: %r", p.pid, e)
        return None


def daemon_window(batch: Path) -> list[str]:
    """Return the command that runs `batch` (start_capture_daemon.cmd) in a minimized window.

    The window is its own, titled "Ed Capture Daemon", under `cmd /c` so the window closes when
    the batch ends (`start` given a batch file runs it under `cmd /K`, which keeps the window
    open).
    """
    return ["cmd", "/c", "start", "Ed Capture Daemon", "/min", "cmd", "/c", str(batch)]


def window(start: list[str] = DAEMON_START, db_path: Path | None = None) -> int:
    """Run the program in this window, and again RESTART_WAIT_SEC after it ends on an error.

    start_capture_daemon.cmd runs it (`launch.py window`). The window holds the program's stop
    request (program_lock.StopRequest, of the lock at `db_path`: None is the runtime's own), so
    `launch.py stop` can ask between two runs as well as during one: the wait ends at the ask,
    and nothing runs again. Nor does it after an exit code of NOT_RUN_AGAIN's or Ctrl+C in the
    window. Returns the program's last exit code. `start` and `db_path` are a test's own.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
    request = StopRequest(db_path)
    try:
        while True:
            code, interrupted = _run_once(start)
            if interrupted or code in NOT_RUN_AGAIN:
                why = "Ctrl+C in its window" if interrupted else NOT_RUN_AGAIN[code]
                log.info("Ed Console ended (exit %s): %s; not run again", code, why)
                return code
            log.warning(
                "Ed Console ended on an error (exit %s): run again in %.0f s",
                code,
                RESTART_WAIT_SEC,
            )
            if request.wait(RESTART_WAIT_SEC):
                log.info("Ed Console: stopped on request; not run again")
                return code
    finally:
        request.close()


def _run_once(start: list[str]) -> tuple[int, bool]:
    """Run the program once in this window; return its exit code and whether Ctrl+C was pressed.

    Ctrl+C reaches the program as well as this window: the program stops by itself (its clean
    stop, capture.INTERRUPTS), and this waits for it to end, never ending it.
    """
    interrupted = False
    with subprocess.Popen([sys.executable, *start], cwd=ROOT) as program:
        while True:
            try:
                return program.wait(), interrupted
            except KeyboardInterrupt:
                log.info("Ctrl+C: Ed Console is stopping; waiting for it to end")
                interrupted = True


def stop() -> int:
    """Stop the program cleanly: set its stop request (program_lock.ask_to_stop).

    It writes what it holds and exits, and its window does not run it again; the Schwab
    connection, the recording and the console's pages end together. Its window holds the request
    too, so a stop between two runs is asked as well. Waits up to STOP_WAIT_SEC for the program
    and its window; 0 when they ended. One it could not ask (no request to set) is reported at
    once, still running, exit 1: no wait can stop a program that was not asked.
    """
    program = running(DAEMON_START) + running(WINDOW_START)
    left = program
    if program:
        try:
            ask_to_stop()
        except OSError as e:
            log.warning("Ed Console: not asked to stop: %s: %s", type(e).__name__, e)
        else:
            _gone, left = psutil.wait_procs(program, timeout=STOP_WAIT_SEC)
    answer = (
        f"still running ({[p.pid for p in left]})"
        if left
        else "stopped"
        if program
        else "not running"
    )
    print("Ed Console: " + answer)
    return 1 if left else 0


def wait_for_pages(seconds: float, db_path: Path | None = None) -> Ports:
    """Return the program's ports once its pages answer /api/health with 200, the answer read whole.

    A connection closed on an unread answer is reset, which the program's stop then waits on.
    The ports are the ones it wrote in its lock (program_ports; `db_path` is for tests). Raises
    TimeoutError when `seconds` pass first, with the last answer: no ports written yet, an error
    status, a refused connection or a timeout.
    """
    deadline = time_et.elapsed() + seconds
    why = "it has not opened its ports"
    while (left := deadline - time_et.elapsed()) > 0:
        ports = program_ports(db_path)
        if ports is not None:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{ports.console}/api/health", timeout=min(left, 2.0)
                ) as r:
                    r.read()
                    if r.status == 200:
                        return ports
                    why = f"HTTP {r.status}"
            except OSError as e:
                why = f"{type(e).__name__}: {e}"
        time.sleep(min(0.25, max(deadline - time_et.elapsed(), 0)))
    raise TimeoutError(why)


#: how long the launcher waits for the program's pages to answer before it says they did not
START_WAIT_SEC = 180.0


def main() -> int:
    if running(DAEMON_START) or running(WINDOW_START):  # between two runs only its window does
        print("Commit check: not run; Ed Console already runs from this checkout.")
    else:
        check, commit, why = bring_to_origin_main(ROOT)
        print(f"Commit check: {check}: {why}")
        if commit is not None:
            print(f"Commit: {commit}")
        if check == COMMIT_MOVED:  # this process loaded the old code: the new one starts it
            return subprocess.call([sys.executable, str(ROOT / "launch.py")], cwd=ROOT)
        subprocess.Popen(daemon_window(ROOT / "start_capture_daemon.cmd"), cwd=ROOT)
        print('Ed Console: started in its own window ("Ed Capture Daemon").')
    started = time_et.elapsed()
    try:
        ports = wait_for_pages(START_WAIT_SEC)
    except TimeoutError as e:
        print(f"Ed Console: its pages did not answer in {fixed_text(START_WAIT_SEC, 0)} s: {e}")
        return 1
    print(f"Ed Console: healthy {fixed_text(time_et.elapsed() - started, 1)} s after the start.")
    webbrowser.open(f"http://127.0.0.1:{ports.console}/")  # the default browser
    return 0


if __name__ == "__main__":
    raise SystemExit(
        stop() if sys.argv[1:] == ["stop"] else window() if sys.argv[1:] == ["window"] else main()
    )
