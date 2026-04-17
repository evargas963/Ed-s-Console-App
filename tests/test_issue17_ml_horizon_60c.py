"""Issue 17: 60c is first-class for ML (artifacts, labels, rule features, meta horizon label)."""

from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path

from ml_horizon import ML_HORIZON_SLUGS, target_definition
from ml_train import engineer_features, meta_path, model_path


def test_ml_train_artifact_paths_60c():
    assert model_path("SPY", Path("models"), ml_horizon_slug="60c").name == "xgb_SPY_60c.pkl"
    assert meta_path("SPY", Path("models"), ml_horizon_slug="60c").name == "xgb_SPY_60c_meta.json"


def test_target_definition_60c():
    td = target_definition("60c")
    assert "outcome_60c" in td
    assert "60 min" in td


def test_60c_in_product_horizon_tuple():
    assert "60c" in ML_HORIZON_SLUGS
    assert ML_HORIZON_SLUGS[-1] == "60c"


def test_engineer_features_does_not_derive_rules_60c_from_empirical_preds():
    n = 5
    df = pd.DataFrame(
        {
            "spot": [100.0] * n,
            "et_hour": [10] * n,
            "et_minute": [30] * n,
            "ticker": ["SPY"] * n,
            "candle_body_pts": [0.1] * n,
            "candle_range_pts": [0.2] * n,
            "nearest_above_dist": [1.0] * n,
            "nearest_below_dist": [1.0] * n,
            "pred_60c_up_prob": np.linspace(0.2, 0.5, n),
            "pred_60c_down_prob": np.linspace(0.5, 0.2, n),
            "pred_60c_flat_prob": [0.3] * n,
        }
    )
    _, names, _, _ = engineer_features(df)
    assert "rules_60c_up" not in names
    assert "rules_60c_spread" not in names
    assert "rules_60c_confidence" not in names


def test_transformer_meta_horizon_label_60c():
    from transformer_model import _horizon_label_from_meta

    assert _horizon_label_from_meta({"target_column": "outcome_60c"}) == "60c"


def test_build_manifest_accepts_60c_suffix():
    from training_cache import build_manifest

    m = build_manifest(
        ticker="spy",
        architecture="parallel",
        scheduler_cache_key="k",
        feature_cache_key="fk",
        data_fp={"min_ts_utc": 1, "max_ts_utc": 2, "row_count": 3},
        trained_at="t",
        artifact_rel_paths={},
        artifact_sha256={},
        training_code_fingerprint="c",
        evaluation={},
        ml_horizon_suffix="60c",
    )
    assert m.get("ml_horizon_suffix") == "60c"
