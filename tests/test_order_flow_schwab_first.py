"""Day 2 — order flow + spread Schwab-first (DFR-019, PQ-002, OP-015/017, etc.)."""

from __future__ import annotations

from pathlib import Path

from order_flow_engine import (
    OrderFlowEngine,
    _compute_options_flow,
    _compute_rvol,
    _compute_spread,
    _compute_top_book_pressure,
)
from server import _CandleAccumulator

ROOT = Path(__file__).resolve().parent.parent


def test_rvol_unavailable_when_avg_volume_invalid():
    data = {
        "quote": {"totalVolume": 1_000_000},
        "fundamental": {},
    }
    rvol, reason = _compute_rvol(data)
    assert rvol is None
    assert reason == "avg_volume_unavailable"


def test_rvol_returns_none_not_one_point_zero_fallback():
    """Parent fail: 2e022d0 returned 1.0 when avg_volume missing."""
    rvol, reason = _compute_rvol({"quote": {"totalVolume": 500}, "fundamental": {}})
    assert rvol is None
    assert reason == "avg_volume_unavailable"
    assert rvol != 1.0


def test_spread_pts_and_frac_units_not_mixed():
    data = {
        "quote": {"bidPrice": 500.0, "askPrice": 500.1, "mark": 500.05},
    }
    spread_d = _compute_spread(data)
    assert spread_d["spread_pts"] == 0.1
    assert spread_d["spread_frac"] is not None
    assert abs(spread_d["spread_frac"] - (0.1 / 500.05)) < 1e-6
    assert spread_d["spread_pts_source"] is not None
    assert "schwab_mark" in (spread_d["spread_frac_source"] or "")
    assert spread_d["spread_pts"] != spread_d["spread_frac"]


def test_spread_frac_fail_closed_without_mark():
    data = {"quote": {"bidPrice": 500.0, "askPrice": 500.1}}
    spread_d = _compute_spread(data)
    assert spread_d["spread_pts"] == 0.1
    assert spread_d["spread_frac"] is None


def test_options_flow_lastsize_requires_tick_mode_source():
    data = {
        "options_flow_tick_mode": True,
        "callExpDateMap": {
            "2099-05-05:0": {
                "500.0": {
                    "strikePrice": 500.0,
                    "lastSize": 50,
                    "totalVolume": 9999,
                    "delta": 0.5,
                }
            }
        },
        "putExpDateMap": {
            "2099-05-05:0": {
                "500.0": {
                    "strikePrice": 500.0,
                    "lastSize": 30,
                    "totalVolume": 8888,
                    "delta": -0.4,
                }
            }
        },
    }
    score, direction, ratio, delta_w, vol_src = _compute_options_flow(data)
    assert score is not None
    assert vol_src == "schwab_chain_lastSize_tick_mode"
    assert score == (50 - 30) / 80


def test_options_flow_default_uses_total_volume_not_last_size():
    data = {
        "callExpDateMap": {
            "2099-05-05:0": {
                "500.0": {
                    "strikePrice": 500.0,
                    "lastSize": 999,
                    "totalVolume": 10,
                    "delta": 0.5,
                }
            }
        },
        "putExpDateMap": {},
    }
    _, _, _, _, vol_src = _compute_options_flow(data)
    assert vol_src == "schwab_chain_totalVolume"


def test_top_book_pressure_emits_source_tier():
    pressure, tier = _compute_top_book_pressure(
        {"quote": {"bidSize": 100, "askSize": 50}}
    )
    assert pressure is not None
    assert tier == "schwab_quote"


def test_top_book_pressure_streaming_uses_bid_ask_size_leaves_only():
    pressure, tier = _compute_top_book_pressure(
        {"content": [{"BID_SIZE": 120, "ASK_SIZE": 80}]}
    )
    assert pressure == (120 - 80) / 200
    assert tier == "schwab_stream"


def test_top_book_pressure_ignores_non_canonical_streaming_bid_ask_size_keys():
    """Streaming CSV leaves are BID_SIZE/ASK_SIZE — not REST quote.bidSize/askSize."""
    pressure, tier = _compute_top_book_pressure(
        {"content": [{"bidSize": 100, "askSize": 50}]}
    )
    assert pressure is None
    assert tier == "unavailable"


def test_server_has_no_second_vwap_implementation():
    """Phase 2A: the server-side VWAP fallback is DELETED, not merely unused.

    `_compute_vwap_from_bars` accumulated its own Σ(tp·v)/Σv from the candle
    accumulator whenever fetch_price_levels returned vwap=None, and that number was
    persisted into snapshots and model features — a VWAP no served endpoint carried.
    The one accumulation is liquidity_value_engine.compute_session_vwap_path.
    """
    import server as S

    assert not hasattr(S, "_compute_vwap_from_bars"), (
        "the second VWAP implementation is back in server.py"
    )
    text = (ROOT / "server.py").read_text(encoding="utf-8")
    assert "cum_tp_vol" not in text, "an inline VWAP accumulation reappeared in server.py"


def test_candle_accumulator_session_reset_volume_source():
    acc = _CandleAccumulator(bar_seconds=60, max_bars=5)
    acc.tick("SPY", 500.0, 1000.0, total_volume=1000.0)
    acc.tick("SPY", 501.0, 1060.0, total_volume=500.0)
    assert acc.get_bars_source("SPY") == "schwab_quote_totalVolume_session_reset"


def test_order_flow_engine_no_rvol_one_point_zero_in_source():
    text = (ROOT / "order_flow_engine.py").read_text(encoding="utf-8")
    assert "return 1.0  # no avg available" not in text
    assert "rvol or 1.0" not in text


def test_order_flow_compute_exposes_split_spread_fields():
    out = OrderFlowEngine().compute({"quote": {"bidPrice": 10.0, "askPrice": 10.2, "mark": 10.1}})
    assert out["spread_pts"] == 0.2
    assert out["spread_frac"] is not None
    assert out["spread_pts"] != out["spread_frac"]
