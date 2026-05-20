"""FIND-CAL-TS-RDERIVE — et_clock_from_ts_utc authority and training RTH filter."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from ml_data_common import (
    calibration_widen_min_ts_utc,
    et_hour_minute_arrays_from_ts_utc,
    filter_df_to_rth_ts_utc,
    market_session_from_ts_utc,
    stamp_et_clock_columns,
)
from time_et import (
    COH_I_A_ET_AUTHORITY_TS_UTC,
    COH_I_A_ET_BACKFILL_CEILING_TS_UTC,
    build_ts_et_from_ts_utc,
    et_clock_from_ts_utc,
    is_rth_ts_utc,
)


def test_et_clock_from_ts_utc_dst_summer_vs_winter():
    winter = datetime(2026, 1, 15, 15, 0, tzinfo=timezone.utc)  # 10:00 ET
    summer = datetime(2026, 7, 15, 14, 0, tzinfo=timezone.utc)  # 10:00 ET
    hw, mw, _ = et_clock_from_ts_utc(winter.timestamp())
    hs, ms, _ = et_clock_from_ts_utc(summer.timestamp())
    assert (hw, mw) == (10, 0)
    assert (hs, ms) == (10, 0)


def test_is_rth_ts_utc_boundaries():
    # 9:30 ET on a Tuesday in summer
    t_open = datetime(2026, 7, 7, 13, 30, tzinfo=timezone.utc).timestamp()
    assert is_rth_ts_utc(t_open)
    t_pre = datetime(2026, 7, 7, 13, 29, tzinfo=timezone.utc).timestamp()
    assert not is_rth_ts_utc(t_pre)


def test_filter_df_to_rth_ignores_skewed_stored_hour():
    # Stored hour says 10:00 but ts_utc is 8:00 ET (pre-market) — must drop
    t_pre = datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc).timestamp()
    df = pd.DataFrame(
        {
            "ts_utc": [t_pre],
            "et_hour": [10],
            "et_minute": [0],
        }
    )
    out = filter_df_to_rth_ts_utc(df)
    assert len(out) == 0


def test_stamp_et_clock_columns_overwrites_from_ts_utc():
    t = datetime(2026, 7, 7, 15, 0, tzinfo=timezone.utc).timestamp()  # 11:00 ET
    df = pd.DataFrame({"ts_utc": [t], "et_hour": [9], "et_minute": [0]})
    out = stamp_et_clock_columns(df)
    assert int(out["et_hour"].iloc[0]) == 11
    assert int(out["et_minute"].iloc[0]) == 0


def test_et_hour_minute_arrays_from_ts_utc_not_stored():
    t = datetime(2026, 7, 7, 15, 0, tzinfo=timezone.utc).timestamp()
    df = pd.DataFrame({"ts_utc": [t], "et_hour": [1], "et_minute": [1]})
    hrs, mns = et_hour_minute_arrays_from_ts_utc(df)
    assert hrs[0] == 11
    assert mns[0] == 0


def test_market_session_from_ts_utc_rth():
    t = datetime(2026, 7, 7, 15, 0, tzinfo=timezone.utc).timestamp()
    assert market_session_from_ts_utc(t) == "rth"


def test_calibration_widen_min_ts_matches_coh_i_a():
    assert calibration_widen_min_ts_utc() == COH_I_A_ET_AUTHORITY_TS_UTC


def test_backfill_ceiling_includes_one_hour_pad():
    assert COH_I_A_ET_BACKFILL_CEILING_TS_UTC == COH_I_A_ET_AUTHORITY_TS_UTC + 3600.0


def test_build_ts_et_from_ts_utc_dst():
    t = datetime(2026, 7, 7, 15, 0, tzinfo=timezone.utc).timestamp()
    assert build_ts_et_from_ts_utc(t) == "2026-07-07 11:00:00 ET"


def test_ml_train_load_data_where_has_no_rth_where_clause():
    import inspect

    from ml_train import load_data

    src = inspect.getsource(load_data)
    assert "rth_where_clause()" not in src


def test_v2_advisory_backfill_stamps_et_clock_from_ts_utc():
    from calibration.v2_advisory_backfill import ms_dict_from_snapshot_row

    t = datetime(2026, 7, 7, 15, 0, tzinfo=timezone.utc).timestamp()
    row = {
        "ticker": "SPY",
        "ts_utc": t,
        "et_hour": 9,
        "et_minute": 0,
        "spot": 500.0,
    }
    ms = ms_dict_from_snapshot_row(row)
    assert ms["et_hour"] == 11
    assert ms["et_minute"] == 0
    assert ms["market_session"] == "rth"
