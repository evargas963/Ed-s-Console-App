"""FIND-CAL-TS-RDERIVE — et_clock_from_ts_utc authority and training RTH filter."""

from __future__ import annotations

from datetime import datetime, timezone


from time_et import (
    et_clock_from_ts_utc,
)


def test_et_clock_from_ts_utc_dst_summer_vs_winter():
    winter = datetime(2026, 1, 15, 15, 0, tzinfo=timezone.utc)  # 10:00 ET
    summer = datetime(2026, 7, 15, 14, 0, tzinfo=timezone.utc)  # 10:00 ET
    hw, mw, _ = et_clock_from_ts_utc(winter.timestamp())
    hs, ms, _ = et_clock_from_ts_utc(summer.timestamp())
    assert (hw, mw) == (10, 0)
    assert (hs, ms) == (10, 0)






















