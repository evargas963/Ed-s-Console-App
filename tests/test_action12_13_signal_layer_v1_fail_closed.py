"""Action 12.13: signal_layer_v1 fail-closed MTF signs + direction probs + fusion blend."""

from __future__ import annotations

import math
from types import SimpleNamespace


from features.signal_layer_v1 import (
    compute_signal_layer_v1,
)


def _synth_bars(n: int, t0: float = 1_000_000.0) -> list[dict]:
    bars = []
    for k in range(n):
        be = t0 + float(k + 1) * 60.0
        bs = be - 60.0
        c = 100.0 + 0.02 * float(k) + 0.15 * math.sin(k * 0.05)
        bars.append(
            {
                "bar_start_ts_utc": bs,
                "bar_end_ts_utc": be,
                "open": c - 0.01,
                "high": c + 0.05,
                "low": c - 0.05,
                "close": c,
                "volume": 1e6 + float(k) * 100.0,
            }
        )
    return bars






def test_compute_signal_layer_v1_missing_last_close_sets_meta_error() -> None:
    bars = _synth_bars(30)
    bars[-1]["close"] = None
    decision_ts = float(bars[-1]["bar_end_ts_utc"])
    layer = compute_signal_layer_v1(bars, decision_ts_utc=decision_ts, inp=None)
    assert layer.get("meta.error") == "missing_last_close"
    assert layer.get("ps.rolling_trend_slope_log20") is None


def test_signal_layer_f_rejects_nan() -> None:
    from pathlib import Path

    from features.signal_layer_v1 import _f

    assert _f(float("nan")) is None
    assert _f(float("inf")) is None
    src = Path(__file__).resolve().parents[1] / "features" / "signal_layer_v1.py"
    body = src.read_text(encoding="utf-8")
    assert "return float_finite_or_none(x)" in body
    assert "math.isnan" not in body.split("def _f")[1].split("\ndef ")[0]


def test_vwap_source_session_or_absent() -> None:
    bars = _synth_bars(80)
    decision_ts = float(bars[-1]["bar_end_ts_utc"])
    layer_absent = compute_signal_layer_v1(bars, decision_ts_utc=decision_ts, inp=None)
    assert layer_absent.get("meta.vwap_source") is None
    assert layer_absent.get("vl.price_vs_vwap_pct") is None
    assert layer_absent.get("vl.vwap_distance_pts") is None
    assert layer_absent.get("vl.vwap_zscore") is None
    inp = SimpleNamespace(vwap=101.5)
    layer_session = compute_signal_layer_v1(bars, decision_ts_utc=decision_ts, inp=inp)
    assert layer_session.get("meta.vwap_source") == "session"
    assert layer_session.get("vl.price_vs_vwap_pct") is not None


def test_mtf_trend_signs_none_when_aggregated_bars_insufficient() -> None:
    bars = _synth_bars(12)
    decision_ts = float(bars[-1]["bar_end_ts_utc"])
    layer = compute_signal_layer_v1(bars, decision_ts_utc=decision_ts, inp=None)
    assert layer["mtf.trend_5m_from_1m_sign"] is None
    assert layer["mtf.bias_15m_from_1m_sign"] is None


def test_mtf_alignment_state_none_when_any_trend_sign_missing() -> None:
    bars = _synth_bars(12)
    decision_ts = float(bars[-1]["bar_end_ts_utc"])
    layer = compute_signal_layer_v1(bars, decision_ts_utc=decision_ts, inp=None)
    assert layer["mtf.alignment_state"] is None






