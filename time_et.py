"""US/Eastern wall-clock authority (DST-aware). Single source for production ET."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
CT = ZoneInfo("America/Chicago")


def ct_label(ts_utc: float, *, seconds: bool = False) -> str:
    """An instant as the screen shows it: "Fri 09/25 06:59 PM CT"; with `seconds`,
    "Fri 09/25 06:59:07 PM CT" (a trade's time)."""
    return datetime.fromtimestamp(float(ts_utc), CT).strftime(
        "%a %m/%d %I:%M:%S %p CT" if seconds else "%a %m/%d %I:%M %p CT")


def trading_date_label(ts_utc: float) -> str:
    """The ET trading date an instant falls on, as the screen shows a daily bar: "Fri 09/25/2026"
    (a date, not a clock time: a daily bar is stamped 00:00 ET of its date)."""
    return datetime.fromtimestamp(float(ts_utc), ET).strftime("%a %m/%d/%Y")


# RTH 09:30–16:00 ET (minute-of-day).
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




def et_minute_total_from_ts_utc(ts_utc: float) -> int:
    h, m, _ = et_clock_from_ts_utc(ts_utc)
    return h * 60 + m




# ── Collect window ──────────
# `price_bars_1m` persists ET bar-END minutes (555, min(975, cash_close+15)] on trading days
# only — 08:15–15:15 CT. The app gathers from 08:15 CT because it must be ready before the
# open, and SPY/QQQ-class ETFs trade to 16:15 ET. This is neither cash RTH [570,960) nor
# vendor extended hours.
COLLECT_WINDOW_START_MINS = 555      # 09:15 ET bar-END exclusive floor (08:15 CT)
COLLECT_WINDOW_END_MINS = 975        # 16:15 ET bar-END inclusive ceiling (15:15 CT)


def collect_window_end_mins_for_et_date(et_date: str) -> int | None:
    """Collect-window ceiling (ET minute-of-day, inclusive) for a date; None = no session.

    `min(COLLECT_WINDOW_END_MINS, cash_close + 15)` — the ETF tail is 15 minutes past the
    cash close, so a half day ends at 13:15 ET (795), never at the full-day 975. Fail-closed
    through `session_close_mins_for_et_date`: holidays and uncovered calendar years return
    None, so an unknown day admits NO bars rather than a guessed full session.
    """
    close = session_close_mins_for_et_date(et_date)
    if close is None:
        return None
    return min(COLLECT_WINDOW_END_MINS, close + 15)


def is_collect_window_bar_end_ts_utc(ts_utc: float) -> bool:
    """True iff a bar ENDING at ts_utc may be persisted to `price_bars_1m` (RC-183).

    Judged on the bar's END minute, which is what the table stores: a bar ending 09:15 ET
    COVERS 09:14 and is therefore pre-window, while the first legal bar ends 09:16. Hence the
    half-open interval (start, end] rather than [start, end).
    """
    try:
        ts = float(ts_utc)
    except (TypeError, ValueError):
        return False                      # unparseable -> excluded, never guessed
    et_date = et_date_str_from_ts_utc(ts)
    if not is_trading_day_et(et_date):
        return False                      # weekends/holidays are never a session
    end_mins = collect_window_end_mins_for_et_date(et_date)
    if end_mins is None:
        return False
    mins = et_minute_total_from_ts_utc(ts)
    return COLLECT_WINDOW_START_MINS < mins <= end_mins




# ── Session calendar ─────────────────────────────────────────────────────────
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
    if close is None or mins < 240 or mins >= 1200:
        return "Closed"
    if mins < RTH_START_MINS:
        return "Pre-Market"
    return "RTH" if mins < close else "After-Hours"


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
    moved". Instant-level callers use session_label or is_capturable_session (extended
    hours) instead.
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


def is_capturable_session(now: "datetime | None" = None) -> bool:
    """True iff a snapshot should be PERSISTED at this ET wall-clock — the one
    canonical capture-session authority (RC-48).

    True only on a trading calendar day (weekday, not a full holiday / uncovered
    year) within extended hours [04:00, 20:00) ET — pre-market, RTH, or
    after-hours. False for weekends, holidays, and the overnight window (< 04:00
    or >= 20:00). Off-hours snapshots carry no signal (options do not trade, spot
    does not move), are excluded from training (ml_train RTH filter), and are
    read by nothing — so they must not be written or accumulated.

    Takes an optional `now` for deterministic testing. Callers pass now_et() live; offline/replay callers pass their clock.
    """
    n = now if now is not None else now_et()
    if n.weekday() >= 5:                                    # Sat / Sun
        return False
    if session_close_mins_for_et_date(n.strftime("%Y-%m-%d")) is None:
        return False                                       # full holiday / uncovered year
    mins = n.hour * 60 + n.minute
    return 240 <= mins < 1200                              # 04:00 <= t < 20:00 ET (extended hours)


#: Seconds in a 365-day year (ACT/365, the standard option-pricing day-count).
YEAR_SECONDS: float = 365.0 * 24.0 * 3600.0
#: Sub-floor on time-to-expiry (10 minutes) — guards the exact-expiry 1/sqrt(T) singularity
#: WITHOUT flattening the genuine near-expiry gamma/charm spike (which desks hedge minute by
#: minute). Far below the old 0.5-DAY floor that mis-priced every 0DTE greek.
MIN_TIME_TO_EXPIRY_YEARS: float = 600.0 / YEAR_SECONDS


#: Schwab's `settlementType` for an AM-settled contract (the $SPX monthly: its value is set from
#: the opening prices on the expiration date; Schwab's lastTradingDay is the day before).
SETTLEMENT_AM = "A"


def settlement_et(expiry_et_date: str, settlement_type: str | None = None) -> "datetime | None":
    """When a contract expiring on this date settles: the session close on that date (16:00 ET,
    13:00 on an early-close day), or the 09:30 ET open for Schwab's settlementType "A". None for
    a date that is a full holiday (a data error) or cannot be read. An expiry in a year the
    calendar does not cover yet is a normal 16:00 close."""
    d = str(expiry_et_date)[:10]
    if d in US_EQUITY_FULL_HOLIDAYS_ET:
        return None
    close_mins = (RTH_OPEN_MINS if settlement_type == SETTLEMENT_AM
                  else US_EQUITY_EARLY_CLOSE_MINS_ET.get(d, RTH_END_MINS))
    try:
        y, mo, dd = int(d[0:4]), int(d[5:7]), int(d[8:10])
    except (ValueError, IndexError):
        return None
    return datetime(y, mo, dd, close_mins // 60, close_mins % 60, tzinfo=ET)


def time_to_expiry_years(expiry_et_date: str, now: "datetime | None" = None, *,
                         settlement_type: str | None = None) -> float | None:
    """Canonical INTRADAY time-to-expiry in years (ACT/365) — the SINGLE SOURCE of T for
    every Black-Scholes greek (gamma, charm, ...).

    T is measured from `now` (ET; defaults to now_et()) to the option's settlement
    (settlement_et). This replaces the per-site day-count/floor conventions
    (a 0.5-DAY floor in bs_gamma, whole-day dte/365 in charm) that smoothed away the real
    1/sqrt(T) near-expiry spike.

    VALIDATED 2026-07-26 against Schwab-reported gamma on real chains: intraday-to-close matches
    Schwab to a MEASURED median ratio 0.987 (94% of ATM strikes within 10%) in the 2-6h window,
    versus 1.29 (13% within 10%) for the old 0.5-day floor — i.e. Schwab prices with this clock.

    Returns None when the expiry date is a holiday / outside the covered calendar (fail closed),
    or when the option has already reached settlement (now >= close). A 10-minute sub-floor
    guards the exact-expiry singularity while preserving the genuine spike.
    """
    expiry_dt = settlement_et(expiry_et_date, settlement_type)
    if expiry_dt is None:
        return None
    ref = now if now is not None else now_et()
    # Instant elapsed seconds, not civil timedelta. Same-tzinfo subtraction ignores DST
    # (spring-forward Friday→Monday expiry wall 77.5h vs UTC timestamp 76.5h).
    ref_aware = ref if ref.tzinfo is not None else ref.replace(tzinfo=ET)
    secs = expiry_dt.timestamp() - ref_aware.timestamp()
    t = secs / YEAR_SECONDS
    if t <= 0.0:
        return None  # at/after settlement — no greeks for an expired contract (fail closed)
    return max(t, MIN_TIME_TO_EXPIRY_YEARS)
