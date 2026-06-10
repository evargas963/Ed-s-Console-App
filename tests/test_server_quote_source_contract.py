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
                    "lastPrice": None,
                    "mark": 501.25,
                    "bidPrice": 501.2,
                    "askPrice": 501.3,
                    "quoteTime": 1_778_018_399.0,
                    "tradeTime": 1_778_018_398.0,
                }
            }
        }


def test_rest_fast_quote_payload_exposes_field_sources(monkeypatch):
    monkeypatch.setattr(server, "get_client", lambda: object())
    monkeypatch.setattr(server, "_safe_get_quote_with_retry", lambda *_args, **_kwargs: _Resp())

    payload = server._build_rest_fast_quote_payload("SPY", "rest_fast_quote")

    assert payload["spot"] == 501.25
    assert payload["quote_mid"] == 501.25
    assert payload["mid_source"] == "schwab_quote_mark"
    assert payload["spread_source"] == "derived_bid_ask_fraction_schwab_mark_denom"
    assert payload["spread_pts"] == 0.1
    assert payload["fast_server_ts"] == 1_778_018_399.0
    assert payload["quote_time_source"] == "schwab_rest_quote"
    assert isinstance(payload["server_received_ts"], float)
    assert payload["quote_source_detail"] == {
        "spot": "mark",
        "bid": "bidPrice",
        "ask": "askPrice",
        "mid": "schwab_quote_mark",
        "spread": "schwab_bid_ask",
        "carried_forward": False,
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


def test_rest_fast_quote_spot_fail_closed_not_zero(monkeypatch):
    """PQ-001 / DFR-003 re-audit: missing last+mark → spot None, never 0.0."""
    monkeypatch.setattr(server, "get_client", lambda: object())
    monkeypatch.setattr(server, "_safe_get_quote_with_retry", lambda *_a, **_k: _RespNoSpot())

    payload = server._build_rest_fast_quote_payload("SPY", "rest_fast_quote")

    assert payload["spot"] is None
    assert payload.get("spot_source") is None
    assert payload["quote_source_detail"]["spot"] == "unavailable_missing_last_and_mark"


def test_rest_fast_quote_source_has_no_silent_zero_spot_fallback():
    import inspect

    src = inspect.getsource(server._build_rest_fast_quote_payload)
    assert "or 0.0" not in src
    assert "spot = last if" in src or "spot_source" in src


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


def test_tier_a_live_state_rest_bootstrap_row_uses_schwab_time_not_wall_clock(monkeypatch):
    """S017: Tier A GET /api/live/state REST bootstrap must not set fast_server_ts from time.time()."""
    monkeypatch.setattr(server._lmp, "get_quote", lambda _ticker: None)
    monkeypatch.setattr(server._lmp, "next_fast_generation", lambda _ticker: 99)
    monkeypatch.setattr(server, "get_client", lambda: object())
    monkeypatch.setattr(server, "_safe_get_quote_with_retry", lambda *_args, **_kwargs: _Resp())

    out = server._tier_a_live_state_dict("SPY", None)

    assert out.get("_tier") == "A_live"
    assert out["quote_ingestion"] == "rest_tier_a"
    assert out["quote_mid"] == 501.25
    assert out["mid_source"] == "schwab_quote_mark"
    assert out["fast_server_ts"] == 1_778_018_399.0
    assert out["quote_time_source"] == "schwab_rest_quote"
    assert isinstance(out["server_received_ts"], float)
