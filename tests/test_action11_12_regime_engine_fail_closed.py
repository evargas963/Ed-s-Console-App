"""Action 11.12: regime_engine fail-closed on zero evidence and missing zone bars."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from regime_engine import classify_regime, _score_breakout
from signal_types import RulesCard, SignalInput
from tests.mvp_test_fixtures import minimal_mvp_features

ROOT = Path(__file__).resolve().parent.parent
REGIME_ENGINE = (ROOT / "regime_engine.py").read_text(encoding="utf-8")


def _inp(**overrides) -> SignalInput:
    base = dict(
        ticker="SPY",
        timeframe="1m",
        expiry=None,
        dte=None,
        spot=450.0,
        candle_open=449.5,
        candle_high=450.2,
        candle_low=449.3,
        candle_close=450.0,
        candle_direction="up",
        candle_body_pts=0.5,
        candle_range_pts=0.9,
        vwap=449.8,
        vwap_side="above",
        vwap_dist_pts=0.2,
        zone="pin_bull",
        prev_zone="pin_bull",
        zone_since_bars=5,
        zone_since_bars_1m=None,
        zone_since_bars_5m=None,
        call_gamma_wall=452.0,
        put_gamma_wall=448.0,
        call_delta_wall=None,
        put_delta_wall=None,
        gamma_inflection=None,
        delta_inflection=None,
        call_oi_wall=None,
        put_oi_wall=None,
        call_vanna_wall=None,
        put_vanna_wall=None,
        pin_width_pts=2.0,
        dist_call_gamma_wall=2.0,
        dist_put_gamma_wall=-2.0,
        dist_call_delta_wall=None,
        dist_put_delta_wall=None,
        dist_gamma_inflection=None,
        dist_delta_inflection=None,
        dist_call_oi_wall=None,
        dist_put_oi_wall=None,
        dist_call_vanna_wall=None,
        dist_put_vanna_wall=None,
        nearest_above_name="CGW",
        nearest_above_val=452.0,
        nearest_above_dist=2.0,
        nearest_below_name="PGW",
        nearest_below_val=448.0,
        nearest_below_dist=2.0,
        net_gamma=1000.0,
        net_delta=200.0,
        net_vanna=None,
        charm_net=None,
        charm_direction="neutral",
        charm_drift_toward=450.0,
        charm_magnitude="moderate",
        dex_magnitude="moderate",
        iv_level=0.15,
        iv_direction="flat",
        realized_vol=None,
        atr=1.5,
        put_call_oi_ratio=1.0,
        oi_center=None,
        recent_crosses=[],
        ceiling_tests_today=0,
        floor_tests_today=0,
        spy_chg_pct=0.05,
        qqq_chg_pct=0.04,
        iwm_chg_pct=0.03,
        vix_level=18.0,
        mins_to_close=240.0,
        em_upper=452.0,
        em_lower=448.0,
        order_flow_score=0.0,
        order_flow_direction="neutral",
        order_flow_readiness="yellow",
    )
    base.update(overrides)
    return SignalInput(**base)


def _rules():
    return RulesCard(
        headline="Test",
        headline_1m="",
        detail="",
        zone_label="UP",
        zone_color="#fff",
        signal="wait",
        conviction="low",
        alerts=[],
        micro=SimpleNamespace(regime="UNKNOWN"),
    )


def test_regime_engine_no_zone_since_bars_or_zero_pattern():
    assert "(inp.zone_since_bars_1m or inp.zone_since_bars) or 0" not in REGIME_ENGINE


def test_classify_returns_unknown_when_all_scores_zero():
    mvp = minimal_mvp_features(zone="pin_bull")
    zero = {k: 0.0 for k in (
        "pinning", "acceleration", "breakout", "mean_reversion",
        "vol_compression", "vol_expansion", "trend_continuation", "reversal_prone",
    )}

    with patch("regime_engine._score_pinning", return_value=(0.0, [], [])), patch(
        "regime_engine._score_acceleration", return_value=(0.0, [], [])
    ), patch("regime_engine._score_breakout", return_value=(0.0, [], [])), patch(
        "regime_engine._score_mean_reversion", return_value=(0.0, [], [])
    ), patch("regime_engine._score_vol_compression", return_value=(0.0, [], [])
    ), patch("regime_engine._score_vol_expansion", return_value=(0.0, [], [])
    ), patch("regime_engine._score_trend_continuation", return_value=(0.0, [], [])
    ), patch("regime_engine._score_reversal_prone", return_value=(0.0, [], [])):
        out = classify_regime(_inp(), _rules(), mvp_features=mvp)

    assert out.primary == "unknown"
    assert out.confidence == "low"


def test_breakout_scorer_skips_fresh_zone_when_bars_unknown():
    from regime_engine import _micro_regimes

    inp = _inp(zone="breakout", prev_zone="pin_bull", zone_since_bars_1m=None, zone_since_bars=None)
    score, support, _contra = _score_breakout(
        inp, "UNKNOWN", _micro_regimes(), minimal_mvp_features()
    )
    assert score == 0.0
    assert not any("fresh breakout" in s for s in support)
