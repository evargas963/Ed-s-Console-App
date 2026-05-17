"""Action 12.13: signal_layer_v1 fail-closed MTF signs + direction probs + fusion blend."""

from __future__ import annotations

import math
from types import SimpleNamespace
from unittest.mock import patch

import bayesian_fusion
import pytest

from features.signal_layer_v1 import (
    compute_signal_layer_v1,
    layer_direction_policy,
    signal_layer_v1_to_direction_probs,
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


def test_signal_layer_v1_to_direction_probs_returns_none_when_n_bars_lt_25() -> None:
    layer = {"meta.n_bars": 24, "mtf.trend_1m_sign": 1.0}
    assert signal_layer_v1_to_direction_probs(layer) is None


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


def test_layer_direction_policy_handles_none_mtf_signs() -> None:
    layer = {
        "ps.rolling_trend_slope_log20": 0.001,
        "mtf.trend_1m_sign": None,
        "mtf.trend_5m_from_1m_sign": None,
        "mtf.bias_15m_from_1m_sign": None,
    }
    assert layer_direction_policy(layer) == "wait"


def _fuse_with_signal_layer(sl: dict) -> bayesian_fusion.FusionPayload:
    regime = SimpleNamespace(primary="pinning", confidence="medium")
    rules = SimpleNamespace(signal="wait", conviction="medium")
    xgb = SimpleNamespace(
        available=True,
        prob_up=0.55,
        prob_down=0.30,
        prob_flat=0.15,
        dominant_class="up",
        confidence_label="medium",
        continuation_support=0.2,
        reversal_support=0.1,
    )
    lstm = SimpleNamespace(
        available=True,
        prob_up=0.52,
        prob_down=0.33,
        prob_flat=0.15,
        continuation_support=0.18,
        reversal_support=0.12,
    )
    tr = SimpleNamespace(available=False)
    mc = SimpleNamespace(
        available=True,
        containment_prob=0.55,
        expansion_prob=0.45,
        n_paths=1000,
        horizon_bars=20,
        assumptions={"garch_active": False, "blended_sigma": 1.2},
    )
    return bayesian_fusion.fuse(
        regime, xgb, lstm, tr, mc, rules, signal_layer_v1=sl
    )


def test_bayesian_fusion_skips_blend_when_signal_layer_returns_none() -> None:
    sl = {"meta.n_bars": 30, "mtf.trend_1m_sign": 1.0}
    without_sl = _fuse_with_signal_layer({"meta.n_bars": 0})
    with patch(
        "features.signal_layer_v1.signal_layer_v1_to_direction_probs",
        return_value=None,
    ):
        with_sl = _fuse_with_signal_layer(sl)
    assert with_sl.signal_layer_v1_fusion is None
    assert with_sl.prob_up == pytest.approx(without_sl.prob_up)
    assert with_sl.prob_down == pytest.approx(without_sl.prob_down)
    assert with_sl.prob_flat == pytest.approx(without_sl.prob_flat)
