"""US/Eastern wall-clock authority (DST-aware). Single source for production ET."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
CT = ZoneInfo("America/Chicago")


def ct_label(ts_utc: float) -> str:
    """An instant as the screen shows it: "Fri 09/25 06:59 PM CT"."""
    return datetime.fromtimestamp(float(ts_utc), CT).strftime("%a %m/%d %I:%M %p CT")


# RTH 09:30–16:00 ET (minute-of-day).
RTH_START_MINS = 570
RTH_OPEN_MINS = RTH_START_MINS  # 9:30 AM ET (alias for cross-module authority)
RTH_END_MINS = 960
# The extended session (pre-market and after hours) 04:00–20:00 ET (minute-of-day).
EXTENDED_START_MINS = 240
EXTENDED_END_MINS = 1200


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










# ── F1 session authority (RC-31 / F-8 / F-9) ─────────────────────────────────
# ONE function answers "is this instant a tradable RTH minute": ET weekday AND
# holiday/early-close calendar AND RTH minutes. The legacy pair
# (is_rth_ts_utc + a SQL weekday clause) was only correct when callers composed
# BOTH — is_rth_ts_utc alone admits Saturday 10:00 ET and full-holiday
# afternoons (measured 2026-07-23: 3,795 labeled 'rth' rows on Memorial Day,
# 912 on 2026-07-03). New F1 consumers must call is_tradable_session_ts_utc.

# NYSE/Nasdaq full-closure dates (ET calendar dates). Covered years only —
# dates outside coverage FAIL CLOSED (excluded, never guessed).
US_EQUITY_CALENDAR_YEARS: frozenset[int] = frozenset({2025, 2026, 2027, 2028})
US_EQUITY_FULL_HOLIDAYS_ET: frozenset[str] = frozenset({
    # 2025
    "2025-01-01", "2025-01-20", "2025-02-17", "2025-04-18", "2025-05-26",
    "2025-06-19", "2025-07-04", "2025-09-01", "2025-11-27", "2025-12-25",
    # 2026 (2026-07-03 = Independence Day observed, Jul 4 is a Saturday)
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
    "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
    # 2027 and 2028 from nyse.com/trade/hours-calendars (read 2026-09-26). 2027-06-18, -07-05,
    # -12-24 are the observed Juneteenth, Independence Day and Christmas; no New Year's Day
    # holiday is observed for 2028 (Jan 1 is a Saturday).
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31",
    "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24",
    "2028-01-17", "2028-02-21", "2028-04-14", "2028-05-29", "2028-06-19",
    "2028-07-04", "2028-09-04", "2028-11-23", "2028-12-25",
})
# 13:00 ET early closes (minute-of-day 780).
EARLY_CLOSE_MINS: int = 780
US_EQUITY_EARLY_CLOSE_MINS_ET: dict[str, int] = {
    "2025-07-03": EARLY_CLOSE_MINS,
    "2025-11-28": EARLY_CLOSE_MINS,
    "2025-12-24": EARLY_CLOSE_MINS,
    "2026-11-27": EARLY_CLOSE_MINS,
    "2026-12-24": EARLY_CLOSE_MINS,
    "2027-11-26": EARLY_CLOSE_MINS,
    "2028-07-03": EARLY_CLOSE_MINS,
    "2028-11-24": EARLY_CLOSE_MINS,
}


def session_label(now: datetime) -> str:
    """"RTH" | "Pre-Market" | "After-Hours" | "Closed" at `now` (ET), holiday and early-close aware."""
    if now.weekday() >= 5:
        return "Closed"
    close = session_close_mins_for_et_date(now.strftime("%Y-%m-%d"))
    mins = now.hour * 60 + now.minute
    if close is None or mins < EXTENDED_START_MINS or mins >= EXTENDED_END_MINS:
        return "Closed"
    if mins < RTH_START_MINS:
        return "Pre-Market"
    return "RTH" if mins < close else "After-Hours"


#: how far back closed_since looks for the last session (the longest closure on the calendar is
#: a holiday weekend: four days)
CLOSED_SINCE_LOOKBACK_DAYS = 14


def closed_since(now: datetime) -> "datetime | None":
    """While the market is Closed at `now` (session_label): when it closed, the end of the
    newest session (20:00 ET of the newest trading day). None while a session is open. A
    calendar with no session in the CLOSED_SINCE_LOOKBACK_DAYS before `now` (a year it does not
    cover) has been closed for as long as it can tell: `now`."""
    if session_label(now) != "Closed":
        return None
    day = now.astimezone(ET).date()
    if now.astimezone(ET).hour * 60 + now.astimezone(ET).minute < EXTENDED_END_MINS:
        day -= timedelta(days=1)                  # today's session, if any, has not ended
    for _ in range(CLOSED_SINCE_LOOKBACK_DAYS):
        if is_trading_day_et(day.isoformat()):
            return datetime(day.year, day.month, day.day, tzinfo=ET) + timedelta(minutes=EXTENDED_END_MINS)
        day -= timedelta(days=1)
    return now


def market_session_date(now: datetime) -> date:
    """The session the market's values belong to at `now` (ET): today's while a session is open
    (Pre-Market, RTH, After-Hours), the newest session's while Closed, whose values stand until
    the next session opens (docs/DATA_FLOW.md §2 D5)."""
    return (closed_since(now) or now).astimezone(ET).date()


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




def is_trading_day_et(et_date: str) -> bool:
    """True iff `et_date` (YYYY-MM-DD) is a US equity TRADING day — the canonical date-level
    authority for analysis scoping (RC-54).

    Weekday AND not a full holiday AND inside a covered calendar year (uncovered years fail
    closed). Use this to exclude weekend/holiday rows from ANY measurement: a market-closed
    row has frozen spot and stale IV, so including it drags every statistic toward "nothing
    moved". Timestamp-level callers use is_tradable_session_ts_utc (RTH minutes) instead.
    """
    s = str(et_date)[:10]
    try:
        y, m, d = (int(v) for v in s.split("-"))
        wd = datetime(y, m, d).weekday()
    except (TypeError, ValueError):
        return False                      # unparseable -> excluded, never guessed
    if wd >= 5:
        return False
    return session_close_mins_for_et_date(s) is not None


#: Seconds in a 365-day year (ACT/365, the standard option-pricing day-count).
YEAR_SECONDS: float = 365.0 * 24.0 * 3600.0
#: Sub-floor on time-to-expiry (10 minutes) — guards the exact-expiry 1/sqrt(T) singularity
#: WITHOUT flattening the genuine near-expiry gamma/charm spike (which desks hedge minute by
#: minute). Far below the old 0.5-DAY floor that mis-priced every 0DTE greek.
MIN_TIME_TO_EXPIRY_YEARS: float = 600.0 / YEAR_SECONDS


#: Schwab's `settlementType` for an AM-settled contract (the $SPX monthly: its value is set from
#: the opening prices on the expiration date; Schwab's lastTradingDay is the day before).
SETTLEMENT_AM = "A"


def time_to_expiry_years(expiry_et_date: str, now: "datetime | None" = None, *,
                         settlement_type: str | None = None) -> float | None:
    """Canonical INTRADAY time-to-expiry in years (ACT/365) — the SINGLE SOURCE of T for
    every Black-Scholes greek (gamma, charm, ...).

    T is measured from `now` (ET; defaults to now_et()) to the option's settlement on its
    expiration date: the session close (16:00 ET, 13:00 ET on early-close days) for a
    PM-settled contract, the 09:30 ET open for Schwab's settlementType "A". This replaces the per-site day-count/floor conventions
    (a 0.5-DAY floor in bs_gamma, whole-day dte/365 in charm) that smoothed away the real
    1/sqrt(T) near-expiry spike.

    VALIDATED 2026-07-26 against Schwab-reported gamma on real chains: intraday-to-close matches
    Schwab to a MEASURED median ratio 0.987 (94% of ATM strikes within 10%) in the 2-6h window,
    versus 1.29 (13% within 10%) for the old 0.5-day floor — i.e. Schwab prices with this clock.

    Returns None when the expiry date is a holiday / outside the covered calendar (fail closed),
    or when the option has already reached settlement (now >= close). A 10-minute sub-floor
    guards the exact-expiry singularity while preserving the genuine spike.
    """
    d = str(expiry_et_date)[:10]
    # Close time for the EXPIRY date: default 16:00 ET, special-casing only the KNOWN
    # early-close days (13:00) and rejecting a KNOWN full holiday (an expiry landing on one
    # is a data error). Unlike session_close_mins_for_et_date, this does NOT year-gate — an
    # expiry in an uncovered future year (2027+ LEAPS) is a normal 16:00 close, not a drop.
    if d in US_EQUITY_FULL_HOLIDAYS_ET:
        return None
    close_mins = (RTH_OPEN_MINS if settlement_type == SETTLEMENT_AM
                  else US_EQUITY_EARLY_CLOSE_MINS_ET.get(d, RTH_END_MINS))
    try:
        y, mo, dd = int(d[0:4]), int(d[5:7]), int(d[8:10])
    except (ValueError, IndexError):
        return None
    expiry_dt = datetime(y, mo, dd, close_mins // 60, close_mins % 60, tzinfo=ET)
    ref = now if now is not None else now_et()
    # Instant elapsed seconds, not civil timedelta. Same-tzinfo subtraction ignores DST
    # (spring-forward Friday→Monday expiry wall 77.5h vs UTC timestamp 76.5h).
    ref_aware = ref if ref.tzinfo is not None else ref.replace(tzinfo=ET)
    secs = expiry_dt.timestamp() - ref_aware.timestamp()
    t = secs / YEAR_SECONDS
    if t <= 0.0:
        return None  # at/after settlement — no greeks for an expired contract (fail closed)
    return max(t, MIN_TIME_TO_EXPIRY_YEARS)


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
