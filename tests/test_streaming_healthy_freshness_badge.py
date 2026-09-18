"""RC-REHAB-1 (Phase 2) — the header freshness badge disagreed with itself.

Confirmed LIVE during real RTH (2026-09-18): the header badge is painted by two code paths
in ed-core.js -- the primary l1_projection SSE push (and its HTTP twin GET
/api/analytics/light), and a REST poll of /api/live/state used only as a fallback when SSE
stalls. Only the REST path ever attached streaming_plane.streaming_healthy and could paint
"DEGRADED". The primary path never carried that signal at all, so the SAME underlying
degraded streaming state (observed live: streaming_healthy=False for hours during actual
trading hours) painted the badge DEGRADED via one path and silently LIVE via the other,
purely as a function of which code path last ran -- not because the price shown was wrong,
but because the freshness VERDICT about it was inconsistent.

server.py:_l1_attach_freshness_semantics is the one function both paths route through
(_project_l1 directly, and _l1_http_get_projection's cache-hit read); it now attaches
streaming_healthy from a short memo (_memoized_streaming_healthy) so both paths agree.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server


def test_l1_attach_freshness_semantics_sets_streaming_healthy_true(monkeypatch):
    monkeypatch.setattr(server, "_streaming_health_memo", (0.0, False))
    monkeypatch.setattr(
        "app.options.order_flow.streaming.get_streaming_diagnostics",
        lambda: {"streaming_healthy": True},
    )
    out: dict = {}
    server._l1_attach_freshness_semantics(out, time.time())
    assert out["streaming_healthy"] is True


def test_l1_attach_freshness_semantics_sets_streaming_healthy_false(monkeypatch):
    monkeypatch.setattr(server, "_streaming_health_memo", (0.0, True))
    monkeypatch.setattr(
        "app.options.order_flow.streaming.get_streaming_diagnostics",
        lambda: {"streaming_healthy": False},
    )
    out: dict = {}
    server._l1_attach_freshness_semantics(out, time.time())
    assert out["streaming_healthy"] is False


def test_memoized_streaming_healthy_does_not_read_diagnostics_every_call(monkeypatch):
    """The real get_streaming_diagnostics() opens the stream capture DB and reads a status
    file -- calling it on every L1 build/serve (a per-tick path) would be real, avoidable
    I/O. A within-TTL call must reuse the memoized value, not recompute."""
    calls = {"n": 0}

    def _fake_diag():
        calls["n"] += 1
        return {"streaming_healthy": True}

    monkeypatch.setattr("app.options.order_flow.streaming.get_streaming_diagnostics", _fake_diag)
    monkeypatch.setattr(server, "_streaming_health_memo", (0.0, False))

    first = server._memoized_streaming_healthy()
    second = server._memoized_streaming_healthy()
    assert first is True
    assert second is True
    assert calls["n"] == 1, "a second call within the TTL must reuse the memo, not recompute"


def test_memoized_streaming_healthy_recomputes_after_ttl(monkeypatch):
    monkeypatch.setattr(
        "app.options.order_flow.streaming.get_streaming_diagnostics",
        lambda: {"streaming_healthy": True},
    )
    stale_ts = time.monotonic() - server._STREAMING_HEALTH_MEMO_TTL_SEC - 1.0
    monkeypatch.setattr(server, "_streaming_health_memo", (stale_ts, False))
    assert server._memoized_streaming_healthy() is True


def test_memoized_streaming_healthy_fails_closed_on_exception(monkeypatch):
    monkeypatch.setattr(server, "_streaming_health_memo", (0.0, True))

    def _boom():
        raise RuntimeError("diagnostics unavailable")

    monkeypatch.setattr("app.options.order_flow.streaming.get_streaming_diagnostics", _boom)
    assert server._memoized_streaming_healthy() is False, (
        "a diagnostics read failure must fail closed to unhealthy, never silently keep "
        "reporting the previous (possibly stale) healthy verdict"
    )


def test_l1_projection_sse_handler_applies_the_same_degraded_branch_the_poll_path_uses():
    """Mutation test (static): the l1_projection SSE handler must check p.streaming_healthy
    and be able to paint DEGRADED, not just LIVE/STALE/UNAVAILABLE -- this is what was
    silently missing before the fix, verified by reading the actual shipped JS."""
    core = (ROOT / "static" / "js" / "ed-core.js").read_text(encoding="utf-8")
    idx = core.index("addEventListener('l1_projection'")
    handler_slice = core[idx:idx + 3200]
    assert "p.streaming_healthy" in handler_slice, (
        "the l1_projection handler must read streaming_healthy off the payload"
    )
    assert "'DEGRADED'" in handler_slice, (
        "the l1_projection handler must be able to paint DEGRADED, matching the poll-fallback "
        "path's own feedLabel branch, not silently collapse an unhealthy stream to LIVE"
    )
