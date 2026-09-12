"""wait_for_ready_then_open: the launcher must open the browser on actual
readiness, not a blind timer -- and must not hang forever if the server never
comes up."""
from __future__ import annotations

import sys
import time
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import wait_for_ready_then_open as wr


def test_returns_true_as_soon_as_the_server_answers(monkeypatch):
    calls = {"n": 0}

    def _fake_urlopen(url, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionRefusedError("not up yet")
        return object()

    monkeypatch.setattr(wr.urllib.request, "urlopen", _fake_urlopen)
    monkeypatch.setattr(wr.time, "sleep", lambda s: None)  # don't actually wait in the test
    ok = wr.wait_until_ready("http://localhost:8000/console", timeout_sec=5)
    assert ok is True
    assert calls["n"] == 3


def test_an_http_error_status_still_counts_as_ready(monkeypatch):
    """A 404/500 proves the ASGI app is accepting and routing requests -- that
    is the readiness signal, not '200 from this exact path'."""
    def _fake_urlopen(url, timeout=None):
        raise urllib.error.HTTPError(url, 404, "not found", None, None)

    monkeypatch.setattr(wr.urllib.request, "urlopen", _fake_urlopen)
    ok = wr.wait_until_ready("http://localhost:8000/console", timeout_sec=5)
    assert ok is True


def test_gives_up_after_the_timeout_instead_of_hanging_forever(monkeypatch):
    def _always_refused(url, timeout=None):
        raise ConnectionRefusedError("never comes up")

    monkeypatch.setattr(wr.urllib.request, "urlopen", _always_refused)
    monkeypatch.setattr(wr.time, "sleep", lambda s: None)
    t0 = time.monotonic()
    ok = wr.wait_until_ready("http://localhost:8000/console", timeout_sec=0.01)
    assert ok is False
    assert time.monotonic() - t0 < 2  # the test itself must not hang
