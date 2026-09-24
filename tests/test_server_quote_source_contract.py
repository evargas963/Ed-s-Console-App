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


class _RespNoSpot:
    status_code = 200

    def json(self) -> dict:
        return {
            "SPY": {
                "quote": {
                    "lastPrice": None,
                    "mark": None,
                    "bidPrice": None,
                    "askPrice": None,
                }
            }
        }


def test_parse_quote_node_session_fields_extended_regular_fallbacks():
    node = {
        "quote": {"lastPrice": None, "mark": None, "bidPrice": None, "askPrice": None},
        "extended": {
            "lastPrice": 100.5,
            "mark": 100.4,
            "bidPrice": 100.3,
            "askPrice": 100.6,
            "quoteTime": 10.0,
            "tradeTime": 9.0,
        },
        "regular": {"regularMarketLastPrice": 99.0, "regularMarketTradeTime": 8.0},
    }
    pq = server._parse_quote_node_session_fields(node)
    assert pq["spot"] == 100.5
    assert pq["spot_source"] == "lastPrice"
    assert pq["bid"] == 100.3
    assert pq["ask"] == 100.6
    assert pq["quote_mid"] == 100.4
    assert pq["mid_source"] == "schwab_quote_mark"
    assert pq["quote_ts"] == 10.0


def test_parse_quote_node_session_fields_normalizes_epoch_ms_to_seconds():
    """2026-06-09 regression: Schwab wire quoteTime/tradeTime are epoch MILLISECONDS. Raw ms
    ticks reached the candle accumulators, price_bars_1m got ms-grid rows, and fill_outcomes
    (seconds grid) matched zero bars — no snapshot outcome was labeled all session."""
    ms_quote = 1_781_047_719_060.0  # 2026-06-09 19:28:39.060 ET in ms
    node = {"quote": {"lastPrice": 600.0, "quoteTime": ms_quote, "tradeTime": ms_quote - 1000.0}}
    pq = server._parse_quote_node_session_fields(node)
    assert pq["quote_time"] == ms_quote / 1000.0
    assert pq["trade_time"] == (ms_quote - 1000.0) / 1000.0
    assert pq["quote_ts"] == ms_quote / 1000.0
    # Seconds-unit inputs (tests, replay fixtures) pass through unchanged.
    node_s = {"quote": {"lastPrice": 600.0, "quoteTime": 1_778_018_399.0, "tradeTime": None}}
    assert server._parse_quote_node_session_fields(node_s)["quote_time"] == 1_778_018_399.0


def test_parse_quote_node_session_fields_carries_raw_order_flow_primitives():
    """2026-06-10 operator: log the Schwab leaves (quotes.{SYM}.bidSize/askSize/lastSize/
    totalVolume), not only derivations like spread — order-flow ablation candidates."""
    node = {
        "quote": {
            "lastPrice": 600.0,
            "bidPrice": 599.9,
            "askPrice": 600.1,
            "bidSize": 12.0,
            "askSize": 7.0,
            "lastSize": 300.0,
            "totalVolume": 41_250_000.0,
        }
    }
    pq = server._parse_quote_node_session_fields(node)
    assert pq["bid_size"] == 12.0
    assert pq["ask_size"] == 7.0
    assert pq["last_size"] == 300.0
    assert pq["total_volume"] == 41_250_000.0
    # Extended-session fallback when the quote node omits sizes.
    node_ext = {
        "quote": {"lastPrice": 600.0},
        "extended": {"bidSize": 3.0, "askSize": 4.0, "lastSize": 50.0, "totalVolume": 100.0},
    }
    pq_ext = server._parse_quote_node_session_fields(node_ext)
    assert pq_ext["bid_size"] == 3.0
    assert pq_ext["ask_size"] == 4.0
    assert pq_ext["last_size"] == 50.0
    assert pq_ext["total_volume"] == 100.0
    # Missing on the wire → honest None, never a fabricated zero.
    pq_none = server._parse_quote_node_session_fields({"quote": {"lastPrice": 600.0}})
    assert pq_none["bid_size"] is None
    assert pq_none["ask_size"] is None
    assert pq_none["last_size"] is None
    assert pq_none["total_volume"] is None


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
