"""wait_for_ready_then_open: the launcher must open the browser on actual
readiness, not a blind timer -- must not hang forever if the server never
comes up -- and must not treat a timeout as clean success (operator finding:
the browser used to open, and the process used to exit 0, in all three cases:
200, non-200, and never-answers)."""
from __future__ import annotations

import sys
import time
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import wait_for_ready_then_open as wr


def test_returns_ready_as_soon_as_the_server_answers_200(monkeypatch):
    calls = {"n": 0}

    def _fake_urlopen(url, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionRefusedError("not up yet")
        return object()

    monkeypatch.setattr(wr.urllib.request, "urlopen", _fake_urlopen)
    monkeypatch.setattr(wr.time, "sleep", lambda s: None)  # don't actually wait in the test
    result = wr.wait_until_ready("http://localhost:8000/console", timeout_sec=5)
    assert result == "ready"
    assert calls["n"] == 3


def test_an_http_error_status_is_reported_as_unhealthy_not_ready(monkeypatch):
    """A 404/500 proves the ASGI app is up and routing -- but it is a DIFFERENT
    fact from '200 at this exact path', and must be reported as such, not
    silently folded into the same 'ready' result."""
    def _fake_urlopen(url, timeout=None):
        raise urllib.error.HTTPError(url, 404, "not found", None, None)

    monkeypatch.setattr(wr.urllib.request, "urlopen", _fake_urlopen)
    result = wr.wait_until_ready("http://localhost:8000/console", timeout_sec=5)
    assert result == "unhealthy"


def test_gives_up_after_the_timeout_instead_of_hanging_forever(monkeypatch):
    def _always_refused(url, timeout=None):
        raise ConnectionRefusedError("never comes up")

    monkeypatch.setattr(wr.urllib.request, "urlopen", _always_refused)
    monkeypatch.setattr(wr.time, "sleep", lambda s: None)
    t0 = time.monotonic()
    result = wr.wait_until_ready("http://localhost:8000/console", timeout_sec=0.01)
    assert result == "timeout"
    assert time.monotonic() - t0 < 2  # the test itself must not hang


def test_main_opens_the_browser_and_exits_0_when_ready(monkeypatch):
    opened = []
    monkeypatch.setattr(wr, "wait_until_ready", lambda url, timeout_sec: "ready")
    monkeypatch.setattr(wr.subprocess, "Popen", lambda args: opened.append(args))
    rc = wr.main(["prog", "http://localhost:8000/console", "msedge.exe"])
    assert rc == 0
    assert opened == [["msedge.exe", "http://localhost:8000/console"]]


def test_main_opens_the_browser_but_exits_1_when_unhealthy_not_0(monkeypatch):
    """Negative control: an 'unhealthy' result must not be reported as the same
    clean success (exit 0) as a real 200 -- the launcher needs to be able to
    tell the two apart even though both open the browser."""
    opened = []
    monkeypatch.setattr(wr, "wait_until_ready", lambda url, timeout_sec: "unhealthy")
    monkeypatch.setattr(wr.subprocess, "Popen", lambda args: opened.append(args))
    rc = wr.main(["prog", "http://localhost:8000/console", "msedge.exe"])
    assert rc == 1
    assert len(opened) == 1  # still opened -- something real to look at


def test_main_does_not_open_the_browser_on_a_genuine_timeout(monkeypatch):
    """The core negative control for the original defect: a timeout used to
    open the browser and exit 0 anyway, indistinguishable from real success.
    A genuine timeout must not open the browser at all."""
    opened = []
    monkeypatch.setattr(wr, "wait_until_ready", lambda url, timeout_sec: "timeout")
    monkeypatch.setattr(wr.subprocess, "Popen", lambda args: opened.append(args))
    rc = wr.main(["prog", "http://localhost:8000/console", "msedge.exe"])
    assert rc == 2
    assert opened == [], "a genuine timeout must never open the browser"
