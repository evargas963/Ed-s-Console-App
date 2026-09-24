"""Event risk comes from sourced calendars only (audit P0, 2026-09-23).

It used to read five hand-typed "example placeholder" macro dates and an "approximate"
earnings list for META and NVDA only. Earnings now come from the Nasdaq calendar table
(world_earnings) for every symbol; macro is unknown until a collector exists; a missing
calendar is "unknown", never "none".
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

import event_risk


def _db(tmp_path, rows):
    p = tmp_path / "console.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE world_earnings (date TEXT, symbol TEXT, time_hint TEXT, fetched_at TEXT)")
    con.executemany("INSERT INTO world_earnings VALUES (?,?,?,datetime('now'))", rows)
    con.commit()
    con.close()
    event_risk._cache.clear()
    return str(p)


NOW = datetime(2026, 10, 21, 10, 0)


def test_any_symbol_on_the_calendar_is_high(tmp_path):
    db = _db(tmp_path, [("2026-10-21", "NFLX", "time-after-hours"), ("2026-10-21", "SIRI", "")])
    level, detail = event_risk.assess_event_risk("NFLX", NOW, db_path=db)
    assert level == "high" and "Nasdaq" in detail and "after-hours" in detail
    assert event_risk.assess_event_risk("siri", NOW, db_path=db)[0] == "high"


def test_off_calendar_is_unknown_never_none(tmp_path):
    db = _db(tmp_path, [("2026-10-21", "NFLX", "")])
    level, detail = event_risk.assess_event_risk("TSLA", NOW, db_path=db)
    assert level == "unknown" and "no TSLA earnings today" in detail and "macro" in detail


def test_an_unfetched_date_or_missing_table_is_unknown(tmp_path):
    db = _db(tmp_path, [("2026-10-20", "NFLX", "")])
    assert "not fetched" in event_risk.assess_event_risk("NFLX", NOW, db_path=db)[1]
    event_risk._cache.clear()
    assert event_risk.assess_event_risk("NFLX", NOW, db_path=str(tmp_path / "missing.db"))[0] == "unknown"


def test_no_hand_typed_dates_remain():
    import inspect
    src = inspect.getsource(event_risk)
    assert "MACRO_ALERT_DATES" not in src and "SYMBOL_EARNINGS" not in src
    assert '"2026-' not in src
