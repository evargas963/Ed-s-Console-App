"""Cursor-audit F6: intraday liveness must not stay green while an individual enrolled ticker is
dark. console_liveness_check's freshness (MAX ts_utc) and producer (COUNT mc_paths) checks are both
AGGREGATE — one live ticker (SPY) masks any specific dark one. The per-ticker check reads each
enrolled collecting-category ticker's own last successful collection clock
(logging_universe.last_background_log_ts_utc) and ALERTs when a WAS-collecting ticker went dark,
while excluding never-collected (NULL) tickers (fresh enrollment / quarantined non-collector).
"""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import tools.console_liveness_check as liv


def _make_db(path: str, snapshots, universe) -> None:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE snapshots (ts_utc REAL, mc_paths TEXT)")
    con.executemany(
        "INSERT INTO snapshots (ts_utc, mc_paths) VALUES (?, ?)",
        [(ts, "paths" if mc else None) for ts, mc in snapshots],
    )
    con.execute(
        "CREATE TABLE logging_universe ("
        "ticker TEXT PRIMARY KEY, category TEXT NOT NULL, enrollment_source TEXT, "
        "enrolled_ts_utc REAL NOT NULL, last_seen_ts_utc REAL NOT NULL, "
        "last_background_log_ts_utc REAL)"
    )
    con.executemany(
        "INSERT INTO logging_universe VALUES (?,?,?,?,?,?)",
        [(tk, cat, "test", 1.0, 1.0, lastbg) for tk, cat, lastbg in universe],
    )
    con.commit()
    con.close()


def test_per_ticker_dark_alerts_while_aggregate_fresh_f6(monkeypatch, tmp_path):
    """A live SPY keeps the aggregate fresh; an enrolled ticker that WAS collecting but went dark
    20 minutes ago must still trip the ALERT (return 1)."""
    monkeypatch.setattr(liv, "_required_window_now", lambda: (True, "test window"))
    monkeypatch.setattr(liv, "_emit", lambda *a, **k: None)
    now = time.time()
    dbp = str(tmp_path / "live.db")
    _make_db(
        dbp,
        snapshots=[(now - 5, True)],   # aggregate: fresh + producer alive
        universe=[("SPY", "core", now - 5), ("DARKX", "user_persisted", now - 1200)],
    )
    assert liv.check(dbp) == 1


def test_never_collected_and_fresh_do_not_alert_f6(monkeypatch, tmp_path):
    """A never-collected (NULL) enrolled ticker is excluded (fresh enrollment / quarantined
    non-collector), and fresh tickers pass — so the check stays OK (return 0)."""
    monkeypatch.setattr(liv, "_required_window_now", lambda: (True, "test window"))
    monkeypatch.setattr(liv, "_emit", lambda *a, **k: None)
    now = time.time()
    dbp = str(tmp_path / "live2.db")
    _make_db(
        dbp,
        snapshots=[(now - 5, True)],
        universe=[("SPY", "core", now - 5), ("QQQ", "core", now - 30),
                  ("NEWX", "user_persisted", None)],   # never collected -> excluded
    )
    assert liv.check(dbp) == 0


def test_missing_enrollment_table_degrades_to_no_false_alert_f6(monkeypatch, tmp_path):
    """If logging_universe is absent, the per-ticker check is skipped (silent) rather than
    crashing or false-alarming — the aggregate checks still govern."""
    monkeypatch.setattr(liv, "_required_window_now", lambda: (True, "test window"))
    monkeypatch.setattr(liv, "_emit", lambda *a, **k: None)
    now = time.time()
    dbp = str(tmp_path / "live3.db")
    con = sqlite3.connect(dbp)
    con.execute("CREATE TABLE snapshots (ts_utc REAL, mc_paths TEXT)")
    con.execute("INSERT INTO snapshots (ts_utc, mc_paths) VALUES (?, ?)", (now - 5, "paths"))
    con.commit()
    con.close()
    assert liv.check(dbp) == 0
