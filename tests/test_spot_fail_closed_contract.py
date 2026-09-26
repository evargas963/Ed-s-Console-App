"""Every consumer of spot price (_validate_trade, compute_confluence_features,
normalize_mc, engineer_single_snapshot, _spot_for_mc_fusion_adjustment) must fail
closed on a missing/invalid spot rather than silently computing against zero or a
stale fallback -- a repo-wide contract, checked at each of its real call sites."""
from __future__ import annotations


from lstm_data import compute_confluence_features
from ml_train import engineer_single_snapshot






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


