"""The launcher (launch.py).

The commit check before a start; and the start and the clean stop of the one program, at the
ports it wrote in its lock.

Before it starts the program it brings the checkout to origin/main: local changes leave it where
it is, the check refused; an origin out of reach, or a git that does not answer, leaves the check
unknown, never passed. It starts either way (RC-512).

The program (capture_main: the Schwab connection, the recording and the console's pages) runs in
its own window from start_capture_daemon.cmd; the launcher waits for its pages to answer and opens
the browser at them, and launch.py stop asks it to stop by its stop request (a named event). The
launcher's own batch, start_ed_console.cmd, runs launch.py with the project's Python.

STAND-INS: local git repositories for GitHub's origin and the production checkout; a folder of
its own holding launch.py, the batch and a virtual environment, as the production checkout does;
a Python of the test's own as the default browser; a launch.py of the test's own that rewrites
the console's batch, and a capture_main of the test's own that ends on the codes it is given.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import site
import socket
import subprocess
import sys
import threading
import time
import venv
from pathlib import Path

import psutil
import pytest

import launch
import time_et
from app.market_data.schwab.streaming.program_lock import ask_to_stop, program_ports
from tests.shared_helpers import git, until

pytestmark = pytest.mark.rail

windows_only = pytest.mark.skipif(
    sys.platform != "win32", reason="console windows and their Ctrl events are Windows'"
)
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


def _merge(work: Path, name: str) -> str:
    """Merge a commit on origin's main; return its id."""
    (work / name).write_text(name, encoding="utf-8")
    git(work, "add", name)
    git(work, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", name)
    git(work, "push", "-q", "origin", "HEAD:main")
    return git(work, "rev-parse", "HEAD")


def _running_in(home: Path) -> list[psutil.Process]:
    """Return the processes whose command line names `home`: a batch's window and its runs."""
    return [
        p
        for p in psutil.process_iter(["cmdline"])
        # None: a process whose command line Windows does not show
        if p.info["cmdline"] is not None and str(home) in " ".join(p.info["cmdline"])
    ]


def test_each_start_brings_the_checkout_to_origin_main_or_says_why_it_cannot(tmp_path):
    git(tmp_path, "init", "-q", "--bare", "-b", "main", "origin.git")
    git(tmp_path, "clone", "-q", "origin.git", "work")
    first = _merge(tmp_path / "work", "first")
    git(tmp_path, "clone", "-q", "origin.git", "prod")
    prod = tmp_path / "prod"

    assert launch.bring_to_origin_main(prod) == (launch.COMMIT_CURRENT, first, "at origin/main")

    merged = _merge(tmp_path / "work", "merged")  # production one commit behind
    assert launch.bring_to_origin_main(prod) == (
        launch.COMMIT_MOVED,
        merged,
        f"fast-forwarded from {first}",
    )
    assert git(prod, "rev-parse", "HEAD") == merged
    assert launch.bring_to_origin_main(prod)[0] == launch.COMMIT_CURRENT  # the run after it starts

    (prod / "first").write_text("edited in production", encoding="utf-8")
    _merge(tmp_path / "work", "later")
    check, at, why = launch.bring_to_origin_main(prod)
    assert (check, at) == (launch.COMMIT_REFUSED, merged) and why.startswith("local changes")
    assert git(prod, "rev-parse", "HEAD") == merged, "a checkout with local changes was moved"

    (prod / "first").write_text("first", encoding="utf-8")
    git(prod, "remote", "set-url", "origin", str(tmp_path / "unreachable.git"))
    check, at, why = launch.bring_to_origin_main(prod)
    assert (check, at) == (launch.COMMIT_UNKNOWN, merged) and why.startswith(
        "origin could not be fetched"
    )

    # INDUCED CONDITION: git cannot run there (no such folder: the OSError an absent git gives)
    check, at, why = launch.bring_to_origin_main(tmp_path / "gone")
    assert (check, at) == (launch.COMMIT_UNKNOWN, None) and why.startswith(
        "git did not answer: "
    ), "the start ended on git"


@windows_only
def test_the_launcher_starts_the_one_program_opens_its_pages_and_the_stop_ends_it(tmp_path):
    """The real start_capture_daemon.cmd and launch.py in a folder of their own.

    With a virtual environment beside them (no Schwab token, no origin to fetch, ports the
    system picks as the program binds them). `python launch.py` starts the one program in its
    window, reads the ports it wrote in its lock, waits for its pages to answer /api/health and
    opens the default browser at them; run again while it runs, it does not run the commit check
    and opens the browser at the same pages. `python launch.py stop` ends the program, and its
    pages end with it: one program. Induced test condition: the default browser is a Python of
    this test's own (the BROWSER setting Python's webbrowser reads) that writes down the address
    it is given.
    """
    home = tmp_path / "checkout"
    home.mkdir()
    for name in ("launch.py", "start_capture_daemon.cmd"):
        shutil.copy(launch.ROOT / name, home)
    venv.create(home / ".venv")
    opened = tmp_path / "opened"
    browser = tmp_path / "browser.py"
    browser.write_text(
        "import sys\n"
        f"with open({str(opened)!r}, 'a', encoding='utf-8') as f:\n"
        "    f.write(sys.argv[1] + '\\n')\n",
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(launch.ROOT), *site.getsitepackages()]),
        "ED_RUNTIME_ROOT": str(tmp_path),
        "ED_CONSOLE_PORT": "0",
        "SCHWAB_TOKEN_PATH": str(tmp_path / "missing_token.json"),
        "BROWSER": f'"{Path(sys.executable).as_posix()}" "{browser.as_posix()}" %s',
    }
    stream_db = tmp_path / "data" / "stream_capture.db"  # the program's lock is beside it

    def launcher(*args: str) -> subprocess.CompletedProcess:
        """`python launch.py *args`, its output to files.

        The program's window inherits the launcher's handles, so a pipe would stay open as long
        as the program runs.
        """
        out, err = tmp_path / "launcher.out", tmp_path / "launcher.err"
        with out.open("w", encoding="utf-8") as o, err.open("w", encoding="utf-8") as e:
            done = subprocess.run(
                [sys.executable, "launch.py", *args],
                cwd=home,
                env=env,
                stdout=o,
                stderr=e,
                timeout=launch.START_WAIT_SEC + 60,
            )
        return subprocess.CompletedProcess(
            done.args,
            done.returncode,
            out.read_text(encoding="utf-8"),
            err.read_text(encoding="utf-8"),
        )

    def opened_at() -> list[str]:
        return opened.read_text(encoding="utf-8").splitlines() if opened.exists() else []

    try:
        started = launcher()
        lines = started.stdout.splitlines()
        assert started.returncode == 0, (started.stdout, started.stderr)
        assert lines[0].startswith("Commit check: unknown: origin could not be fetched"), lines
        assert 'Ed Console: started in its own window ("Ed Capture Daemon").' in lines, lines
        assert lines[-1].startswith("Ed Console: healthy "), lines
        console_port = launch.wait_for_pages(5.0, stream_db).console
        pages = f"http://127.0.0.1:{console_port}/"
        asyncio.run(until(opened_at, 30))
        assert opened_at() == [pages]
        assert program_ports(stream_db).console == console_port
        assert launch.running(launch.DAEMON_START, home), "the program the batch started"
        again = launcher()
        assert (again.returncode, again.stdout.splitlines()[0]) == (
            0,
            "Commit check: not run; Ed Console already runs from this checkout.",
        ), (again.stdout, again.stderr)
        asyncio.run(until(lambda: len(opened_at()) >= 2, 30, state=opened_at))
        assert opened_at() == [pages, pages]
        stopped = launcher("stop")
        assert (stopped.returncode, stopped.stdout) == (0, "Ed Console: stopped\n"), stopped.stderr
        with socket.socket() as probe:
            refused = probe.connect_ex(("127.0.0.1", console_port))
        assert refused, "the pages outlived the program"
        assert program_ports(stream_db) is None, "the lock outlived the program"
        assert launch.running(launch.DAEMON_START, home) == []
    finally:
        for p in _running_in(home):
            p.kill()


@windows_only
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
    # the file exists from its open, before its write: the pid is in it once its digits are
    ran = lambda: window_pid.exists() and window_pid.read_text(encoding="utf-8").isdigit()
    asyncio.run(until(ran, 60.0))
    assert ran(), "the batch never ran"
    window = int(window_pid.read_text(encoding="utf-8"))
    try:
        asyncio.run(until(lambda: not psutil.pid_exists(window), 30.0))
    finally:
        still_open = psutil.pid_exists(window)
        if still_open:
            psutil.Process(window).kill()
    assert not still_open, "the daemon's window stayed open after its batch ended"


@pytest.mark.alone
@windows_only
def test_the_stop_finds_and_ends_the_daemon_its_batch_started(tmp_path):
    """The real start_capture_daemon.cmd in a folder of its own starts the real daemon.

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
    for name in ("launch.py", "start_capture_daemon.cmd"):
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
    bat = home / "start_capture_daemon.cmd"
    subprocess.Popen(launch.daemon_window(bat), cwd=home, env=env)
    try:
        serving = lambda: program_ports(tmp_path / "data" / "stream_capture.db") is not None
        asyncio.run(until(serving, 60))
        assert serving(), "the batch's daemon never served its port"
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
        stopped_at = time_et.now()
        end = time_et.elapsed() + 8  # past the batch's 5 s restart wait
        while time_et.elapsed() < end:
            # each one found, with when it started against the stop: one started after it is a
            # restart, one started before it is a process the stop did not wait for
            started = [
                {
                    "pid": p.pid,
                    "started_sec_after_the_stop": round(p.info["create_time"] - stopped_at, 2),
                    "seen_sec_after_the_stop": round(time_et.now() - stopped_at, 2),
                    "line": p.info["cmdline"],
                }
                for p in psutil.process_iter(["name", "cwd", "create_time", "cmdline"])
                if p.info["name"] == "python.exe"
                and p.info["cwd"]
                and Path(p.info["cwd"]).resolve() == home.resolve()
            ]
            log_ends = [
                f.read_text(encoding="utf-8")[-1500:] for f in (tmp_path / "logs").glob("*.log")
            ]
            assert not started, (
                f"the batch restarted a daemon stopped on request: {started}; "
                f"the stop's error output: {stopped.stderr!r}; the daemon's log ends: {log_ends}"
            )
            time.sleep(0.2)
    finally:
        for p in _running_in(home):
            p.kill()


def _console(home: Path) -> subprocess.CompletedProcess:
    """Run the real start_ed_console.cmd, copied into `home`, as a double click runs it."""
    shutil.copy(launch.ROOT / "start_ed_console.cmd", home)
    return subprocess.run(
        ["cmd", "/c", str(home / "start_ed_console.cmd")],
        cwd=home,
        stdin=subprocess.DEVNULL,  # its pause on an error reads no key and ends at once
        capture_output=True,
        text=True,
        timeout=120,
    )


@windows_only
def test_the_console_launcher_runs_to_its_end_when_its_start_rewrites_it(tmp_path):
    """A start that fast-forwards the checkout rewrites start_ed_console.cmd while it runs.

    cmd.exe reads a batch file again, at the place it left off, after each command it read
    whole, so the launcher is one block, read whole before it runs: what the new file holds at
    that place never runs. Induced: a launch.py of the test's own writes the file anew, each of
    its lines a command that would note it ran, and ends 0.
    """
    home = tmp_path / "checkout"
    home.mkdir()
    venv.create(home / ".venv")
    ran, stray = tmp_path / "ran", tmp_path / "stray"
    line = f'echo stray> "{stray}"\r\n'
    (home / "launch.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(ran)!r}).write_text('ran')\n"
        f"Path('start_ed_console.cmd').write_bytes({(line * 40).encode()!r})\n",
        encoding="utf-8",
    )
    done = _console(home)
    assert done.returncode == 0, (done.stdout, done.stderr)
    assert ran.exists(), "launch.py did not run"
    assert not stray.exists(), "a line of the rewritten file ran"


@windows_only
def test_a_checkout_with_no_virtual_environment_says_how_to_make_one(tmp_path):
    """The launcher runs the project's own Python only: with no .venv it says how, exit 1."""
    done = _console(tmp_path)
    assert done.returncode == 1, (done.stdout, done.stderr)
    assert "ERROR: repo virtualenv interpreter not found at" in done.stdout, done.stdout
    assert "python -m venv .venv" in done.stdout, done.stdout


def _program(runs: Path, *codes: int) -> list[str]:
    """Return a program of the test's own (INDUCED): each run notes itself in `runs`, ends `codes`.

    Its n-th run ends on the n-th code, the last code on every run after.
    """
    script = (
        "import sys\nfrom pathlib import Path\n"
        f"runs = Path({str(runs)!r})\n"
        "before = len(runs.read_text().splitlines()) if runs.exists() else 0\n"
        "with runs.open('a') as f:\n    f.write('run\\n')\n"
        f"codes = {list(codes)!r}\n"
        "sys.exit(codes[min(before, len(codes) - 1)])\n"
    )
    return ["-c", script]


@pytest.mark.parametrize(
    "code", [launch.EXIT_REFUSED, launch.EXIT_OWNER_LOCK_HELD, launch.EXIT_STOPPED]
)
def test_the_daemons_window_restarts_a_program_that_failed_and_not_one_that_may_not_run(
    tmp_path, code
):
    """The program's window runs it again RESTART_WAIT_SEC after it ends on an error.

    One that ends refusing to run here (2), because another program holds the stream (3), or
    stopped on request (5) is not run again. launch.window with a program of the test's own that
    ends 1 (an error), then `code`; its stop request is the test's own lock's, never the
    runtime's.
    """
    runs = tmp_path / "runs"
    assert launch.window(_program(runs, 1, code), tmp_path / "stream_capture.db") == code
    assert runs.read_text().splitlines() == ["run", "run"], "run again after a code it ends on"


@windows_only
def test_a_stop_between_two_runs_ends_the_windows_wait_and_nothing_runs_again(tmp_path):
    """`launch.py stop` asks the window too: between two runs, the wait ends and nothing runs.

    The window holds the stop request (a named event on Windows), so the ask finds it while no
    program runs. Asked once the first run has noted itself, the window ends at its wait, the
    program run once.
    """
    runs, db = tmp_path / "runs", tmp_path / "stream_capture.db"

    def ask_once_it_ran() -> None:
        asyncio.run(until(runs.exists, 60))
        ask_to_stop(db)

    asking = threading.Thread(target=ask_once_it_ran)
    asking.start()
    try:
        assert launch.window(_program(runs, 1), db) == 1
    finally:
        asking.join(60)
    assert runs.read_text().splitlines() == ["run"], "the window ran it again after the stop"
