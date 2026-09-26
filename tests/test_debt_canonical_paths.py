"""Technical debt retirement: Monte Carlo, regime, similarity filters, encoder spot — canonical alignment."""
from __future__ import annotations


import pytest



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
    feats["liquidity.absorption_score"] = None
    feats["liquidity.continuation_score"] = None
    return build_inference_snapshot_v1_from_feature_row(
        ticker="SPY", expiry=None, as_of_ts=1.0, features=feats
    )






def _snap_raw_spot(spot):
    from features.canonical_contract import get_mvp_feature_names

    feats = {k: None for k in get_mvp_feature_names()}
    feats["price.spot"] = spot
    return {
        "snapshot_type": "InferenceSnapshotV1",
        "feature_contract_version": "v1_1m_mvp",
        "canonical_timeframe": "1m",
        "features": feats,
    }














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
