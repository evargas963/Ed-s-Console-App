"""
Issue 28 — Tier B overlay vs projection: explicit full_overlay contract (HTTP + SSE).

Proves: single server assembly (_l1_http_get_projection), no projection-only SSE path,
client does not re-document a conflicting mode.
"""
from __future__ import annotations

import asyncio
import inspect
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_server_contract_constant_full_overlay():
    import server as srv

    assert getattr(srv, "L1_TIER_B_CHANNEL_PAYLOAD_MODE", None) == "full_overlay"


def test_http_and_sse_both_call_same_projection_assembler(monkeypatch):
    """GET /api/analytics/light path and L1 SSE notify must use _l1_http_get_projection for the Tier B body."""
    import server as srv

    calls: list[tuple[str, str | None, bool]] = []

    def traced(ticker: str, expiry: str | None, *, force: bool = False) -> dict:
        calls.append((ticker, expiry, force))
        return {
            "l1_generation": 7,
            "_server_build_ts": 1700000000.0,
            "ticker": ticker,
            "_tier": "B_light",
        }

    monkeypatch.setattr(srv, "_l1_http_get_projection", traced)

    from planes import l1_events

    l1_events.notify_ticker_expiry_changed("SPY", None)
    assert len(calls) == 1
    assert calls[0] == ("SPY", None, False)

    q = asyncio.Queue(maxsize=10)
    key = ("SPY", "__auto__")
    srv._l1_light_sse_clients.append((q, key))
    monkeypatch.setattr(srv, "_L1_SSE_MIN_INTERVAL_SEC", 0.0)
    srv._l1_sse_last_emit_mono.pop(key, None)
    try:
        srv._l1_notify_sse_after_authoritative_build("SPY", None)
        assert len(calls) == 2
        assert calls[1] == ("SPY", None, False)
    finally:
        srv._l1_light_sse_clients.clear()
        while not srv._l1_sse_thread_queue.empty():
            try:
                srv._l1_sse_thread_queue.get_nowait()
            except Exception:
                break


def test_sse_notify_source_assigns_payload_from_projection_only():
    """
    Regression: SSE must not assign Tier B payload from raw cache without overlay.
    Enforced by requiring payload = _l1_http_get_projection(...) in source.
    """
    import server as srv

    src = inspect.getsource(srv._l1_notify_sse_after_authoritative_build)
    assert re.search(r"payload\s*=\s*_l1_http_get_projection\s*\(", src), (
        "SSE notify must set payload from _l1_http_get_projection (full_overlay contract)"
    )
    assert "L1_TIER_B_CHANNEL_PAYLOAD_MODE" in srv.__dict__ or hasattr(srv, "L1_TIER_B_CHANNEL_PAYLOAD_MODE")


def test_fingerprint_identity_same_for_equivalent_payloads():
    """Semantic identity helper is stable for Tier B contract (aligned with material fingerprint)."""
    import server as srv

    a = {"spot": 100.0, "l1_generation": 1, "_server_build_ts": 100.0, "ticker": "SPY"}
    b = dict(a)
    assert srv._l1_payload_fingerprint(a) == srv._l1_payload_fingerprint(b)


def test_index_html_declares_full_overlay_client_mode():
    """Client documents full_overlay; fail if marker removed."""
    index = ROOT / "static" / "index.html"
    text = index.read_text(encoding="utf-8")
    assert "ED_L1_TIER_B_SEMANTIC_MODE" in text
    assert "full_overlay" in text
    assert "renderTierBLight" in text


def test_not_projection_only_mode():
    """Guardrail: contract must not regress to ambiguous projection-only SSE."""
    import server as srv

    assert srv.L1_TIER_B_CHANNEL_PAYLOAD_MODE != "projection_only"
