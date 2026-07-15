"""Central Time (America/Chicago) research session authority (Stage 1; research-only).

FOUNDATIONAL TIMEZONE CONTRACT:
  * UTC is the immutable storage / join / ordering / causal timestamp authority.
  * America/Chicago is the canonical application/research/cohort/display timezone.
  * The official exchange calendar (data/trading_calendar/us_equities.json)
    governs session membership, holidays, and early closes.
  * U.S. equity RTH is REPRESENTED to the operator as 08:30-15:00 Central Time.
  * No fixed UTC offset is used; DST is resolved via zoneinfo.
  * Eastern Time appears ONLY as the external exchange convention stored in the
    calendar (open_et/close_et); it is never the canonical application contract.

This module changes NO production session behavior. It is the research cohort
authority for Stage 1 fixtures/contracts/reports.
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
CALENDAR_PATH = ROOT / "data" / "trading_calendar" / "us_equities.json"

CENTRAL = ZoneInfo("America/Chicago")
EXCHANGE_TZ = ZoneInfo("America/New_York")  # the calendar's ET convention only
UTC = timezone.utc

# Central Time session labels (application representation)
SESSION_RTH = "rth"
SESSION_PREMARKET = "premarket"
SESSION_AFTERHOURS = "afterhours"
SESSION_CLOSED = "closed"  # weekend / holiday / overnight full closure


def load_calendar(path: Path = CALENDAR_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _et_hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def _et_boundary_utc(d: date, hhmm: time) -> datetime:
    """Convert an exchange-convention ET wall time on date d to a UTC instant."""
    return datetime.combine(d, hhmm, tzinfo=EXCHANGE_TZ).astimezone(UTC)


def ct_clock(ts_utc: float) -> datetime:
    """The America/Chicago wall clock for a UTC instant (DST-resolved)."""
    return datetime.fromtimestamp(ts_utc, tz=UTC).astimezone(CENTRAL)


def rth_bounds_utc(d: date, cal: dict | None = None) -> tuple[datetime, datetime] | None:
    """RTH [open, close) as UTC instants for calendar date d, or None if the
    exchange is fully closed that day. Half-days use the early-close time."""
    cal = cal or load_calendar()
    iso = d.isoformat()
    if iso in set(cal.get("full_closures") or []):
        return None
    if d.weekday() >= 5:  # Sat/Sun
        return None
    open_et = _et_hhmm(cal["regular_session"]["open_et"])
    close_et = _et_hhmm(cal["regular_session"]["close_et"])
    for ec in cal.get("early_closes") or []:
        if ec.get("date") == iso:
            close_et = _et_hhmm(ec["close_et"])
            break
    return _et_boundary_utc(d, open_et), _et_boundary_utc(d, close_et)


def classify_session(ts_utc: float, cal: dict | None = None) -> str:
    """Classify a UTC instant into a Central-Time session label using the
    exchange calendar. Fully calendar/DST-governed; no fixed offset, no stored
    et_hour."""
    cal = cal or load_calendar()
    ct = ct_clock(ts_utc)
    bounds = rth_bounds_utc(ct.date(), cal)
    if bounds is None:
        return SESSION_CLOSED
    open_utc, close_utc = bounds
    now = datetime.fromtimestamp(ts_utc, tz=UTC)
    if open_utc <= now < close_utc:
        return SESSION_RTH
    # premarket window in CT is 03:00-08:30 CT; afterhours 15:00-19:00 CT
    pre_open = _et_boundary_utc(ct.date(), time(4, 0))   # 04:00 ET = 03:00 CT
    post_close_cap = _et_boundary_utc(ct.date(), time(20, 0))  # 20:00 ET = 19:00 CT
    if pre_open <= now < open_utc:
        return SESSION_PREMARKET
    if close_utc <= now < post_close_cap:
        return SESSION_AFTERHOURS
    return SESSION_CLOSED


def is_rth_ct(ts_utc: float, cal: dict | None = None) -> bool:
    return classify_session(ts_utc, cal) == SESSION_RTH


def ct_label(ts_utc: float) -> str:
    """Human CT label, e.g. '2026-01-05 08:35 CST'."""
    return ct_clock(ts_utc).strftime("%Y-%m-%d %H:%M %Z")


def is_early_close(d: date, cal: dict | None = None) -> bool:
    cal = cal or load_calendar()
    iso = d.isoformat()
    return any(ec.get("date") == iso for ec in cal.get("early_closes") or [])


def is_full_closure(d: date, cal: dict | None = None) -> bool:
    cal = cal or load_calendar()
    return d.isoformat() in set(cal.get("full_closures") or [])
