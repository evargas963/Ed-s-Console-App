"""US/Eastern wall-clock authority (DST-aware). Single source for production ET."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# COH-I-A (`99ea0e0`): first commit with DST-aware `now_et` / `time_et.ET` authority.
COH_I_A_ET_AUTHORITY_TS_UTC = 1779237069.0

# Historical backfill ceiling: rows with ts_utc < this are rewritten from ts_utc (item-6).
# One-hour pad after the git landing instant so rows logged by long-running workers that
# had not restarted yet are still corrected (FIND-CAL-TS item-6).
COH_I_A_ET_BACKFILL_CEILING_TS_UTC = COH_I_A_ET_AUTHORITY_TS_UTC + 3600.0

# RTH 09:30–16:00 ET (minute-of-day); shared with ml_data_common.
RTH_START_MINS = 570
RTH_OPEN_MINS = RTH_START_MINS  # 9:30 AM ET (alias for cross-module authority)
RTH_END_MINS = 960


def now_et() -> datetime:
    """Timezone-aware US/Eastern now."""
    return datetime.now(ET)


def et_clock_from_ts_utc(ts_utc: float) -> tuple[int, int, int]:
    """DST-aware (hour, minute, weekday) from UTC epoch. weekday: Mon=0 .. Sun=6."""
    dt = datetime.fromtimestamp(float(ts_utc), tz=timezone.utc).astimezone(ET)
    return int(dt.hour), int(dt.minute), int(dt.weekday())


def et_date_str_from_ts_utc(ts_utc: float) -> str:
    """YYYY-MM-DD in America/New_York for the instant."""
    dt = datetime.fromtimestamp(float(ts_utc), tz=timezone.utc).astimezone(ET)
    return dt.strftime("%Y-%m-%d")


def build_ts_et_from_ts_utc(ts_utc: float) -> str:
    """Display ts_et string from UTC epoch (DST-aware), matching db.build_ts_et format."""
    dt = datetime.fromtimestamp(float(ts_utc), tz=timezone.utc).astimezone(ET)
    return dt.strftime("%Y-%m-%d %H:%M:%S ET")


def et_minute_total_from_ts_utc(ts_utc: float) -> int:
    h, m, _ = et_clock_from_ts_utc(ts_utc)
    return h * 60 + m


def is_rth_ts_utc(ts_utc: float) -> bool:
    """True when ts_utc falls in RTH (09:30 <= t < 16:00 ET)."""
    mins = et_minute_total_from_ts_utc(ts_utc)
    return RTH_START_MINS <= mins < RTH_END_MINS


def calibration_widen_min_ts_utc() -> float:
    """Default ts_utc floor for calibration widen cohorts (post COH-I-A logging)."""
    return COH_I_A_ET_AUTHORITY_TS_UTC
