"""Issue 15: 5c (and other slugs) are first-class in artifact names, data loading, and manifests."""
from __future__ import annotations

from pathlib import Path


def test_ml_train_paths_5c():
    from ml_train import meta_path, model_path

    assert model_path("SPY", Path("models"), ml_horizon_slug="5c").name == "xgb_SPY_5c.pkl"
    assert meta_path("SPY", Path("models"), ml_horizon_slug="5c").name == "xgb_SPY_5c_meta.json"


def test_build_manifest_horizon_field():
    from training_cache import build_manifest
    from features.training_canonical_input import training_canonical_lineage_header

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
        ml_horizon_suffix="5c",
    )
    assert m.get("ml_horizon_suffix") == "5c"
    assert m.get("canonical_feature_contract_version") == training_canonical_lineage_header()[
        "canonical_feature_contract_version"
    ]


def test_manifest_horizon_mismatch_invalidates_skip():
    from training_cache import compute_feature_cache_key, manifest_matches_current
    from features.training_canonical_input import training_canonical_lineage_header
    from ml_horizon import outcome_column

    lineage = training_canonical_lineage_header()
    data_fp = {
        "row_count": 1,
        "min_ts_utc": None,
        "max_ts_utc": None,
        "table": "snapshots_1m_normalized",
        "timeframe": "1m",
        "ticker": "SPY",
    }
    code_fp = "c"
    ticker = "SPY"
    fk_1c = compute_feature_cache_key(ticker, data_fp, code_fp, target_column=outcome_column("1c"))
    fk_5c = compute_feature_cache_key(ticker, data_fp, code_fp, target_column=outcome_column("5c"))

    assert not manifest_matches_current(
        {
            **lineage,
            "scheduler_cache_key": "k",
            "data_fingerprint": data_fp,
            "ml_horizon_suffix": "1c",
            "feature_cache_key": fk_1c,
        },
        "k",
        data_fp,
        code_fp,
        ticker,
        ml_horizon_suffix="5c",
    )
    assert manifest_matches_current(
        {
            **lineage,
            "scheduler_cache_key": "k",
            "data_fingerprint": data_fp,
            "ml_horizon_suffix": "5c",
            "feature_cache_key": fk_5c,
        },
        "k",
        data_fp,
        code_fp,
        ticker,
        ml_horizon_suffix="5c",
    )
