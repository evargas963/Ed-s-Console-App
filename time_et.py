"""US/Eastern wall-clock authority (DST-aware). Single source for production ET."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# COH-I-A (`99ea0e0`): first commit with DST-aware `now_et` / `time_et.ET` authority.
COH_I_A_ET_AUTHORITY_TS_UTC = 1779237069.0

# Historical backfill ceiling: rows with ts_utc < this are rewritten from ts_utc (item-6).
# One-hour pad after the git landing instant so rows logged by long-running workers that
# had not restarted yet are still corrected (FIND-CAL-TS item-6).
COH_I_A_ET_BACKFILL_CEILING_TS_UTC = COH_I_A_ET_AUTHORITY_TS_UTC + 3600.0

# RC-429: persist writer 95a61031 (2026-08-19T14:10:58Z) switched snapshots.gamma_pin
# from selected-expiry net-GEX peak (`getattr(consensus_summary, "gamma_pin")`, later
# ExposureRow.net_gex_peak) to terrain total-gamma pin (`terrain_cache_get` /
# pick_pin_and_strength). Do NOT ALTER/backfill historical values. The 1h pad matches
# COH-I-A: rows after git-land until desk restart may still be the old semantic.
SNAPSHOTS_GAMMA_PIN_WRITER_LAND_ISO_UTC = "2026-08-19T14:10:58+00:00"
SNAPSHOTS_GAMMA_PIN_WRITER_LAND_TS_UTC = datetime.fromisoformat(
    SNAPSHOTS_GAMMA_PIN_WRITER_LAND_ISO_UTC
).timestamp()
SNAPSHOTS_GAMMA_PIN_RESTART_PAD_SEC = 3600.0
SNAPSHOTS_GAMMA_PIN_TERRAIN_ANALYSIS_TS_UTC = (
    SNAPSHOTS_GAMMA_PIN_WRITER_LAND_TS_UTC + SNAPSHOTS_GAMMA_PIN_RESTART_PAD_SEC
)
GAMMA_PIN_SEMANTIC_NET_GEX_PEAK = "selected_expiry_net_gex_peak"
GAMMA_PIN_SEMANTIC_TERRAIN = "terrain_total_gamma_pin"
GAMMA_PIN_SEMANTIC_MIXED = "mixed_until_restart"
GAMMA_PIN_SEMANTIC_UNKNOWN = "unknown"


def _as_unix_ts_utc(ts_utc: object) -> float | None:
    """Parse snapshots.ts_utc (unix seconds) or an ISO-8601 string to UTC unix."""
    if ts_utc is None:
        return None
    if isinstance(ts_utc, bool):
        return None
    if isinstance(ts_utc, (int, float)):
        t = float(ts_utc)
        return t if t == t else None  # NaN
    raw = str(ts_utc).strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        pass
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def snapshots_gamma_pin_semantic(ts_utc: object) -> str:
    """Which meaning snapshots.gamma_pin holds at persist time (RC-429).

    Before writer land: selected-expiry net-GEX peak. Land until land+1h: mixed
    (desk may not have restarted). After the pad: terrain total-gamma pin for
    analysis. Unknown timestamps do not join either series.
    """
    t = _as_unix_ts_utc(ts_utc)
    if t is None:
        return GAMMA_PIN_SEMANTIC_UNKNOWN
    if t < SNAPSHOTS_GAMMA_PIN_WRITER_LAND_TS_UTC:
        return GAMMA_PIN_SEMANTIC_NET_GEX_PEAK
    if t < SNAPSHOTS_GAMMA_PIN_TERRAIN_ANALYSIS_TS_UTC:
        return GAMMA_PIN_SEMANTIC_MIXED
    return GAMMA_PIN_SEMANTIC_TERRAIN


def snapshots_gamma_pin_is_terrain_analysis_safe(ts_utc: object) -> bool:
    """True iff snapshots.gamma_pin may be treated as terrain total-gamma pin."""
    return snapshots_gamma_pin_semantic(ts_utc) == GAMMA_PIN_SEMANTIC_TERRAIN

# RTH 09:30–16:00 ET (minute-of-day); shared with ml_data_common.
RTH_START_MINS = 570
RTH_OPEN_MINS = RTH_START_MINS  # 9:30 AM ET (alias for cross-module authority)
RTH_END_MINS = 960
RTH_SESSION_MINUTES = RTH_END_MINS - RTH_START_MINS  # 390 = single RTH session length as 1m bars


def rth_clock_js_source() -> str:
    """Served JS projection of the one RTH open/close authority.

    Frontend must consume these names. Re-encoding 570/960 (or 9:30/16:00) in
    HTML/JS is a second producer of the same boundary (F09). Raises rather than
    emitting a partial assignment so a failed projection cannot look like truth.
    """
    start = int(RTH_START_MINS)
    end = int(RTH_END_MINS)
    if start != RTH_START_MINS or end != RTH_END_MINS:
        raise TypeError("RTH clock authority must be integer minutes")
    if not (0 <= start < end <= 24 * 60):
        raise ValueError("RTH clock authority out of minute-of-day range")
    return (
        f"window.ED_RTH_START_MINS={start};\n"
        f"window.ED_RTH_END_MINS={end};\n"
    )


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


# ── Collect-window authority (RC-183, operator law 2026-08-01, non-negotiable) ──────────
# `price_bars_1m` persists ET bar-END minutes (555, min(975, cash_close+15)] on trading days
# only — 08:15–15:15 CT. The app gathers from 08:15 CT because it must be ready before the
# open, and SPY/QQQ-class ETFs trade to 16:15 ET. This is NEITHER classic cash RTH [570,960)
# NOR vendor extended hours, which is exactly why it needs its own named authority: three
# different windows governed one table and nothing encoded the law.
# MEASURED 2026-08-01 before the lock: 1,224,370 of 2,537,437 rows (48.25%) sat outside it —
# 820,531 from the ungated Schwab backfill, 315,660 from the accumulator's wider 540–990
# buffer, and the completeness checker measured a THIRD grid.
# RESTORED 2026-08-03: these four symbols were destroyed by the RC-210 worktree wipe, leaving
# `EdDB.upsert_1m_bars` ungated in production and `tools/rth_completeness_check_v1` unable to
# import. Rebuilt against the surviving negative-control spec in
# `tests/test_collect_window_law_v1.py`, which is the authority for every boundary below.
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


def hours_until_session_close_et(
    now: datetime,
    expiry_et_date: str | None = None,
) -> float | None:
    """Hours from `now` to RTH session close on `expiry_et_date` (default: now's date).

    Early-close sessions use 13:00 ET; regular sessions 16:00 ET. Returns None when
    already at/after that close, when the date is a full holiday, or when the date
    cannot be parsed. Uncovered calendar years use the regular 16:00 close so a
    LEAP expiry is not dropped (same as time_to_expiry_years).
    """
    d = str(expiry_et_date)[:10] if expiry_et_date else now.strftime("%Y-%m-%d")
    if d in US_EQUITY_FULL_HOLIDAYS_ET:
        return None
    close_mins = session_close_mins_for_et_date(d)
    if close_mins is None:
        close_mins = US_EQUITY_EARLY_CLOSE_MINS_ET.get(d, RTH_END_MINS)
    try:
        y, mo, dd = int(d[0:4]), int(d[5:7]), int(d[8:10])
    except (ValueError, IndexError):
        return None
    tz = now.tzinfo or ET
    close_dt = datetime(y, mo, dd, close_mins // 60, close_mins % 60, tzinfo=tz)
    # Instant elapsed hours, not civil timedelta. Same-tzinfo subtraction ignores DST
    # (spring-forward Friday→Monday wall 77.5h vs UTC 76.5h).
    now_aware = now if now.tzinfo is not None else now.replace(tzinfo=tz)
    secs = close_dt.timestamp() - now_aware.timestamp()
    if secs <= 0:
        return None
    return round(secs / 3600.0, 2)


def is_trading_day_et(et_date: str) -> bool:
    """True iff `et_date` (YYYY-MM-DD) is a US equity TRADING day — the canonical date-level
    authority for analysis scoping (RC-54).

    Weekday AND not a full holiday AND inside a covered calendar year (uncovered years fail
    closed). Use this to exclude weekend/holiday rows from ANY measurement: a market-closed
    row has frozen spot and stale IV, so including it drags every statistic toward "nothing
    moved". Timestamp-level callers use is_tradable_session_ts_utc (RTH minutes) or
    is_capturable_session (extended hours) instead.
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

    Mirrors market_context._derive_session's calendar logic (weekday -> holiday
    -> hours) as a single boolean, and takes an optional `now` for deterministic
    testing. Callers pass now_et() live; offline/replay callers pass their clock.
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


def time_to_expiry_years(expiry_et_date: str, now: "datetime | None" = None) -> float | None:
    """Canonical INTRADAY time-to-expiry in years (ACT/365) — the SINGLE SOURCE of T for
    every Black-Scholes greek (gamma, charm, ...).

    T is measured from `now` (ET; defaults to now_et()) to the option's SESSION CLOSE on its
    expiration date — 16:00 ET normally, 13:00 ET on early-close days — because US index/ETF
    options are PM-settled at the close. This replaces the per-site day-count/floor conventions
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
    close_mins = US_EQUITY_EARLY_CLOSE_MINS_ET.get(d, RTH_END_MINS)
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


def next_rth_session_et(now: datetime | None = None) -> tuple[str, str]:
    """Next valid RTH session as (ISO date, weekday name).

    Uses this module's calendar only: `is_trading_day_et` + `session_close_mins_for_et_date`.
    If `now` is on a trading day before that day's close, that date is next RTH.
    Weekends, full holidays, uncovered years, and post-close (including early close)
    walk forward. Does not invent a second holiday table.
    """
    n = now if now is not None else now_et()
    if n.tzinfo is None:
        n = n.replace(tzinfo=ET)
    else:
        n = n.astimezone(ET)
    mins = n.hour * 60 + n.minute + (1 if n.second or n.microsecond else 0)
    d = n.date()
    iso = d.isoformat()
    if is_trading_day_et(iso):
        close = session_close_mins_for_et_date(iso)
        if close is not None and mins < close:
            return iso, n.strftime("%A")
    for i in range(1, 21):
        nxt = d + timedelta(days=i)
        iso_n = nxt.isoformat()
        if is_trading_day_et(iso_n):
            return iso_n, nxt.strftime("%A")
    raise RuntimeError("no trading day in 21-day lookahead — calendar coverage ended")
