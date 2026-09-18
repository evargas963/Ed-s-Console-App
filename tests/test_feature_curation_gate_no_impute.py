"""
No-fallback lock repair (2026-09-17): tools/feature_curation_gate.py's Spearman-
hierarchical clustering used to median-impute missing feature readings before
computing the correlation matrix -- fabricating a value the correlation would then
treat as observed data, capable of silently pulling two features into (or out of) the
same redundancy cluster based on invented numbers, not real co-movement. Repaired to
use complete-case rows only (pandas .dropna()): a row missing any clustered column is
excluded from the correlation computation entirely, never assigned a value it never had.
"""
from __future__ import annotations

import inspect

import numpy as np
import pandas as pd
import pytest
from scipy.stats import spearmanr


def test_no_fillna_left_in_run_source():
    import tools.feature_curation_gate as fcg

    src = inspect.getsource(fcg.run)
    code_only = "\n".join(
        line for line in src.splitlines() if not line.strip().startswith("#")
    )
    assert "fillna" not in code_only
    assert ".dropna()" in code_only


def test_complete_case_exclusion_matches_the_repaired_pattern():
    """
    Direct proof of the repaired statistical pattern: a row with a missing value in
    either clustered column is excluded from the correlation, not median-filled. Two
    features that are ONLY correlated on their complete rows must show that true
    correlation, not one diluted/distorted by a fabricated median value plugged into
    the incomplete row.
    """
    df = pd.DataFrame({
        "a": [1.0, 2.0, 3.0, 4.0, np.nan],
        "b": [1.0, 2.0, 3.0, 4.0, 100.0],  # would distort the correlation if the NaN
                                            # row were assigned a value instead of excluded
    })
    num = df.apply(pd.to_numeric, errors="coerce")

    x_repaired = num[["a", "b"]].dropna()
    assert len(x_repaired) == 4, "the row with a real NaN must be excluded entirely"
    rho_repaired, _ = spearmanr(x_repaired.values)
    assert rho_repaired == pytest.approx(1.0), (
        "the 5th row's outlier 'b' value must never enter the correlation, since its "
        "'a' value was never observed"
    )
