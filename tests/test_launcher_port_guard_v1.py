"""launcher_port_guard: the launcher must never kill a process just for occupying
the target port -- only a verified Ed Console server -- and must never treat a
failed port inspection as proof the port is free. Negative-controlled below."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import launcher_port_guard as lpg


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


def test_rejects_a_coincidental_substring_match():
    """Operator finding (2026-09-11): the original check was `"uvicorn" in c and
    "server:app" in c` -- true for ANY command line containing both words
    anywhere, not just a real invocation. This is the exact negative control:
    a command that mentions both words but is not the real invocation shape
    must NOT be classified as an Ed Console server."""
    cmd = r'C:\Windows\notepad.exe "C:\notes\uvicorn and server:app migration plan.txt"'
    assert lpg.is_ed_console_command_line(cmd) is False


class _FakeResponse:
    def __init__(self, status, body_bytes):
        self.status = status
        self._body = body_bytes

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_is_actually_ed_console_true_when_build_endpoint_matches(monkeypatch):
    body = b'{"git_sha": "abc123", "release_id": "r1"}'
    monkeypatch.setattr(lpg.urllib.request, "urlopen", lambda url, timeout=None: _FakeResponse(200, body))
    assert lpg.is_actually_ed_console(8000) is True


def test_is_actually_ed_console_false_when_shape_matches_but_identity_endpoint_disagrees(monkeypatch):
    """The exact adversarial case named in this module's docstring: an unrelated
    process with a matching command-line SHAPE must not answer /api/build with
    the expected identity -- here it doesn't answer at all (connection refused),
    which must read as NOT confirmed, never as confirmed by default."""
    def _raise(url, timeout=None):
        raise ConnectionRefusedError("nothing listening with this identity")

    monkeypatch.setattr(lpg.urllib.request, "urlopen", _raise)
    assert lpg.is_actually_ed_console(8000) is False


def test_is_actually_ed_console_false_when_body_is_missing_expected_keys(monkeypatch):
    body = b'{"unrelated": "app"}'
    monkeypatch.setattr(lpg.urllib.request, "urlopen", lambda url, timeout=None: _FakeResponse(200, body))
    assert lpg.is_actually_ed_console(8000) is False


def test_is_actually_ed_console_false_when_the_identity_values_are_null(monkeypatch):
    """Independent-review finding (2026-09-12), REPRODUCED directly against this function:
    `"git_sha" in body` tests KEY MEMBERSHIP, not a real value -- a body of
    {"git_sha": null, "release_id": null} has both keys present and passed the old check.
    Any unrelated JSON endpoint naming these two keys with nothing behind them must not be
    misidentified as Ed Console."""
    body = b'{"git_sha": null, "release_id": null}'
    monkeypatch.setattr(lpg.urllib.request, "urlopen", lambda url, timeout=None: _FakeResponse(200, body))
    assert lpg.is_actually_ed_console(8000) is False


def test_is_actually_ed_console_false_when_the_identity_values_are_empty_strings(monkeypatch):
    body = b'{"git_sha": "", "release_id": ""}'
    monkeypatch.setattr(lpg.urllib.request, "urlopen", lambda url, timeout=None: _FakeResponse(200, body))
    assert lpg.is_actually_ed_console(8000) is False


class _FakeProcess:
    """Stand-in for psutil.Process -- records .kill() calls without touching a
    real OS process."""

    def __init__(self, pid, *, calls):
        self.pid = pid
        self._calls = calls

    def kill(self):
        self._calls["kill"] += 1


def test_ensure_port_free_leaves_an_unrelated_process_running(monkeypatch):
    """Negative control for the original defect: nothing must be killed when the
    occupying process's command line does not even match the Ed Console shape."""
    calls = {"kill": 0}
    monkeypatch.setattr(lpg, "listening_pid", lambda port: 4242)
    monkeypatch.setattr(lpg, "command_line_for_pid", lambda pid: "C:\\other\\thing.exe")
    monkeypatch.setattr(lpg.psutil, "Process", lambda pid: _FakeProcess(pid, calls=calls))
    rc = lpg.ensure_port_free(8000, out=lambda *a: None)
    assert rc == 1
    assert calls["kill"] == 0, "an unrelated process on the port must never be killed"


def test_ensure_port_free_leaves_a_shape_matching_but_unconfirmed_process_running(monkeypatch):
    """Independent-review finding (2026-09-11/12): invocation SHAPE alone is not
    proof of ownership -- an unrelated app using the same common uvicorn/
    server:app naming would pass the regex too. Must not be killed unless
    /api/build identity is ALSO confirmed."""
    calls = {"kill": 0}
    monkeypatch.setattr(lpg, "listening_pid", lambda port: 4343)
    monkeypatch.setattr(
        lpg, "command_line_for_pid",
        lambda pid: r'C:\...\python.exe -m uvicorn server:app --host 0.0.0.0 --port 8000',
    )
    monkeypatch.setattr(lpg, "is_actually_ed_console", lambda port, **kw: False)
    monkeypatch.setattr(lpg.psutil, "Process", lambda pid: _FakeProcess(pid, calls=calls))
    rc = lpg.ensure_port_free(8000, out=lambda *a: None)
    assert rc == 1
    assert calls["kill"] == 0, "shape match without confirmed /api/build identity must not be killed"


def test_ensure_port_free_stops_a_real_ed_console_instance(monkeypatch):
    calls = {"kill": 0}
    monkeypatch.setattr(lpg, "listening_pid", lambda port: 5151)
    monkeypatch.setattr(
        lpg, "command_line_for_pid",
        lambda pid: r'C:\...\python.exe -m uvicorn server:app --host 0.0.0.0 --port 8000',
    )
    monkeypatch.setattr(lpg, "is_actually_ed_console", lambda port, **kw: True)
    monkeypatch.setattr(lpg.psutil, "Process", lambda pid: _FakeProcess(pid, calls=calls))
    monkeypatch.setattr(lpg, "port_is_free", lambda port: True)  # freed immediately after stop
    rc = lpg.ensure_port_free(8000, out=lambda *a: None)
    assert rc == 0
    assert calls["kill"] == 1


def test_ensure_port_free_is_a_noop_when_the_port_is_already_free(monkeypatch):
    calls = {"kill": 0}
    monkeypatch.setattr(lpg, "listening_pid", lambda port: None)
    monkeypatch.setattr(lpg.psutil, "Process", lambda pid: _FakeProcess(pid, calls=calls))
    rc = lpg.ensure_port_free(8000, out=lambda *a: None)
    assert rc == 0
    assert calls["kill"] == 0


def test_a_failed_port_inspection_is_not_treated_as_a_free_port(monkeypatch):
    """Negative control for the original defect: listening_pid() used to swallow
    a netstat failure and return None, which ensure_port_free read as 'nothing
    is listening' -- silently proceeding to launch a second server into a port
    whose real state was actually unknown. Must now fail closed (exit 2), never
    exit 0."""
    def _raise(port):
        raise lpg.PortInspectionError("netstat -ano failed: simulated")

    monkeypatch.setattr(lpg, "listening_pid", _raise)
    rc = lpg.ensure_port_free(8000, out=lambda *a: None)
    assert rc == 2, "an inspection failure must never be reported as a confirmed-free port"


class _FakeListenConn:
    """Stand-in for a psutil connection object -- just the attributes listening_pid reads."""

    def __init__(self, status, port, pid):
        self.status = status
        self.laddr = _FakeLaddr(port)
        self.pid = pid


class _FakeLaddr:
    def __init__(self, port):
        self.port = port


def test_listening_pid_raises_when_a_real_listener_has_no_attributable_pid(monkeypatch):
    """Independent-review finding (2026-09-12), REPRODUCED directly against this function:
    psutil can report a LISTENING socket whose own .pid is None (Windows without elevated
    privilege, or a socket psutil cannot attribute) -- the old code returned that None
    straight through, which read as 'nothing is listening'. A genuinely occupied port with
    an unreadable owner is an inspection gap, not a free port."""
    fake_conn = _FakeListenConn(lpg.psutil.CONN_LISTEN, 8000, None)
    monkeypatch.setattr(lpg.psutil, "net_connections", lambda kind="inet": [fake_conn])
    try:
        lpg.listening_pid(8000)
        assert False, "must raise PortInspectionError, never return None for an unattributable listener"
    except lpg.PortInspectionError:
        pass


def test_ensure_port_free_fails_closed_when_the_listener_has_no_attributable_pid(monkeypatch):
    fake_conn = _FakeListenConn(lpg.psutil.CONN_LISTEN, 8000, None)
    monkeypatch.setattr(lpg.psutil, "net_connections", lambda kind="inet": [fake_conn])
    rc = lpg.ensure_port_free(8000, out=lambda *a: None)
    assert rc == 2, "an unattributable listener must never be reported as a confirmed-free port"


def test_listening_pid_returns_the_real_pid_when_attributable(monkeypatch):
    """Not every listener lacks a pid -- the ordinary case must still work."""
    fake_conn = _FakeListenConn(lpg.psutil.CONN_LISTEN, 8000, 4242)
    monkeypatch.setattr(lpg.psutil, "net_connections", lambda kind="inet": [fake_conn])
    assert lpg.listening_pid(8000) == 4242
