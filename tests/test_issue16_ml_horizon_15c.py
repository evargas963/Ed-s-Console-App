"""Issue 16: 15c is a first-class ML product horizon (artifacts, labels, rule features)."""

from __future__ import annotations


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






