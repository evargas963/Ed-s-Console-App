"""signal_layer_v1: leakage bounds + synthetic predictive sanity."""

from __future__ import annotations

import math

import pytest

from features.signal_layer_v1 import (
    MOMENTUM_RETURN_LOOKBACKS_1M,
    SNAPSHOT_PRICE_ACTION_COLUMNS,
    compute_price_action_snapshot_columns,
    compute_signal_layer_v1,
)


def _synth_bars(n: int, t0: float = 1_000_000.0) -> list[dict]:
    bars = []
    for k in range(n):
        be = t0 + float(k + 1) * 60.0
        bs = be - 60.0
        c = 100.0 + 0.02 * float(k) + 0.15 * math.sin(k * 0.05)
        o = c - 0.01
        h = c + 0.05
        l_ = c - 0.05
        bars.append(
            {
                "bar_start_ts_utc": bs,
                "bar_end_ts_utc": be,
                "open": o,
                "high": h,
                "low": l_,
                "close": c,
                "volume": 1e6 + float(k) * 100.0,
            }
        )
    return bars


def test_no_future_bar_in_window() -> None:
    """Features at decision_ts must not use bars ending after decision_ts."""
    bars = _synth_bars(80)
    decision_ts = bars[50]["bar_end_ts_utc"]
    layer = compute_signal_layer_v1(bars[:51], decision_ts_utc=float(decision_ts), inp=None)
    assert int(layer["meta.n_bars"]) == 51
    assert layer["meta.bar_end_last"] == pytest.approx(float(bars[50]["bar_end_ts_utc"]))




def test_synthetic_trend_slope_detectable() -> None:
    """Upward drift → positive log slope (sanity)."""
    bars = _synth_bars(120)
    decision_ts = float(bars[-1]["bar_end_ts_utc"])
    layer = compute_signal_layer_v1(bars, decision_ts_utc=decision_ts, inp=None)
    sl = layer.get("ps.rolling_trend_slope_log20")
    assert sl is not None and float(sl) > 0.0


def test_missing_volume_does_not_create_synthetic_vwap_features() -> None:
    """S002: VWAP/value features must not use fake unit or zero volume."""
    bars = _synth_bars(80)
    for bar in bars:
        bar.pop("volume", None)
    decision_ts = float(bars[-1]["bar_end_ts_utc"])

    layer = compute_signal_layer_v1(bars, decision_ts_utc=decision_ts, inp=None)

    assert layer["vl.price_vs_vwap_pct"] is None
    assert layer["vl.vwap_distance_pts"] is None
    assert layer["part.relative_volume"] is None


def test_missing_ohlc_does_not_create_synthetic_multiframe_bars() -> None:
    """S003: missing high/low in 1m bars must not become synthetic 0.0 levels."""
    bars = _synth_bars(80)
    for bar in bars:
        bar.pop("high", None)
    decision_ts = float(bars[-1]["bar_end_ts_utc"])

    layer = compute_signal_layer_v1(bars, decision_ts_utc=decision_ts, inp=None)

    assert layer["mtf.trend_5m_from_1m_sign"] is None
    assert layer["mtf.bias_15m_from_1m_sign"] is None




# ── Price-action persistence cone (operator 2026-06-11) ──────────────────────


def test_momentum_returns_match_log_return_definition() -> None:
    """mom.ret_{k}m_pct = 100·ln(close_now / close_{k bars back}) — exact."""
    bars = _synth_bars(80)
    decision_ts = float(bars[-1]["bar_end_ts_utc"])
    layer = compute_signal_layer_v1(bars, decision_ts_utc=decision_ts, inp=None)
    closes = [b["close"] for b in bars]
    for k in MOMENTUM_RETURN_LOOKBACKS_1M:
        expected = 100.0 * math.log(closes[-1] / closes[-1 - k])
        assert layer[f"mom.ret_{k}m_pct"] == pytest.approx(expected)


def test_momentum_returns_honest_null_when_history_short() -> None:
    bars = _synth_bars(10)
    decision_ts = float(bars[-1]["bar_end_ts_utc"])
    layer = compute_signal_layer_v1(bars, decision_ts_utc=decision_ts, inp=None)
    assert layer["mom.ret_5m_pct"] is not None
    assert layer["mom.ret_15m_pct"] is None
    assert layer["mom.ret_60m_pct"] is None


def test_signed_impulse_run_carries_direction() -> None:
    bars = _synth_bars(80)
    # Force the last 4 closes strictly descending.
    for i, px in enumerate((101.0, 100.5, 100.2, 100.0)):
        bars[-4 + i]["close"] = px
        bars[-4 + i]["open"] = px + 0.01
        bars[-4 + i]["high"] = px + 0.05
        bars[-4 + i]["low"] = px - 0.05
    decision_ts = float(bars[-1]["bar_end_ts_utc"])
    layer = compute_signal_layer_v1(bars, decision_ts_utc=decision_ts, inp=None)
    assert layer["cnd.consecutive_impulse_signed"] is not None
    assert layer["cnd.consecutive_impulse_signed"] <= -3.0


def test_snapshot_price_action_columns_complete_and_leak_free() -> None:
    """Every persisted pa_* column maps to a real layer key; future bars excluded."""
    bars = _synth_bars(80)
    decision_ts = float(bars[50]["bar_end_ts_utc"])
    # Pass the FULL list — the function must drop bars ending after decision_ts.
    cols = compute_price_action_snapshot_columns(bars, decision_ts_utc=decision_ts)
    assert set(cols) == {c for c, _ in SNAPSHOT_PRICE_ACTION_COLUMNS}
    leak_free = compute_price_action_snapshot_columns(bars[:51], decision_ts_utc=decision_ts)
    assert cols == leak_free
    # Uptrend drift → positive momentum and trend columns.
    full = compute_price_action_snapshot_columns(bars, decision_ts_utc=float(bars[-1]["bar_end_ts_utc"]))
    assert full["pa_ret_60m_pct"] is not None and full["pa_ret_60m_pct"] > 0.0
    assert full["pa_trend_slope_log20"] is not None
    assert full["pa_mtf_trend_1m"] in (-1.0, 0.0, 1.0)


def test_snapshot_price_action_columns_honest_nulls_on_thin_history() -> None:
    bars = _synth_bars(3)
    cols = compute_price_action_snapshot_columns(
        bars, decision_ts_utc=float(bars[-1]["bar_end_ts_utc"])
    )
    assert cols["pa_ret_60m_pct"] is None
    assert cols["pa_atr_pctile_60"] is None
    assert cols["pa_ret_1m_pct"] is not None