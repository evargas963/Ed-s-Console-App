"""Issue 7: training vs inference parity for XGB tabular features."""
from __future__ import annotations


import pandas as pd



def _minimal_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ticker": ["SPY"],
            "candle_body_pts": [1.0],
            "candle_range_pts": [2.0],
            "nearest_above_dist": [1.0],
            "nearest_below_dist": [1.0],
            "spot": [100.0],
            "outcome_1c": ["up"],
        }
    )
















def _ordered_feature_df() -> pd.DataFrame:
    """8 chronological rows: a shared time-of-day group (idx0-5), a distinct tod tail (idx6-7),
    and a 'zone' category that appears only in the tail. Used for B3 train-only-fit tests."""
    ts = 1_700_000_000
    return pd.DataFrame(
        {
            "ticker": ["SPY"] * 8,
            "ts_utc": [ts, ts, ts, ts, ts, ts, ts + 7200, ts + 7200],
            "spot": [100.0] * 8,
            "candle_body_pts": [0.5, 0.4, 0.6, 0.5, 0.45, 0.55, 0.5, 0.5],
            "candle_range_pts": [1.0] * 8,
            "nearest_above_dist": [1.0] * 8,
            "nearest_below_dist": [1.0] * 8,
            "candle_volume": [100.0, 110.0, 90.0, 105.0, 95.0, 100.0, 200.0, 220.0],
            "zone": ["pin_neutral"] * 6 + ["breakout_up", "breakout_up"],
            "outcome_1c": ["up", "down", "flat", "up", "down", "flat", "up", "down"],
        }
    )









































































































def test_check_ablation_pipeline_parity_green():
    from tools.check_ablation_pipeline_parity import check_ablation_pipeline_parity

    assert check_ablation_pipeline_parity() == []




















def test_ml_pipeline_efficiency_checker_green():
    from tools.check_ml_pipeline_efficiency import check_ml_pipeline_efficiency

    assert check_ml_pipeline_efficiency() == []


# ── RC-332: cf_* has ONE input population, and callers may not choose it ────────
#
# RC-328 made the confluence WINDOW clock-defined and repaired two lanes. Four more kept
# passing their own row population into the same producer, because the producer's signature
# accepts one. Measured before the fix: 179 divergent cells over 826 SPY bars between the
# LSTM offline and live populations, cf_alignment_score off by up to 3.0 of its -4..+4
# range. These two controls fail if either half of that regresses.




























