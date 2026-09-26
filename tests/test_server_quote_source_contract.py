"""server's REST fast-quote path must expose real field provenance, fail closed
(never silently zero) on a missing spot, and derive session/order-flow fields from
Schwab's own timestamps -- not wall-clock or a memoized stale quote."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server


class _Resp:
    status_code = 200

    def json(self) -> dict:
        return {
            "SPY": {
                "quote": {
                    "lastPrice": 501.25,
                    "mark": 501.25,
                    "bidPrice": 501.2,
                    "askPrice": 501.3,
                    "quoteTime": 1_778_018_399.0,
                    "tradeTime": 1_778_018_398.0,
                }
            }
        }


def _fresh_streamed_row(spot=501.25):
    import time as _t
    return {"ticker": "SPY", "spot": spot, "bid": 501.2, "ask": 501.3, "chg_pct": 0.42,
            "server_received_ts": _t.time(), "spot_received_ts": _t.time(), "exchange_quote_ts": _t.time(),
            "quote_source_detail": {"spot": "LAST_PRICE"},
            "quote_ingestion": "schwab_streaming_level_one"}


def test_tier_a_live_state_never_bootstraps_from_rest(monkeypatch):
    """/api/live/state is STREAM ONLY (operator rule 2026-09-23: no fallbacks). With no
    streamed row, a working REST quote changes nothing: the route answers
    stream_unavailable and serves no spot, bid, ask or chg_pct."""
    monkeypatch.setattr(server._lmp, "get_quote", lambda _ticker: None)
    monkeypatch.setattr(server, "get_client", lambda: object())
    monkeypatch.setattr(server, "_safe_get_quote_with_retry", lambda *_args, **_kwargs: _Resp())

    out = server._tier_a_live_state_dict("SPY", None)

    assert out.get("_tier") == "A_live"
    assert out["state_error"] == "stream_unavailable"
    for k in ("spot", "bid", "ask", "chg_pct", "quote_ingestion"):
        assert k not in out, f"{k} must be withheld, not substituted"


def test_tier_a_live_state_serves_the_fresh_streamed_row(monkeypatch):
    """Spot, bid, ask and chg_pct all come from ONE fresh streamed row (0 hops each)."""
    from tests.feed_live_helper import mark_feed_live
    mark_feed_live('SPY')   # the daemon holds it on a live feed
    monkeypatch.setattr(server._lmp, "get_quote", lambda _ticker: _fresh_streamed_row())

    out = server._tier_a_live_state_dict("SPY", None)

    assert out["spot"] == 501.25 and out["spot_source"] == server.SPOT_SOURCE_PLANE
    assert out["spot_state"] == "live"
    assert out["bid"] == 501.2 and out["ask"] == 501.3 and out["chg_pct"] == 0.42


def test_tier_a_live_state_withholds_a_stale_streamed_row(monkeypatch):
    """A stalled stream's last tick is not live and nothing replaces it: no REST leg."""
    import time as _t

    stale_row = dict(_fresh_streamed_row(999.0),
                     server_received_ts=_t.time() - (server._CARD_FRESHNESS_V1_QUOTE_STALE_SEC + 5.0),
                     spot_received_ts=_t.time() - (server._CARD_FRESHNESS_V1_QUOTE_STALE_SEC + 5.0))
    monkeypatch.setattr(server._lmp, "get_quote", lambda _ticker: dict(stale_row))
    monkeypatch.setattr(server, "get_client", lambda: object())
    monkeypatch.setattr(server, "_safe_get_quote_with_retry", lambda *_args, **_kwargs: _Resp())

    out = server._tier_a_live_state_dict("SPY", None)

    assert out["state_error"] == "stream_unavailable"
    assert "spot" not in out


def test_tier_a_lightweight_carries_the_tier_c_bundle_generation(monkeypatch):
    """PR #238 D-PCR identity: analytics_lightweight.analytics_version is the SAME entry-level
    generation every /api/analytics/state response reports (_attach_analytics_freshness_contract
    reads entry["analytics_version"]), so a consumer caching a Tier C value can see the bundle
    advance on the plane it already polls and re-read once — no second clock, no per-tick read."""
    from tests.feed_live_helper import mark_feed_live
    mark_feed_live('SPY')   # the daemon holds it on a live feed
    import time as _t

    monkeypatch.setattr(server._lmp, "get_quote", lambda _ticker: _fresh_streamed_row())

    key = ("SPY", "2099-01-16")          # a scope no other test seeds; newest entry for the ticker
    now = _t.time() + 3600.0
    server._state_cache[key] = {
        "ts": now, "generated_at": now, "analytics_version": 42,
        "ms_dict": {"ticker": "SPY", "selected_exp": key[1], "pcr_val": 0.87},
        "pcr_val": 0.87, "spot_f": 500.0, "vix": None,
        "price_levels": None, "pl_date": "", "pl_generation": None, "pl_mono": None,
    }
    # a SECOND, OLDER entry for the same ticker at another expiry with its own generation: Tier C
    # state is keyed by (ticker, expiry) and the generation is per entry, never shared per ticker
    key2 = ("SPY", "2099-02-20")
    server._state_cache[key2] = dict(server._state_cache[key], ts=now - 60.0, generated_at=now - 60.0,
                                     analytics_version=7,
                                     ms_dict={"ticker": "SPY", "selected_exp": key2[1], "pcr_val": 1.13})
    try:
        out = server._tier_a_live_state_dict("SPY", None)
        lw = out["analytics_lightweight"]
        assert lw["pcr_val"] == 0.87
        assert lw["analytics_version"] == 42 == server._state_cache[key]["analytics_version"]
        # the generation is the bundle's, so advancing the bundle advances the plane
        server._state_cache[key]["analytics_version"] = 43
        assert server._tier_a_live_state_dict("SPY", None)["analytics_lightweight"]["analytics_version"] == 43
        # EXPIRY CONTEXT: /api/live/state?expiry=E answers from entry (SPY, E) — the same entry
        # /api/analytics/state?expiry=E reads — not from the ticker's newest entry
        lw2 = server._tier_a_live_state_dict("SPY", key2[1])["analytics_lightweight"]
        assert lw2["analytics_version"] == 7 and lw2["pcr_val"] == 1.13
        server._state_cache[key2]["analytics_version"] = 8
        assert server._tier_a_live_state_dict("SPY", key2[1])["analytics_lightweight"]["analytics_version"] == 8
        assert server._tier_a_live_state_dict("SPY", None)["analytics_lightweight"]["analytics_version"] == 43
        # DEFAULT CONTEXT: both carriers resolve "no expiry" to the ticker's newest entry by the
        # same freshest-ts rule (the analytics route via _latest_cached_ms_and_key_for_ticker)
        _md, newest_key = server._latest_cached_ms_and_key_for_ticker("SPY")
        assert newest_key == key
        assert server._latest_cache_entry_for_ticker("SPY")[0] == key
    finally:
        server._state_cache.pop(key, None)
        server._state_cache.pop(key2, None)
