"""RC-481/RC-479: the liveness check catches a down/stalled console AND a dead producer.

Driven against synthetic DBs with now_et pinned inside/outside the required window, so the
two failure modes (no fresh snapshots; fresh snapshots but mc_paths NULL) each return an
ALERT, and a healthy collecting-and-writing state returns OK.
"""
from __future__ import annotations

import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import tools.console_liveness_check as clc  # noqa: E402

# 2026-08-25 is a Tuesday and a trading day (production collected snapshots that day).
IN_WINDOW = datetime(2026, 8, 25, 10, 0)     # 10:00 ET, inside [09:30, close+15]
BEFORE_WINDOW = datetime(2026, 8, 25, 8, 0)  # 08:00 ET, before 09:30


def _db(tmp_path: Path, *, newest_age_s: float, mc_present: bool) -> str:
    p = tmp_path / "snap.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE snapshots (ts_utc REAL, mc_paths TEXT)")
    now = time.time()
    mc = "[1,2,3]" if mc_present else None
    con.executemany(
        "INSERT INTO snapshots (ts_utc, mc_paths) VALUES (?,?)",
        [(now - newest_age_s - 30, mc), (now - newest_age_s, mc)],
    )
    con.commit()
    con.close()
    return str(p)


def test_ok_when_fresh_and_producer_live(tmp_path, monkeypatch):
    monkeypatch.setattr(clc, "now_et", lambda: IN_WINDOW)
    db = _db(tmp_path, newest_age_s=60, mc_present=True)
    assert clc.check(db) == 0


def test_alert_when_collection_stalled(tmp_path, monkeypatch):
    monkeypatch.setattr(clc, "now_et", lambda: IN_WINDOW)
    db = _db(tmp_path, newest_age_s=1200, mc_present=True)   # 20min old > STALE_LIMIT
    assert clc.check(db) == 1


def test_alert_dead_producer_when_fresh_but_mc_null(tmp_path, monkeypatch):
    monkeypatch.setattr(clc, "now_et", lambda: IN_WINDOW)
    db = _db(tmp_path, newest_age_s=60, mc_present=False)    # fresh, but mc_paths NULL
    assert clc.check(db) == 1


def test_ok_outside_window_regardless_of_db(tmp_path, monkeypatch):
    monkeypatch.setattr(clc, "now_et", lambda: BEFORE_WINDOW)
    db = _db(tmp_path, newest_age_s=99999, mc_present=False)  # would ALERT if in-window
    assert clc.check(db) == 0
