# institutional-synthetic-ok: a crafted thin prior-session tape proves the banked coverage stamp fires.
"""Audit round 2 (2026-08-25) — the banked prior-session tape carries the same coverage
honesty as the accumulator path.

WHAT WAS MEASURED: the >=LEVELS_PRIOR_SESSION_MIN_BARS floor existed only on the
accumulator path (t12/RC-227), while the banked fallback fires precisely WHEN coverage
is low — MTA sessions banked at 188/236/316 of 390 RTH bars served next-day PDH/PDL as
prior-day fact from a tape missing up to half the session, silently. The fix stamps the
prior_day family degraded with the measured count (levels still serve — a low banked
count is ambiguous between thin trading and a collection gap, so absence-of-warning was
the defect, not the values' existence).
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

ET = ZoneInfo("America/New_York")


def _seed_thin_prior_db(tmp_path: Path, ticker: str, prior_day: datetime,
                        n_bars: int) -> Path:
    dbp = tmp_path / "thin.db"
    con = sqlite3.connect(dbp)
    con.execute(
        "CREATE TABLE price_bars_1m (ticker TEXT, bar_start_ts_utc REAL, open REAL, "
        "high REAL, low REAL, close REAL, volume REAL)")
    start = prior_day.replace(hour=9, minute=30, second=0, microsecond=0)
    for i in range(n_bars):
        ts = (start + timedelta(minutes=i)).timestamp()
        con.execute(
            "INSERT INTO price_bars_1m VALUES (?,?,?,?,?,?,?)",
            (ticker, ts, 100.0 + i * 0.01, 100.2 + i * 0.01, 99.8 + i * 0.01,
             100.1 + i * 0.01, 1000))
    con.commit()
    con.close()
    return dbp


def test_thin_banked_prior_session_is_stamped_degraded(tmp_path, monkeypatch):
    import server

    prior = datetime(2026, 8, 21, tzinfo=ET)          # Friday
    session_date = datetime(2026, 8, 24, tzinfo=ET).date()  # Monday
    dbp = _seed_thin_prior_db(tmp_path, "THIN", prior, n_bars=180)

    class _StubDB:
        db_path = str(dbp)

    monkeypatch.setattr(server, "_liquidity_live_1m_overlay_bars", lambda tk: [])
    monkeypatch.setattr(server, "get_db", lambda: _StubDB())
    bars, source, degraded = server._canonical_price_level_bars("THIN", session_date)
    assert source == "banked_price_bars_1m"
    assert bars, "the thin tape still serves — the defect was silence, not existence"
    stamps = [d for d in degraded if d.get("family") == "prior_day"]
    assert stamps and "banked prior session" in stamps[0]["reason"], degraded
    assert "180" in stamps[0]["reason"], stamps


def test_full_banked_prior_session_carries_no_stamp(tmp_path, monkeypatch):
    import server

    prior = datetime(2026, 8, 21, tzinfo=ET)
    session_date = datetime(2026, 8, 24, tzinfo=ET).date()
    dbp = _seed_thin_prior_db(tmp_path, "FULL", prior, n_bars=390)

    class _StubDB:
        db_path = str(dbp)

    monkeypatch.setattr(server, "_liquidity_live_1m_overlay_bars", lambda tk: [])
    monkeypatch.setattr(server, "get_db", lambda: _StubDB())
    _bars, source, degraded = server._canonical_price_level_bars("FULL", session_date)
    assert source == "banked_price_bars_1m"
    assert [d for d in degraded if d.get("family") == "prior_day"] == []
