"""launcher_port_guard: the launcher must never kill a process just for occupying
the target port -- only a verified Ed Console server. Negative-controlled below."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import launcher_port_guard as lpg


def test_recognizes_a_real_ed_console_command_line():
    cmd = (
        r'C:\App\EdWebConsole\.venv\Scripts\python.exe '
        r'-m uvicorn server:app --host 0.0.0.0 --port 8000 --timeout-graceful-shutdown 10'
    )
    assert lpg.is_ed_console_command_line(cmd) is True


def test_rejects_an_unrelated_process_on_the_same_port():
    """The exact adversarial case: something else is using port 8000 -- must not
    be classified as an Ed Console server just because it happens to be there."""
    cmd = r'C:\Program Files\SomeOtherApp\other.exe --listen 8000'
    assert lpg.is_ed_console_command_line(cmd) is False


def test_rejects_empty_or_unavailable_command_line():
    assert lpg.is_ed_console_command_line("") is False
    assert lpg.is_ed_console_command_line(None) is False  # process already exited


def test_ensure_port_free_leaves_an_unrelated_process_running(monkeypatch):
    """Negative control for the original defect: taskkill must NOT be invoked when
    the occupying process is not an Ed Console server."""
    calls = {"taskkill": 0}
    monkeypatch.setattr(lpg, "listening_pid", lambda port: "4242")
    monkeypatch.setattr(lpg, "command_line_for_pid", lambda pid: "C:\\other\\thing.exe")

    def _fake_run(args, **kwargs):
        if args and args[0] == "taskkill":
            calls["taskkill"] += 1
        class _R:
            pass
        return _R()

    monkeypatch.setattr(lpg.subprocess, "run", _fake_run)
    rc = lpg.ensure_port_free(8000, out=lambda *a: None)
    assert rc == 1
    assert calls["taskkill"] == 0, "an unrelated process on the port must never be killed"


def test_ensure_port_free_stops_a_real_ed_console_instance(monkeypatch):
    calls = {"taskkill": 0}
    monkeypatch.setattr(lpg, "listening_pid", lambda port: "5151")
    monkeypatch.setattr(
        lpg, "command_line_for_pid",
        lambda pid: r'C:\...\python.exe -m uvicorn server:app --host 0.0.0.0 --port 8000',
    )

    def _fake_run(args, **kwargs):
        if args and args[0] == "taskkill":
            calls["taskkill"] += 1
        class _R:
            pass
        return _R()

    monkeypatch.setattr(lpg.subprocess, "run", _fake_run)
    monkeypatch.setattr(lpg, "port_is_free", lambda port: True)  # freed immediately after stop
    rc = lpg.ensure_port_free(8000, out=lambda *a: None)
    assert rc == 0
    assert calls["taskkill"] == 1


def test_ensure_port_free_is_a_noop_when_the_port_is_already_free(monkeypatch):
    calls = {"taskkill": 0}
    monkeypatch.setattr(lpg, "listening_pid", lambda port: None)

    def _fake_run(args, **kwargs):
        if args and args[0] == "taskkill":
            calls["taskkill"] += 1
        class _R:
            pass
        return _R()

    monkeypatch.setattr(lpg.subprocess, "run", _fake_run)
    rc = lpg.ensure_port_free(8000, out=lambda *a: None)
    assert rc == 0
    assert calls["taskkill"] == 0
