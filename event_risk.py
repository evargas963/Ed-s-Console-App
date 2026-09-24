"""
event_risk.py — scheduled-event risk for the traded symbol, from SOURCED calendars only.

Earnings: the Nasdaq earnings calendar collected by tools/world_earnings_ingest.py into the
console database (`world_earnings`) -- every symbol, the same way.

Macro (CPI / FOMC / NFP): no collector exists yet, so macro risk is UNKNOWN and says so.
This module used to carry five hand-typed "example placeholder" macro dates and an
"approximate" earnings list for two symbols (META, NVDA) -- guessed inputs to The Call
(audit P0, operator rules 2026-09-23: no fallbacks, universality).

Levels: "high" (the symbol reports earnings this session) | "unknown" (no sourced event;
macro not sourced). "none" is never claimed while a calendar is missing.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from datetime import date, datetime
from typing import Optional, Tuple

from time_et import now_et

EARNINGS_SOURCE = "Nasdaq earnings calendar (world_earnings)"
_CACHE_TTL_SEC = 600.0
_cache: dict[str, tuple[float, Optional[dict[str, str]]]] = {}
_cache_lock = threading.Lock()


def session_date_et(now: datetime | None = None) -> date:
    if now is None:
        now = now_et()
    return now.date()


def _earnings_for_date(ds: str, db_path: str | None = None) -> Optional[dict[str, str]]:
    """{SYMBOL: time_hint} reporting on `ds`, or None when that date was never fetched (or
    the table does not exist) -- "not fetched" is not "no earnings"."""
    key = f"{db_path or ''}|{ds}"
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < _CACHE_TTL_SEC:
            return hit[1]
    if db_path is None:
        from db_authority import canonical_console_db_path
        db_path = str(canonical_console_db_path())
    result: Optional[dict[str, str]]
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)
        try:
            rows = con.execute(
                "SELECT symbol, time_hint FROM world_earnings WHERE date = ?", (ds,)).fetchall()
        finally:
            con.close()
        result = {str(s).upper(): (h or "") for s, h in rows} if rows else None
    except sqlite3.Error:
        result = None
    with _cache_lock:
        _cache[key] = (now, result)
    return result


def assess_event_risk(ticker: str, now: datetime | None = None, *,
                      db_path: str | None = None) -> Tuple[str, str]:
    """(level, detail). level: "high" | "unknown"."""
    t = (ticker or "").upper().strip().lstrip("$")
    ds = session_date_et(now).isoformat()
    earnings = _earnings_for_date(ds, db_path)
    if earnings is not None and t in earnings:
        hint = earnings[t]
        return "high", (f"{t} earnings session{(' (' + hint + ')') if hint else ''} "
                        f"-- {EARNINGS_SOURCE}")
    earn_note = (f"no {t} earnings today ({EARNINGS_SOURCE})" if earnings is not None
                 else f"earnings calendar not fetched for {ds}")
    return "unknown", f"{earn_note}; macro calendar (CPI/FOMC) not sourced"
