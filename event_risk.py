"""
event_risk.py — Known macro / issuer event calendar for day-trading stack gating.

Update MACRO_ALERT_DATES and SYMBOL_EARNINGS manually or from your data vendor.

Wiring a live calendar (implement in server or a daily job; keep this module sync/cheap):
  - **Macro:** Fed FOMC pdf/calendar, BLS CPI schedule, CBOE holiday calendar — curate high-impact ET dates into MACRO_ALERT_DATES or load JSON at startup.
  - **Earnings:** Vendor APIs (e.g. Polygon, Finnhub earnings endpoints) or issuer IR pages — cache `symbol -> [ISO dates]` and refresh daily.
  - **Unified:** Paid terminals (FactSet, Refinitiv) or a repo CSV you edit; avoid scraping without ToS review.

This file is not a substitute for a live API; it is the policy hook `assess_event_risk(ticker)` consumes.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import List, Tuple
from app.domain.time_et import now_et

# US session date (ET) — ISO strings. Broad risk: CPI, FOMC, NFP-heavy days, major quad witching.
# Keep tight: only days where you want elevated or high event_risk.
# Source: maintain alongside your desk calendar (Fed + CPI schedule).
MACRO_ALERT_DATES: frozenset[str] = frozenset({
    "2026-01-28",  # example placeholder — replace with real CPI/FOMC dates you trade around
    "2026-03-18",
    "2026-06-17",
    "2026-09-16",
    "2026-12-16",
})

# Issuer earnings (after-market / BMO) — settlement date in ET. Extend per symbol.
SYMBOL_EARNINGS: dict[str, List[str]] = {
    # META: approximate quarterly pattern — verify against investor relations each quarter.
    "META": ["2026-01-29", "2026-04-30", "2026-07-30", "2026-10-29"],
    "NVDA": ["2026-02-26", "2026-05-28", "2026-08-27", "2026-11-19"],
}


def session_date_et(now: datetime | None = None) -> date:
    if now is None:
        now = now_et()
    return now.date()


def assess_event_risk(ticker: str, now: datetime | None = None) -> Tuple[str, str]:
    """
    Returns (level, detail).
    level: "none" | "elevated" | "high"
    """
    t = (ticker or "").upper().strip()
    d = session_date_et(now)
    ds = d.isoformat()
    reasons: list[str] = []

    if ds in MACRO_ALERT_DATES:
        reasons.append("Macro calendar alert (CPI/FOMC/OPEX tier — verify)")

    earn = SYMBOL_EARNINGS.get(t, [])
    if ds in earn:
        reasons.append(f"{t} earnings session — vol / pin / gap risk")

    if not reasons:
        return "none", ""

    # Earnings on single name = high for that symbol; macro alone = elevated
    if any(t in r or "earnings" in r for r in reasons) and t in SYMBOL_EARNINGS:
        return "high", "; ".join(reasons)
    return "elevated", "; ".join(reasons)

