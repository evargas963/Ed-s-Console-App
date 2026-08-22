"""Technical debt retirement: Monte Carlo, regime, similarity filters, encoder spot — canonical alignment."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from features.monte_carlo_stack_input import MonteCarloStackInputError, resolve_monte_carlo_stack_inputs
from features.regime_mvp_context import mvp_zone


def _snap(spot: float):
    from features.inference_snapshot import build_inference_snapshot_v1_from_feature_row
    from features.canonical_contract import get_mvp_feature_names

    feats = {k: None for k in get_mvp_feature_names()}
    feats["price.spot"] = spot
    feats["price.spread_pts"] = 0.01
    feats["structure.zone"] = "pin_neutral"
    feats["structure.nearest_above_dist"] = 1.0
    feats["structure.nearest_below_dist"] = 1.0
    feats["structure.net_gamma"] = 0.0
    feats["anchor.vwap_side"] = "above"
    feats["anchor.vwap_dist_pts"] = 0.0
    feats["liquidity.range_imbalance_stall_score"] = None
    feats["liquidity.range_imbalance_push_score"] = None
    return build_inference_snapshot_v1_from_feature_row(
        ticker="SPY", expiry=None, as_of_ts=1.0, features=feats
    )


def test_monte_carlo_uses_canonical_spot_only():
    inp = SimpleNamespace(spot=450.0, em_upper=460.0, em_lower=440.0, call_gamma_wall=1.0, put_gamma_wall=1.0)
    ctx = resolve_monte_carlo_stack_inputs(inp, _snap(450.0))
    assert ctx["spot"] == 450.0


def test_monte_carlo_fail_closed_on_spot_mismatch():
    inp = SimpleNamespace(spot=451.0, em_upper=460.0, em_lower=440.0, call_gamma_wall=1.0, put_gamma_wall=1.0)
    with pytest.raises(MonteCarloStackInputError):
        resolve_monte_carlo_stack_inputs(inp, _snap(450.0))


def _snap_raw_spot(spot):
    from features.canonical_contract import get_mvp_feature_names

    feats = {k: None for k in get_mvp_feature_names()}
    feats["price.spot"] = spot
    return {
        "snapshot_type": "InferenceSnapshotV1",
        "feature_contract_version": "v1_1m_range_imbalance",
        "canonical_timeframe": "1m",
        "features": feats,
    }


@pytest.mark.parametrize("bad_spot", [float("inf"), float("nan"), -1.0, 0.0])
def test_monte_carlo_rejects_non_positive_finite_canonical_spot(bad_spot):
    inp = SimpleNamespace(spot=450.0)
    with pytest.raises(MonteCarloStackInputError):
        resolve_monte_carlo_stack_inputs(inp, _snap_raw_spot(bad_spot))


def test_monte_carlo_non_canonical_nan_em_upper_stripped_to_none():
    inp = SimpleNamespace(
        spot=450.0,
        em_upper=float("nan"),
        em_lower=440.0,
        call_gamma_wall=1.0,
        put_gamma_wall=1.0,
    )
    ctx = resolve_monte_carlo_stack_inputs(inp, _snap(450.0))
    assert ctx["em_upper"] is None
    assert ctx["em_lower"] == 440.0


def test_monte_carlo_fail_closed_missing_canonical_spot():
    from features.inference_snapshot import build_inference_snapshot_v1_from_feature_row
    from features.canonical_contract import get_mvp_feature_names

    feats = {k: None for k in get_mvp_feature_names()}
    snap = build_inference_snapshot_v1_from_feature_row(ticker="SPY", expiry=None, as_of_ts=1.0, features=feats)
    inp = SimpleNamespace(spot=450.0)
    with pytest.raises(MonteCarloStackInputError):
        resolve_monte_carlo_stack_inputs(inp, snap)


def test_mvp_zone_reads_canonical_only():
    mvp = {"structure.zone": "pin_neutral"}
    assert mvp_zone(mvp) == "pin_neutral"


def test_similar_setup_filters_align_with_inference_snapshot_not_signalinput():
    """High-risk SQL filter params must come from MVP row (same helper as fusion overlay)."""
    from features.fusion_model_input import similar_setup_filters_from_canonical_features

    inf = _snap(450.0)
    f = similar_setup_filters_from_canonical_features(inf["features"])
    assert f["zone"] == "pin_neutral"
    assert f["vwap_side"] == "above"
    assert f["nearest_above_dist"] is not None


def test_production_default_parallel_unchanged_in_signals_doc():
    import signals

    src = open(signals.__file__, encoding="utf-8").read()
    assert "parallel" in src.lower() or "run_unified_stack_ml_once" in src


def test_transformer_prepare_sequence_accepts_reference_spot():
    from transformer_model import _prepare_sequence

    class _Inp:
        spot = 100.0
        net_gamma = 0.0
        net_delta = 0.0
        dist_call_gamma_wall = 0.0
        dist_put_gamma_wall = 0.0
        vix_level = 15.0

    class _C:
        pass

    candles = [_C() for _ in range(30)]
    for i, c in enumerate(candles):
        c.open = c.high = c.low = c.close = 100.0 + i * 0.01
        c.volume = 1.0
    seq = _prepare_sequence(candles, _Inp(), 200.0)
    assert seq is not None
    assert abs(seq[0]["position"]) > 0.01


def test_prepare_sequence_does_not_read_inp_spot_for_normalization():
    """Explicit reference_spot governs; wrong inp.spot must not change encoded position scale."""
    import inspect

    from transformer_model import _prepare_sequence

    assert "inp.spot" not in inspect.getsource(_prepare_sequence)

    class _Inp:
        spot = 999.0
        net_gamma = 0.0
        net_delta = 0.0
        dist_call_gamma_wall = 0.0
        dist_put_gamma_wall = 0.0
        vix_level = 15.0

    class _C:
        pass

    candles = [_C() for _ in range(30)]
    for i, c in enumerate(candles):
        c.open = c.high = c.low = c.close = 100.0 + i * 0.01
        c.volume = 1.0
    seq_a = _prepare_sequence(candles, _Inp(), 200.0)

    class _Inp2:
        spot = 50.0
        net_gamma = 0.0
        net_delta = 0.0
        dist_call_gamma_wall = 0.0
        dist_put_gamma_wall = 0.0
        vix_level = 15.0

    seq_b = _prepare_sequence(candles, _Inp2(), 200.0)
    assert seq_a == seq_b


def test_prepare_sequence_requires_reference_spot_positional():
    from transformer_model import _prepare_sequence

    class _Inp:
        spot = 100.0
        net_gamma = net_delta = 0.0
        dist_call_gamma_wall = dist_put_gamma_wall = 0.0
        vix_level = 15.0

    class _C:
        pass

    candles = [_C() for _ in range(30)]
    for c in candles:
        c.open = c.high = c.low = c.close = 100.0
        c.volume = 1.0
    with pytest.raises(TypeError):
        _prepare_sequence(candles, _Inp())


def test_canonical_reference_spot_first_bar_only():
    from lstm_data import canonical_reference_spot_from_sequence_window_first_bar

    assert canonical_reference_spot_from_sequence_window_first_bar([{"spot": 450.0}]) == 450.0
    with pytest.raises(ValueError):
        canonical_reference_spot_from_sequence_window_first_bar([{"spot": None}])
    with pytest.raises(ValueError):
        canonical_reference_spot_from_sequence_window_first_bar([{"spot": 0}])


def test_inference_and_training_sources_use_canonical_reference_helpers():
    """Production-relevant modules must wire explicit first-bar ref via lstm_data helpers."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    mp = (root / "ml_predict.py").read_text(encoding="utf-8")
    assert "canonical_reference_spot_from_merged_window" in mp
    tt = (root / "transformer_train.py").read_text(encoding="utf-8")
    assert "canonical_reference_spot_from_sequence_window_first_bar" in tt
    ld = (root / "lstm_data.py").read_text(encoding="utf-8")
    assert "canonical_reference_spot_from_sequence_window_first_bar" in ld
    sch = (root / "ml_scheduler.py").read_text(encoding="utf-8")
    assert "canonical_reference_spot_from_sequence_window_first_bar" in sch
