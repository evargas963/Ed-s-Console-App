"""prediction_engine chunk-1: I-01 contracts for empirical withholding and canonical requirement."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from prediction_engine import (
    _literal_empirical_horizon,
    _overlay_multi_horizon_ml_on_product_triplets,
    _pack_horizon_row,
    compute_prediction_core,
)
from signal_types import SignalInput
from tests.mvp_test_fixtures import minimal_mvp_features


def test_literal_empirical_horizon_withholds_when_insufficient_labeled():
    probs, src, _note, n = _literal_empirical_horizon([], "outcome_5c", 5)
    assert probs is None
    assert src == "insufficient_labeled_outcome_5c"
    assert n == 0


def test_pack_horizon_row_withhold_reason_no_data_when_labeled_count_zero():
    """LIVE-UI-D: empirical row with zero labeled samples must stamp withhold_reason='no_data'
    so the UI can render 'NO DATA' instead of a generic WAIT — distinguishes 'empty histogram'
    from 'insufficient samples' from 'data-quality anomaly'.
    """
    row = _pack_horizon_row(
        None, "insufficient_labeled_outcome_5c", "5c", method="hist", empirical_forward_bars=5, labeled_count=0
    )
    assert row["up"] is None and row["down"] is None and row["flat"] is None
    assert row["labeled_count"] == 0
    assert row["withhold_reason"] == "no_data"


def test_pack_horizon_row_withhold_reason_min_samples_when_below_threshold():
    """LIVE-UI-D: empirical row with some labeled samples but below MIN_SAMPLES_STATISTICAL
    must stamp withhold_reason='min_samples' — distinct from no_data."""
    from prediction_engine import MIN_SAMPLES_STATISTICAL

    n_below = max(1, MIN_SAMPLES_STATISTICAL - 1)
    row = _pack_horizon_row(
        None, "insufficient_labeled_outcome_5c", "5c",
        method="hist", empirical_forward_bars=5, labeled_count=n_below,
    )
    assert row["up"] is None
    assert row["labeled_count"] == n_below
    assert row["min_samples_required"] == MIN_SAMPLES_STATISTICAL
    assert row["withhold_reason"] == "min_samples"


def test_pack_horizon_row_withhold_reason_data_quality_when_count_ok_but_probs_none():
    """LIVE-UI-D: anomalous path — labeled_count >= MIN_SAMPLES_STATISTICAL but probs are None.
    Should not normally happen; producer stamps 'data_quality' so the operator-visible audit
    surfaces the anomaly instead of treating it like a min_samples withhold."""
    from prediction_engine import MIN_SAMPLES_STATISTICAL

    row = _pack_horizon_row(
        None, "hist_ok", "5c",
        method="hist", empirical_forward_bars=5, labeled_count=MIN_SAMPLES_STATISTICAL + 10,
    )
    assert row["up"] is None
    assert row["withhold_reason"] == "data_quality"


def test_pack_horizon_row_no_withhold_reason_when_probs_present():
    """LIVE-UI-D regression: when probs is non-None, withhold_reason MUST NOT be stamped —
    the UI checks for its presence to discriminate withhold vs real WAIT verdict."""
    row = _pack_horizon_row(
        {"up": 0.45, "down": 0.3, "flat": 0.25}, "hist", "5c",
        method="hist", empirical_forward_bars=5, labeled_count=50,
    )
    assert row["up"] == 0.45
    assert "withhold_reason" not in row, (
        f"withhold_reason leaked into non-withhold row: {row!r}"
    )
    # Card-fidelity lock (2026-07-05): populated rows must carry their sample
    # count too — the EMPIRICAL chip's "N similar setups" operator text reads
    # hp.labeled_count and was permanently generic while only withheld rows
    # stamped it.
    assert row["labeled_count"] == 50


def test_overlay_withholds_product_triplets_when_fusion_missing(monkeypatch):
    """Horizon cards: fusion-only product path — no empirical fallback by default."""
    monkeypatch.delenv("ED_MH_EMPIRICAL_SUPPORT", raising=False)
    empirical = {
        "1c": (0.6, 0.2, 0.2),
        "5c": (0.6, 0.2, 0.2),
        "15c": (0.6, 0.2, 0.2),
        "60c": (0.6, 0.2, 0.2),
    }
    tri, src, _events = _overlay_multi_horizon_ml_on_product_triplets(empirical, None)
    assert tri["1c"] == (None, None, None)
    assert src["1c"] == "fusion_unavailable"
    assert src["5c"] == "fusion_unavailable"


def test_compute_prediction_core_requires_canonical_forecast():
    inp = SignalInput(
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
        zone_since_bars_1m=5,
        zone_since_bars_5m=1,
        call_gamma_wall=451.0,
        put_gamma_wall=449.0,
        call_delta_wall=None,
        put_delta_wall=None,
        gamma_inflection=None,
        delta_inflection=None,
        call_oi_wall=None,
        put_oi_wall=None,
        call_vanna_wall=None,
        put_vanna_wall=None,
        pin_width_pts=2.0,
        dist_call_gamma_wall=1.0,
        dist_put_gamma_wall=-1.0,
        dist_call_delta_wall=None,
        dist_put_delta_wall=None,
        dist_gamma_inflection=None,
        dist_delta_inflection=None,
        dist_call_oi_wall=None,
        dist_put_oi_wall=None,
        dist_call_vanna_wall=None,
        dist_put_vanna_wall=None,
        nearest_above_name="CGW",
        nearest_above_val=451.0,
        nearest_above_dist=1.0,
        nearest_below_name="PGW",
        nearest_below_val=449.0,
        nearest_below_dist=1.0,
        net_gamma=1000.0,
        net_delta=500.0,
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
        put_call_oi_ratio=0.9,
        oi_center=None,
        recent_crosses=[],
        ceiling_tests_today=0,
        floor_tests_today=0,
        spy_chg_pct=0.0,
        qqq_chg_pct=0.0,
        iwm_chg_pct=0.0,
        vix_level=18.0,
        mins_to_close=240.0,
        em_upper=452.0,
        em_lower=448.0,
        order_flow_score=0.0,
        order_flow_direction="neutral",
        order_flow_readiness="yellow",
    )
    snapshot = {
        "as_of_ts": 1_700_000_000.0,
        "features": minimal_mvp_features(zone="pin_bull", spot=450.0),
    }

    with pytest.raises(ValueError, match="canonical=CanonicalForecast"):
        compute_prediction_core(
            inp,
            MagicMock(),
            canonical=None,
            inference_snapshot_v1=snapshot,
        )
