"""The launcher (launch.py): whether a port is in use, against real local listeners on free ports,
and the console's clean stop. The console runs in a process group of its own (launch.start_console)
and launch.py stop sends that group Ctrl+Break (launch.ctrl_break): the console runs its shutdown
and ends with 0, the window's cmd never gets an interrupt (it would ask "Terminate batch job
(Y/N)?"), and the window closes. The operator's Ctrl+C on the window still stops the console.

STAND-INS: a console window of its own (hidden) for each case; a batch file ending as
start_ed_console.bat ends (launch.py, then a pause only on an error); a Python process with a
Ctrl+Break handler for the console in the first case, and the real console (uvicorn server:app,
offline, a runtime root of its own) in the second.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest

import launch

REPO = Path(__file__).resolve().parent.parent
windows_only = pytest.mark.skipif(sys.platform != "win32", reason="console windows and their Ctrl events are Windows'")


def test_a_port_with_a_listener_is_in_use_and_a_free_one_is_not():
    with socket.socket() as held:
        held.bind(("127.0.0.1", 0))
        held.listen()
        port = held.getsockname()[1]
        assert launch.in_use(port) is True
    assert launch.in_use(port) is False


def _window(argv: "list[str]") -> subprocess.Popen:
    """`argv` in a console window of its own, hidden."""
    hidden = subprocess.STARTUPINFO()
    hidden.dwFlags, hidden.wShowWindow = subprocess.STARTF_USESHOWWINDOW, 0
    return subprocess.Popen(argv, cwd=REPO, creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=hidden)


def _until(path: Path, seconds: float = 60.0) -> str:
    deadline = time.monotonic() + seconds
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    return path.read_text(encoding="utf-8")


def _batch(tmp_path: Path, console_argv: "list[str]", env: "dict | None" = None) -> Path:
    """A batch file that ends as start_ed_console.bat does, its launcher starting `console_argv`
    with launch.start_console and writing the console's process id to tmp_path/console.pid."""
    launcher = tmp_path / "launcher.py"
    launcher.write_text(
        "import signal, sys\n"
        f"sys.path.insert(0, {str(REPO)!r})\n"
        "import launch\n"
        f"console = launch.start_console({console_argv!r}, {env!r})\n"
        f"open({str(tmp_path / 'console.pid')!r}, 'w').write(str(console.pid))\n"
        "signal.signal(signal.SIGINT, signal.SIG_IGN)\n"
        "sys.exit(console.wait())\n", encoding="utf-8")
    bat = tmp_path / "start.bat"
    bat.write_text(f'@echo off\r\n"{sys.executable}" "{launcher}"\r\nif errorlevel 1 pause\r\n', encoding="utf-8")
    return bat


@windows_only
def test_the_stop_ends_the_console_and_leaves_no_window_waiting(tmp_path):
    ready, handled = tmp_path / "ready", tmp_path / "handled"
    console = ("import pathlib, signal, sys, time\n"
               f"def on_break(signum, frame):\n    pathlib.Path(r'{handled}').write_text('break')\n    sys.exit(0)\n"
               "signal.signal(signal.SIGBREAK, on_break)\n"
               f"pathlib.Path(r'{ready}').write_text('ready')\n"
               "while True:\n    time.sleep(0.1)\n")      # awake, as a running console is
    window = _window(["cmd", "/c", str(_batch(tmp_path, [sys.executable, "-c", console], dict(os.environ)))])
    try:
        _until(ready)
        launch.ctrl_break(int(_until(tmp_path / "console.pid")))
        assert window.wait(timeout=30) == 0, "the window's cmd did not end"
        assert handled.read_text() == "break", "the console ended without its Ctrl+Break handler"
    finally:
        window.kill()


def _real_console(tmp_path: Path) -> "tuple[subprocess.Popen, int]":
    """The real console, offline on a free port with a runtime root of its own, started by the
    batch file in a window of its own; healthy before this returns its window and process id."""
    tmp_path.mkdir()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "ED_CI_OFFLINE": "1", "ED_RUNTIME_ROOT": str(tmp_path / "runtime"), "ED_LIVE_PUSH_PORT": "1",
           "SCHWAB_API_KEY": "stand-in", "SCHWAB_APP_SECRET": "stand-in"}
    window = _window(["cmd", "/c", str(_batch(tmp_path, [sys.executable, "-m", "uvicorn", "server:app", "--host",
                                                          "127.0.0.1", "--port", str(port)], env))])
    assert launch.unhealthy_for(port, 120.0) is None
    return window, int(_until(tmp_path / "console.pid"))


@windows_only
def test_the_real_console_stops_on_the_stop_and_on_the_operators_ctrl_c(tmp_path):
    window, pid = _real_console(tmp_path / "break")
    try:
        launch.ctrl_break(pid)
        assert window.wait(timeout=60) == 0, "the console did not stop, or its window waits"
    finally:
        window.kill()
    window, pid = _real_console(tmp_path / "ctrl_c")
    console = psutil.Process(pid)
    try:                    # Ctrl+C to every process on the window, as the operator's key press
        subprocess.run([sys.executable, "-c", "import ctypes, sys; k = ctypes.windll.kernel32; k.FreeConsole(); "
                        "k.AttachConsole(int(sys.argv[1])); k.SetConsoleCtrlHandler(None, True); "
                        "k.GenerateConsoleCtrlEvent(0, 0)", str(pid)], creationflags=subprocess.CREATE_NO_WINDOW,
                       check=True, timeout=30)
        # the console stops (its window's cmd, which the key press reached too, asks its own question)
        assert console.wait(timeout=60) == 0, "the operator's Ctrl+C did not stop the console"
    finally:
        window.kill()
