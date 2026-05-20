"""Direct unit tests for ml_data_common ET helpers (FIND-CAL-TS item-6)."""

from __future__ import annotations

import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from ml_data_common import (
    et_hour_minute_arrays_from_ts_utc,
    filter_df_to_rth_ts_utc,
    head_rth_df_from_ts_utc,
    market_session_from_ts_utc,
    rth_where_clause,
    stamp_et_clock_columns,
    training_base_where_clause,
)


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
