"""Issue 16: 15c is a first-class ML product horizon (artifacts, labels, rule features)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ml_horizon import ML_HORIZON_SLUGS, target_definition
from ml_train import engineer_features, meta_path, model_path


def test_ml_train_artifact_paths_15c():
    assert model_path("SPY", Path("models"), ml_horizon_slug="15c").name == "xgb_SPY_15c.pkl"
    assert meta_path("SPY", Path("models"), ml_horizon_slug="15c").name == "xgb_SPY_15c_meta.json"


def test_target_definition_15c():
    td = target_definition("15c")
    assert "outcome_15c" in td
    assert "15" in td
    assert "15 min" in td


def test_15c_in_product_horizon_tuple():
    assert "15c" in ML_HORIZON_SLUGS


def test_engineer_features_does_not_derive_rules_15c_from_empirical_preds():
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
            "pred_15c_up_prob": np.linspace(0.2, 0.5, n),
            "pred_15c_down_prob": np.linspace(0.5, 0.2, n),
            "pred_15c_flat_prob": [0.3] * n,
        }
    )
    _, names, _, _ = engineer_features(df)
    assert "rules_15c_up" not in names
    assert "rules_15c_spread" not in names
    assert "rules_15c_confidence" not in names


def test_transformer_meta_horizon_label():
    from transformer_model import _horizon_label_from_meta

    assert (
        _horizon_label_from_meta({"target_column": "outcome_15c"}) == "15c"
    )
    assert _horizon_label_from_meta({}) == "1c"


@pytest.mark.parametrize("slug", ["1c", "5c", "15c", "60c"])
def test_train_ticker_writes_horizon_metadata(tmp_path: Path, slug: str):
    """End-to-end XGB save: meta.target_column and filenames match horizon (small synthetic df)."""
    from ml_train import train_ticker

    hz = slug
    col = f"outcome_{hz}"
    n = 400
    rng = np.random.default_rng(42)
    rows = {
        "spot": rng.uniform(99, 101, n),
        "et_hour": rng.integers(10, 15, n),
        "et_minute": rng.integers(0, 59, n),
        "ts_et": [f"2026-03-{1 + i % 20:02d} 10:30:00" for i in range(n)],
        "ticker": ["XXT"] * n,
        "candle_body_pts": rng.normal(0, 0.5, n),
        "candle_range_pts": rng.uniform(0.1, 1.0, n),
        "nearest_above_dist": rng.uniform(0.5, 2.0, n),
        "nearest_below_dist": rng.uniform(0.5, 2.0, n),
        col: rng.choice(["up", "down", "flat"], n),
    }
    df = pd.DataFrame(rows)
    model_dir = tmp_path / "models"
    train_ticker(
        "XXT",
        df,
        model_dir=model_dir,
        skip_sanity=True,
        ml_horizon_slug=hz,
    )
    mp = model_dir / f"xgb_XXT_{hz}.pkl"
    assert mp.exists()
    mtp = model_dir / f"xgb_XXT_{hz}_meta.json"
    assert mtp.exists()
    meta = json.loads(mtp.read_text(encoding="utf-8"))
    assert meta.get("target_column") == col
    assert (meta.get("target_definition") or "") == target_definition(hz)


def _synthetic_training_rows(n: int, col: str, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "spot": rng.uniform(99, 101, n),
        "et_hour": rng.integers(10, 15, n),
        "et_minute": rng.integers(0, 59, n),
        "ts_et": [f"2026-03-{1 + i % 20:02d} 10:30:00" for i in range(n)],
        "ticker": ["XXT"] * n,
        "candle_body_pts": rng.normal(0, 0.5, n),
        "candle_range_pts": rng.uniform(0.1, 1.0, n),
        "nearest_above_dist": rng.uniform(0.5, 2.0, n),
        "nearest_below_dist": rng.uniform(0.5, 2.0, n),
        col: rng.choice(["up", "down", "flat"], n),
    })


def test_train_ticker_b3_reports_out_of_sample_holdout_metric(tmp_path: Path):
    """B3: with enough rows the XGB reports an out-of-sample val metric and early-stops on the
    time-ordered tail (not training loss)."""
    from ml_train import train_ticker

    df = _synthetic_training_rows(400, "outcome_1c")
    model_dir = tmp_path / "models"
    train_ticker("XXT", df, model_dir=model_dir, skip_sanity=True, ml_horizon_slug="1c")
    meta = json.loads((model_dir / "xgb_XXT_1c_meta.json").read_text(encoding="utf-8"))
    assert meta.get("val_basis") == "time_ordered_tail"
    assert meta.get("val_accuracy") is not None
    assert 0.0 <= float(meta["val_accuracy"]) <= 1.0
    assert "xgb_best_iteration" in meta            # early stopping ran on the held-out tail
    assert meta.get("train_accuracy") is not None  # in-sample train-partition metric retained


def test_train_ticker_b3_no_holdout_when_too_few_rows(tmp_path: Path):
    """Thin ticker: no honest holdout can be carved -> in-sample (disclosed), blocked by A1/B1."""
    from ml_train import train_ticker

    df = _synthetic_training_rows(80, "outcome_1c")
    model_dir = tmp_path / "models"
    train_ticker("XXT", df, model_dir=model_dir, skip_sanity=True, ml_horizon_slug="1c")
    meta = json.loads((model_dir / "xgb_XXT_1c_meta.json").read_text(encoding="utf-8"))
    assert meta.get("val_basis") == "in_sample_no_holdout"
    assert meta.get("val_accuracy") is None
