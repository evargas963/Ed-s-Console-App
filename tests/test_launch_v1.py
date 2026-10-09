"""The launcher (launch.py): whether a port is in use, against real local listeners on free ports,
and the console's clean stop: Ctrl+C on its own console window (launch.ctrl_c), which runs its
Ctrl+C handler instead of ending it from outside.

STAND-IN: a Python process in a console window of its own, with a Ctrl+C handler that records it
ran, for the console (server._install_signal_handlers).
"""
from __future__ import annotations

import socket
import subprocess
import sys
import time

import pytest

import launch


def test_a_port_with_a_listener_is_in_use_and_a_free_one_is_not():
    with socket.socket() as held:
        held.bind(("127.0.0.1", 0))
        held.listen()
        port = held.getsockname()[1]
        assert launch.in_use(port) is True
    assert launch.in_use(port) is False


@pytest.mark.skipif(sys.platform != "win32", reason="console windows and Ctrl+C events are Windows'")
def test_ctrl_c_runs_the_consoles_handler_on_its_own_window(tmp_path):
    ready, handled = tmp_path / "ready", tmp_path / "handled"
    script = ("import pathlib, signal, sys, time\n"
              f"def on_ctrl_c(signum, frame):\n    pathlib.Path(r'{handled}').write_text('ctrl-c')\n    sys.exit(0)\n"
              "signal.signal(signal.SIGINT, on_ctrl_c)\n"
              f"pathlib.Path(r'{ready}').write_text('ready')\n"
              "time.sleep(120)\n")
    hidden = subprocess.STARTUPINFO()
    hidden.dwFlags, hidden.wShowWindow = subprocess.STARTF_USESHOWWINDOW, 0
    child = subprocess.Popen([sys.executable, "-c", script], creationflags=subprocess.CREATE_NEW_CONSOLE,
                             startupinfo=hidden)
    try:
        deadline = time.monotonic() + 30
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        launch.ctrl_c(child.pid)
        assert child.wait(timeout=30) == 0
        assert handled.read_text() == "ctrl-c", "the process ended without its Ctrl+C handler"
    finally:
        child.kill()
