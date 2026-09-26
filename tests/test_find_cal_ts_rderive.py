"""FIND-CAL-TS-RDERIVE — et_clock_from_ts_utc authority and training RTH filter."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from ml_data_common import (
    et_hour_minute_arrays_from_ts_utc,
    filter_df_to_rth_ts_utc,
    stamp_et_clock_columns,
)
from time_et import (
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










def test_ml_train_load_data_where_has_no_rth_where_clause():
    import inspect

    from ml_train import load_data

    src = inspect.getsource(load_data)
    assert "rth_where_clause()" not in src


_SKIP_PY_TREE_DIRS = frozenset(
    {".claude", ".git", ".venv", "venv", "node_modules", "__pycache__"}
)


def test_no_rth_where_clause_callers_repo_wide(repo_index):
    """Regression: rth_where_clause() must not appear outside ml_data_common
    (definition). TEST_SYSTEM_REHAB_V2: sources from the shared `repo_index` corpus
    instead of an independent root.rglob("*.py")."""
    offenders: list[str] = []
    for rel, src, _tree in repo_index.items():
        if rel.parts and rel.parts[0] == "tests":
            continue
        if rel.name == "ml_data_common.py":
            continue
        if any(part in _SKIP_PY_TREE_DIRS for part in rel.parts):
            continue
        if "rth_where_clause()" in src:
            offenders.append(str(rel).replace("\\", "/"))
    assert not offenders, f"rth_where_clause() callers: {offenders}"


