"""Issue 17: 60c is first-class for ML (artifacts, labels, rule features, meta horizon label)."""

from __future__ import annotations


from ml_horizon import (
    ML_HORIZON_SLUGS,
)






def test_60c_in_product_horizon_tuple():
    assert "60c" in ML_HORIZON_SLUGS
    assert ML_HORIZON_SLUGS[-1] == "60c"




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
