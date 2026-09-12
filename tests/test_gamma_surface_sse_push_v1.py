"""_next_gamma_surface_seq's SSE push / _sse_event_name_for_envelope (server.py): independent-
review finding (2026-09-12) -- 'the browser still polls every 12 seconds. The new Playwright
test manually triggers the refresh event, bypassing that wait. It proves rendering after
delivery, not timely delivery.' This closes that gap by reusing the EXISTING
/api/analytics/light/stream connection/queue/dispatch pipe (no second SSE endpoint or daemon):
every gamma-surface publication now pushes a lightweight {ticker, surface_seq} notify through
it, and the generator picks the wire event name from the envelope instead of always emitting
"l1_projection"."""
from __future__ import annotations

import server


def test_sse_event_name_defaults_to_l1_projection_for_an_ordinary_envelope():
    """Every existing L1 envelope omits _sse_event_name -- must be completely unaffected."""
    assert server._sse_event_name_for_envelope({"l1_sse_schema": 1, "payload": {}}) == "l1_projection"


def test_sse_event_name_uses_the_envelope_override_when_present():
    assert server._sse_event_name_for_envelope(
        {"_sse_event_name": "gamma_surface_seq", "surface_seq": 3}) == "gamma_surface_seq"


def test_sse_event_name_is_l1_projection_for_a_non_dict_envelope():
    assert server._sse_event_name_for_envelope(None) == "l1_projection"
    assert server._sse_event_name_for_envelope("not a dict") == "l1_projection"


def test_next_gamma_surface_seq_pushes_a_gamma_surface_seq_envelope_when_a_subscriber_exists():
    tk = server.ticker_storage_key("SPY")
    server._gamma_surface_seq.pop(tk, None)
    import asyncio
    q = asyncio.Queue(maxsize=10)
    key = (tk, "__auto__")
    server._l1_light_sse_clients.append((q, key))
    try:
        n0 = server._l1_sse_thread_queue.qsize()
        seq = server._next_gamma_surface_seq(tk)
        assert seq == 1
        assert server._l1_sse_thread_queue.qsize() == n0 + 1
        pushed_key, env = server._l1_sse_thread_queue.get_nowait()
        assert pushed_key == key
        assert env["_sse_event_name"] == "gamma_surface_seq"
        assert env["scope"] == {"ticker": tk}
        assert env["surface_seq"] == 1
    finally:
        server._l1_light_sse_clients.remove((q, key))


def test_next_gamma_surface_seq_still_bumps_the_counter_with_no_subscribers():
    """The push is best-effort -- an empty thread queue push still must not affect the
    counter itself, which is the load-bearing part for revision-key correctness."""
    tk = server.ticker_storage_key("QQQ")
    server._gamma_surface_seq.pop(tk, None)
    server._l1_light_sse_clients.clear()
    assert server._next_gamma_surface_seq(tk) == 1
    assert server._next_gamma_surface_seq(tk) == 2


def test_next_gamma_surface_seq_survives_a_push_failure(monkeypatch):
    tk = server.ticker_storage_key("SPY")
    server._gamma_surface_seq.pop(tk, None)

    def _boom(sk, env):
        raise RuntimeError("simulated queue failure")

    monkeypatch.setattr(server, "_l1_put_thread_queue_notify", _boom)
    assert server._next_gamma_surface_seq(tk) == 1, (
        "a failed SSE push must never prevent the counter (the load-bearing part) from advancing"
    )
