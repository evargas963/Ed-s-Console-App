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
import time
import venv
from pathlib import Path

import psutil
import pytest

import launch
import time_et
from app.market_data.schwab.streaming.program_lock import program_ports
from tests.shared_helpers import git, until

pytestmark = pytest.mark.rail

windows_only = pytest.mark.skipif(
    sys.platform != "win32", reason="console windows and their Ctrl events are Windows'"
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
        deadline = time_et.elapsed() + 30
        while not opened.exists() and time_et.elapsed() < deadline:
            time.sleep(0.1)
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
        assert opened_at() == [pages]
        assert program_ports(stream_db).console == console_port
        assert launch.running(launch.DAEMON_START, home), "the program the batch started"
        again = launcher()
        assert (again.returncode, again.stdout.splitlines()[0]) == (
            0,
            "Commit check: not run; Ed Console already runs from this checkout.",
        ), (again.stdout, again.stderr)
        deadline = time_et.elapsed() + 30
        while len(opened_at()) < 2 and time_et.elapsed() < deadline:
            time.sleep(0.1)
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


@windows_only
@pytest.mark.parametrize("code", [2, 3])
def test_the_daemons_window_restarts_a_program_that_failed_and_not_one_that_may_not_run(
    tmp_path, code
):
    """The real start_capture_daemon.cmd restarts a program that ended on an error, after its wait.

    One that ends because this checkout may not run live (2) or another program holds the stream
    (3) is not restarted: its window starts nothing more and ends, once its wait to be read is
    over (at once here: the window has this test's input, and timeout.exe takes none
    redirected). Induced: a capture_main of the test's own, beside the batch where its -m finds
    it first, notes each run and ends 1 (an error), then `code`.
    """
    home = tmp_path / "checkout"
    home.mkdir()
    shutil.copy(launch.ROOT / "start_capture_daemon.cmd", home)
    venv.create(home / ".venv")
    runs = tmp_path / "runs"
    package = Path("app", "market_data", "schwab", "streaming")
    (home / package).mkdir(parents=True)
    for folder in (package, *package.parents[:-1]):
        (home / folder / "__init__.py").write_text("", encoding="utf-8")
    (home / package / "capture_main.py").write_text(
        "import sys\nfrom pathlib import Path\n"
        f"runs = Path({str(runs)!r})\n"
        "before = len(runs.read_text().splitlines()) if runs.exists() else 0\n"
        "with runs.open('a') as f:\n    f.write('run\\n')\n"
        f"sys.exit(1 if before == 0 else {code})\n",
        encoding="utf-8",
    )
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    subprocess.Popen(launch.daemon_window(home / "start_capture_daemon.cmd"), cwd=home, env=env)
    ran = [runs]
    try:
        # the window has started once the first run notes itself, and ends only at its batch's end
        asyncio.run(
            until(
                lambda: runs.exists() and not _running_in(home),
                90,
                state=lambda: [
                    f"runs: {len(r.read_text().splitlines())}" for r in ran if r.exists()
                ],
            )
        )
        assert runs.read_text().splitlines() == ["run", "run"], "restarted after exit code"
    finally:
        for p in _running_in(home):
            p.kill()
