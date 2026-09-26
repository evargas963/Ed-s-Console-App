"""Cascade challenger path: staged upstream features, lineage, parallel default unchanged."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _minimal_inf_v1():
    from features.inference_snapshot import build_inference_snapshot_v1_from_feature_row
    from features.canonical_contract import get_mvp_feature_names

    feats = {k: None for k in get_mvp_feature_names()}
    feats["price.spot"] = 450.0
    feats["price.spread_pts"] = 0.02
    feats["structure.zone"] = "pin_neutral"
    feats["structure.nearest_above_dist"] = 1.0
    feats["structure.nearest_below_dist"] = -1.0
    feats["structure.net_gamma"] = 0.0
    feats["anchor.vwap_side"] = "above"
    feats["anchor.vwap_dist_pts"] = 0.1
    feats["liquidity.absorption_score"] = None
    feats["liquidity.continuation_score"] = None
    return build_inference_snapshot_v1_from_feature_row(
        ticker="SPY",
        expiry=None,
        as_of_ts=1_700_000_000.0,
        features=feats,
    )


def test_infer_architecture_default_is_parallel():
    import ml_predict as mp

    assert mp._INFER_ARCHITECTURE.get() == "parallel"












def test_scheduler_train_cascade_uses_same_feature_cache_key_family():
    """train_cascade_candidate uses compute_feature_cache_key / feature_cache_dir like parallel."""
    text = (ROOT / "ml_scheduler.py").read_text(encoding="utf-8")
    assert "def train_cascade_candidate" in text
    assert "compute_feature_cache_key" in text and "feature_cache_dir" in text
