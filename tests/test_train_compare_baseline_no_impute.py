"""
No-fallback lock repair (2026-09-17): train_compare.py's _compute_baseline mapped
rules_signal values outside {long, short, wait} to "flat" via fillna -- treating an
unrecognized/malformed signal the same as a genuine wait/flat reading, which could
silently bias the reported baseline accuracy metric. Repaired to exclude unmapped rows
from the metric entirely.
"""
from __future__ import annotations

import pandas as pd

from train_compare import _compute_baseline


def test_all_recognized_signals_baseline_unaffected():
    df = pd.DataFrame({
        "rules_signal": ["long", "short", "wait", "long"],
        "label": ["up", "down", "flat", "down"],
    })
    # 3 of 4 rows' predicted direction matches label (long->up matches twice minus one wrong).
    acc = _compute_baseline(df, "label")
    assert acc == 0.75


def test_unrecognized_signal_excluded_not_guessed_as_flat():
    """An unrecognized rules_signal value must not be silently scored as a 'flat'
    prediction -- it is excluded from the baseline metric entirely."""
    df = pd.DataFrame({
        "rules_signal": ["long", "short", "garbled_unexpected_value"],
        "label": ["up", "down", "flat"],
    })
    # Both recognized rows are correct; the unrecognized row is excluded, not counted
    # as a wrong (or coincidentally right) "flat" guess.
    acc = _compute_baseline(df, "label")
    assert acc == 1.0


def test_all_unrecognized_returns_zero_not_a_crash():
    df = pd.DataFrame({
        "rules_signal": ["garbled_1", "garbled_2"],
        "label": ["up", "down"],
    })
    assert _compute_baseline(df, "label") == 0.0


def test_empty_after_notna_filter_returns_zero():
    df = pd.DataFrame({"rules_signal": [None], "label": ["up"]})
    assert _compute_baseline(df, "label") == 0.0
