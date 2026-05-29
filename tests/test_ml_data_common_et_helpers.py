"""Direct unit tests for ml_data_common ET helpers (FIND-CAL-TS item-6)."""

from __future__ import annotations

import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from ml_data_common import (
    INNER_VAL_MIN_ROWS,
    et_hour_minute_arrays_from_ts_utc,
    filter_df_to_rth_ts_utc,
    head_rth_df_from_ts_utc,
    market_session_from_ts_utc,
    rth_where_clause,
    stamp_et_clock_columns,
    time_ordered_tail_split,
    training_base_where_clause,
)


# ── Workstream B3 — chronological inner holdout split ────────────────────────


def test_time_ordered_tail_split_holds_out_recent_tail():
    n = 1000
    train_end, n_val = time_ordered_tail_split(n, val_fraction=0.15)
    assert n_val == 150                      # last 15% (most recent) held out
    assert train_end == 850                  # earlier rows train
    assert train_end + n_val == n            # partition is exhaustive + disjoint


def test_time_ordered_tail_split_no_holdout_when_val_too_small():
    # round(80*0.15)=12 < INNER_VAL_MIN_ROWS -> no holdout (caller trains in-sample).
    train_end, n_val = time_ordered_tail_split(80, val_fraction=0.15)
    assert (train_end, n_val) == (80, 0)
    assert 12 < INNER_VAL_MIN_ROWS


def test_time_ordered_tail_split_no_holdout_when_train_too_small():
    # val passes min, but train would be < min_train -> no holdout.
    train_end, n_val = time_ordered_tail_split(120, val_fraction=0.5, min_val=20, min_train=100)
    assert (train_end, n_val) == (120, 0)


def test_time_ordered_tail_split_zero_rows():
    assert time_ordered_tail_split(0) == (0, 0)


def test_rth_where_clause_emits_deprecation_warning():
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        clause = rth_where_clause()
        assert "et_hour" in clause
        assert any(issubclass(x.category, DeprecationWarning) for x in w)


def test_filter_df_to_rth_drops_nan_ts_utc():
    df = pd.DataFrame({"ts_utc": [np.nan, None], "et_hour": [10, 10], "et_minute": [0, 0]})
    assert len(filter_df_to_rth_ts_utc(df)) == 0


def test_filter_df_to_rth_empty_frame():
    assert filter_df_to_rth_ts_utc(pd.DataFrame()).empty


def test_stamp_et_clock_columns_missing_ts_utc_column():
    df = pd.DataFrame({"et_hour": [9]})
    out = stamp_et_clock_columns(df)
    assert out.equals(df)


def test_training_base_where_clause_has_no_rth_on_stored_hour():
    w = training_base_where_clause()
    assert "et_hour" not in w
    assert "et_minute" not in w


def test_market_session_from_ts_utc_premarket():
    t = datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc).timestamp()  # 8:00 ET
    assert market_session_from_ts_utc(t) == "premarket"


def test_head_rth_df_from_ts_utc_caps_after_filter():
    t_rth = datetime(2026, 7, 7, 15, 0, tzinfo=timezone.utc).timestamp()
    t_pre = datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc).timestamp()
    df = pd.DataFrame({"ts_utc": [t_pre, t_rth, t_rth]})
    out = head_rth_df_from_ts_utc(df, 1)
    assert len(out) == 1
    assert float(out["ts_utc"].iloc[0]) == t_rth
