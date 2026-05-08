from __future__ import annotations

from types import SimpleNamespace

from call_engine import _validate_trade
from lstm_data import compute_confluence_features
from mc_fusion_adjustment import normalize_mc
from ml_train import engineer_single_snapshot
from signals import _spot_for_mc_fusion_adjustment


def test_mc_fusion_spot_returns_none_when_context_spot_missing():
    assert _spot_for_mc_fusion_adjustment({}, {"features": {}}) is None
    assert _spot_for_mc_fusion_adjustment({"spot": 0}, {"features": {"price.spot": 0}}) is None


def test_mc_normalization_does_not_scale_by_synthetic_one_when_spot_missing():
    out = normalize_mc({"expected_move": 10.0, "volatility": 5.0}, spot_price=None)

    assert out["mc_expected_move"] == 0.0
    assert out["mc_volatility"] == 0.0


def test_lstm_confluence_features_fail_closed_without_spot():
    snapshots = [{"spot": 500.0} for _ in range(12)]
    snapshots[-1].pop("spot")

    out = compute_confluence_features(snapshots, 11)

    assert out["cf_momentum_5m"] == 0.0
    assert out["cf_structure_15m"] == 0.0
    assert out["cf_trend_1h"] == 0.0


def test_ml_single_snapshot_returns_none_without_positive_spot():
    assert engineer_single_snapshot({"spot": None}, {}, [], {}, "SPY") is None
    assert engineer_single_snapshot({"spot": 0}, {}, [], {}, "SPY") is None


def test_call_validation_fails_closed_without_spot_for_trade_signal():
    inp = SimpleNamespace(spot=None, call_gamma_wall=501.0, put_gamma_wall=499.0)

    out = _validate_trade(
        final_signal="long",
        inp=inp,
        regime_label="trend",
        micro_regime="bos_up",
        micro={},
        pred={},
        fusion={},
        canonical=SimpleNamespace(prob_up=0.6, prob_down=0.2, confidence=0.7),
        regime=None,
    )

    assert out["structure_valid"] is False
    assert out["structure_reason"] == "missing canonical spot"
