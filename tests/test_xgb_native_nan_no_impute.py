"""
No-fallback lock repair (2026-09-17, FB-00420, MISSINGNESS_CONTRACT_VERSION issue7_v2):
ml_train.py used to median-impute missing feature readings (fit on the train partition)
before training an XGBoost model, and zero any remaining NaN -- both a specific,
meaningful value substituted for "never observed." XGBoost natively handles NaN inputs
(learns an optimal tree-split direction for missing values), so training now passes real
NaN straight through with no imputation at all. This closes the LAST remaining FALLBACK
candidate in the repo-wide no-fallback census.

Deploying this change means every XGBoost model bundle trained under the prior
missingness_contract_version ("issue7_v1_empirical_nan_impute") no longer matches
CURRENT_MISSINGNESS_CONTRACT_VERSION and fails meta_matches_system_contract until
retrained -- the deliberate, documented consequence of a genuine missingness-semantics
change (see model_contract.py's own "bump when semantics change; retrain all families"
convention), not an oversight.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path

import numpy as np
import pandas as pd

from model_contract import (
    CURRENT_MISSINGNESS_CONTRACT_VERSION,
    contract_metadata_dict,
    validate_artifact_contract,
)


def _make_training_df(n: int = 400, nan_col: str = "candle_body_pts") -> pd.DataFrame:
    rng = np.random.default_rng(7)
    rows = {
        "spot": rng.uniform(99, 101, n),
        "et_hour": rng.integers(10, 15, n),
        "et_minute": rng.integers(0, 59, n),
        "ts_et": [f"2026-03-{1 + i % 20:02d} 10:30:00" for i in range(n)],
        "ticker": ["XNA"] * n,
        "candle_body_pts": rng.normal(0, 0.5, n),
        "candle_range_pts": rng.uniform(0.1, 1.0, n),
        "nearest_above_dist": rng.uniform(0.5, 2.0, n),
        "nearest_below_dist": rng.uniform(0.5, 2.0, n),
        "outcome_1c": rng.choice(["up", "down", "flat"], n),
    }
    df = pd.DataFrame(rows)
    # A genuine, realistic gap: some rows never had this reading.
    mask = rng.random(n) < 0.15
    df.loc[mask, nan_col] = np.nan
    return df


def test_train_ticker_writes_empty_impute_medians_and_v2_contract(tmp_path: Path):
    from ml_train import train_ticker

    df = _make_training_df()
    model_dir = tmp_path / "models"
    train_ticker("XNA", df, model_dir=model_dir, skip_sanity=True, ml_horizon_slug="1c")

    mtp = model_dir / "xgb_XNA_1c_meta.json"
    assert mtp.exists()
    meta = json.loads(mtp.read_text(encoding="utf-8"))

    assert meta.get("impute_medians") == {}, (
        "a freshly trained model must carry a deliberately empty impute_medians, "
        "proving no median was computed or applied"
    )
    assert meta.get("missingness_contract_version") == CURRENT_MISSINGNESS_CONTRACT_VERSION
    assert CURRENT_MISSINGNESS_CONTRACT_VERSION == "issue7_v2_xgb_native_nan_no_impute"

    ok, msg = validate_artifact_contract(meta, "xgb")
    assert ok, f"freshly trained model must pass contract validation: {msg}"


def test_apply_xgb_imputation_matrix_preserves_nan_for_empty_medians():
    """Direct proof apply_xgb_imputation_matrix -- the ONE function every serving path
    (ml_predict.py, arch_competition.ablation_bundle_inference) routes through -- is a
    true passthrough (no median fill, no unconditional nan_to_num zeroing) when
    impute_medians is empty, the shape a v2-trained model always carries."""
    from ml_train import apply_xgb_imputation_matrix

    x = np.array([[1.0, np.nan, 3.0]])
    out = apply_xgb_imputation_matrix(x, ["a", "b", "c"], {})
    assert np.isnan(out[0, 1]), (
        "an empty impute_medians must leave a missing reading as real NaN for XGBoost's "
        "own native handling -- not zero, which is a specific, valid-looking value"
    )
    assert out[0, 0] == 1.0 and out[0, 2] == 3.0


def test_apply_xgb_imputation_matrix_legacy_shape_unchanged():
    """A model trained under the PRIOR contract (real, complete impute_medians) must see
    byte-identical behavior to before this repair -- median fill, then zero any
    remainder."""
    from ml_train import apply_xgb_imputation_matrix

    x = np.array([[np.nan, 2.0]])
    out = apply_xgb_imputation_matrix(x, ["a", "b"], {"a": 9.0, "b": 2.0})
    assert out[0, 0] == 9.0
    assert out[0, 1] == 2.0


def test_v1_bundle_fails_contract_until_retrained():
    """
    The deliberate consequence of the version bump: a model trained under the PRIOR
    missingness contract (real, complete impute_medians) no longer matches
    CURRENT_MISSINGNESS_CONTRACT_VERSION and fails validate_artifact_contract --
    fail-closed, not silently still-served under stale semantics.
    """
    v1_meta = {
        **contract_metadata_dict(),
        "missingness_contract_version": "issue7_v1_empirical_nan_impute",
        "features": ["a", "b"],
        "impute_medians": {"a": 1.0, "b": 2.0},
    }
    ok, msg = validate_artifact_contract(v1_meta, "xgb")
    assert ok is False
    assert "missingness_contract_version" in msg


def test_legacy_complete_impute_medians_still_valid_under_v2_stamp():
    """Byte-identical acceptance for the (never-produced-by-current-code, purely
    defensive) case of a fully-populated impute_medians dict stamped with the CURRENT
    contract version -- accepting it is harmless since training never produces this
    shape anymore, and a partial dict is still correctly rejected either way."""
    meta = {
        **contract_metadata_dict(),
        "features": ["a", "b"],
        "impute_medians": {"a": 1.0, "b": 2.0},
    }
    ok, _ = validate_artifact_contract(meta, "xgb")
    assert ok is True

    partial_meta = {**meta, "impute_medians": {"a": 1.0}}
    ok2, msg2 = validate_artifact_contract(partial_meta, "xgb")
    assert ok2 is False
    assert "impute_medians" in msg2


def test_apply_xgb_imputation_matrix_docstring_names_the_repair():
    from ml_train import apply_xgb_imputation_matrix

    assert "issue7_v2" in inspect.getsource(apply_xgb_imputation_matrix)
