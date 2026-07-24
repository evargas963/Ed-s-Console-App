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
RTH_SESSION_MINUTES = RTH_END_MINS - RTH_START_MINS  # 390 = single RTH session length as 1m bars


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


# ── F1 session authority (RC-31 / F-8 / F-9) ─────────────────────────────────
# ONE function answers "is this instant a tradable RTH minute": ET weekday AND
# holiday/early-close calendar AND RTH minutes. The legacy pair
# (is_rth_ts_utc + a SQL weekday clause) was only correct when callers composed
# BOTH — is_rth_ts_utc alone admits Saturday 10:00 ET and full-holiday
# afternoons (measured 2026-07-23: 3,795 labeled 'rth' rows on Memorial Day,
# 912 on 2026-07-03). New F1 consumers must call is_tradable_session_ts_utc.

# NYSE/Nasdaq full-closure dates (ET calendar dates). Covered years only —
# dates outside coverage FAIL CLOSED (excluded, never guessed).
US_EQUITY_CALENDAR_YEARS: frozenset[int] = frozenset({2025, 2026})
US_EQUITY_FULL_HOLIDAYS_ET: frozenset[str] = frozenset({
    # 2025
    "2025-01-01", "2025-01-20", "2025-02-17", "2025-04-18", "2025-05-26",
    "2025-06-19", "2025-07-04", "2025-09-01", "2025-11-27", "2025-12-25",
    # 2026 (2026-07-03 = Independence Day observed, Jul 4 is a Saturday)
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
    "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
})
# 13:00 ET early closes (minute-of-day 780).
EARLY_CLOSE_MINS: int = 780
US_EQUITY_EARLY_CLOSE_MINS_ET: dict[str, int] = {
    "2025-07-03": EARLY_CLOSE_MINS,
    "2025-11-28": EARLY_CLOSE_MINS,
    "2025-12-24": EARLY_CLOSE_MINS,
    "2026-11-27": EARLY_CLOSE_MINS,
    "2026-12-24": EARLY_CLOSE_MINS,
}


def session_close_mins_for_et_date(et_date: str) -> int | None:
    """RTH close (ET minute-of-day) for a calendar date; None = no session that day.

    Fail-closed: dates in uncovered years return None — an unknown calendar is
    an excluded day, never a guessed full session.
    """
    try:
        year = int(str(et_date)[:4])
    except (TypeError, ValueError):
        return None
    if year not in US_EQUITY_CALENDAR_YEARS:
        return None
    if et_date in US_EQUITY_FULL_HOLIDAYS_ET:
        return None
    return US_EQUITY_EARLY_CLOSE_MINS_ET.get(str(et_date), RTH_END_MINS)


def is_tradable_session_ts_utc(ts_utc: float) -> bool:
    """True iff ts_utc is an ET-weekday RTH minute of an actual trading session.

    Checks all three dimensions in one place so a caller cannot forget one:
    ET weekday (not UTC weekday — Sunday 20:30 ET is Monday in UTC), the
    holiday/early-close calendar, and the 09:30 <= t < close ET minute window.
    """
    h, m, wd = et_clock_from_ts_utc(ts_utc)
    if wd >= 5:
        return False
    close = session_close_mins_for_et_date(et_date_str_from_ts_utc(ts_utc))
    if close is None:
        return False
    mins = h * 60 + m
    return RTH_START_MINS <= mins < close
