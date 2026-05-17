"""Actions 12.1–12.5 + 11.1d: fail-closed fixes in prediction/MH/vol/rules/news paths."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from prediction_engine import (
    _fusion_snap_triplet,
    _overlay_multi_horizon_ml_on_product_triplets,
    _tri_probs,
)
from multi_horizon_decision import _infer_trade_mode, _norm_triplet
from volatility_regime import classify_volatility_regime
from math_exposure_core import compute_beta
from tests.mvp_test_fixtures import minimal_mvp_features
from signal_types import SignalInput

ROOT = Path(__file__).resolve().parent.parent


def _inp(**kw) -> SignalInput:
    base = dict(
        ticker="SPY", timeframe="1m", expiry=None, dte=None, spot=450.0,
        candle_open=449.5, candle_high=450.2, candle_low=449.3, candle_close=450.0,
        candle_direction="up", candle_body_pts=0.5, candle_range_pts=0.9,
        vwap=449.8, vwap_side="above", vwap_dist_pts=0.2,
        zone="pin_bull", prev_zone="pin_bull",
        zone_since_bars=5, zone_since_bars_1m=None, zone_since_bars_5m=None,
        call_gamma_wall=452.0, put_gamma_wall=448.0,
        call_delta_wall=None, put_delta_wall=None,
        gamma_inflection=None, delta_inflection=None,
        call_oi_wall=None, put_oi_wall=None, call_vanna_wall=None, put_vanna_wall=None,
        pin_width_pts=2.0, dist_call_gamma_wall=2.0, dist_put_gamma_wall=-2.0,
        dist_call_delta_wall=None, dist_put_delta_wall=None,
        dist_gamma_inflection=None, dist_delta_inflection=None,
        dist_call_oi_wall=None, dist_put_oi_wall=None,
        dist_call_vanna_wall=None, dist_put_vanna_wall=None,
        nearest_above_name="CGW", nearest_above_val=452.0, nearest_above_dist=2.0,
        nearest_below_name="PGW", nearest_below_val=448.0, nearest_below_dist=2.0,
        net_gamma=1000.0, net_delta=200.0, net_vanna=None,
        charm_net=None, charm_direction="neutral", charm_drift_toward=450.0,
        charm_magnitude="moderate", dex_magnitude="moderate",
        iv_level=0.15, iv_direction="flat", realized_vol=None, atr=1.5,
        put_call_oi_ratio=1.0, oi_center=None,
        recent_crosses=[], ceiling_tests_today=0, floor_tests_today=0,
        spy_chg_pct=0.05, qqq_chg_pct=0.04, iwm_chg_pct=0.03,
        vix_level=None, vix_vs_prev=None, mins_to_close=None,
        em_upper=452.0, em_lower=448.0,
        order_flow_score=0.0, order_flow_direction="neutral", order_flow_readiness="yellow",
    )
    base.update(kw)
    return SignalInput(**base)


def test_fusion_snap_triplet_none_when_probs_missing():
    snap = SimpleNamespace(available=True, fusion_available=True)
    assert _fusion_snap_triplet(snap) is None


def test_overlay_uses_empirical_when_fusion_triplet_missing():
    empirical = {hz: (0.6, 0.2, 0.2) for hz in ("1c", "5c", "15c", "60c")}
    snap = SimpleNamespace(fusion_available=True)
    bundle = SimpleNamespace(by_horizon={"1c": snap, "5c": snap, "15c": snap, "60c": snap})
    out, src, _ev = _overlay_multi_horizon_ml_on_product_triplets(empirical, bundle)
    assert src["1c"] == "fusion_directional_missing"
    assert out["1c"] == empirical["1c"]


def test_tri_probs_none_when_dict_incomplete():
    assert _tri_probs({"up": 0.5}) == (None, None, None)


def test_norm_triplet_none_when_inputs_missing():
    assert _norm_triplet(None, None, None) is None


def test_infer_trade_mode_no_fabricated_mins():
    assert _infer_trade_mode(SimpleNamespace(mins_to_close=None)) == "intraday"


def test_compute_beta_r_squared_none_when_ticker_variance_zero():
    spy = [0.1, -0.1, 0.2, -0.2, 0.1]
    ticker = [0.0, 0.0, 0.0, 0.0, 0.0]
    out = compute_beta(ticker, spy)
    assert out["r_squared"] is None


def test_vol_regime_default_not_trade_permissive():
    mvp = minimal_mvp_features(zone="pin_bull")
    out = classify_volatility_regime(
        _inp(realized_vol=None, atr=None, iv_level=None, vix_level=None),
        mvp_features=mvp,
    )
    assert out.vol_regime == "unknown"
    assert out.trade_permissive is False


def test_prediction_engine_no_fusion_prob_one_third_default():
    text = (ROOT / "prediction_engine.py").read_text(encoding="utf-8")
    assert 'getattr(snap, "prob_up", 1.0 / 3.0)' not in text
