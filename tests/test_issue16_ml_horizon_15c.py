"""Issue 16: 15c is a first-class ML product horizon (artifacts, labels, rule features)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml_horizon import (
    ML_HORIZON_SLUGS,
)






def test_15c_in_product_horizon_tuple():
    assert "15c" in ML_HORIZON_SLUGS






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


