"""RC-181 — the non-negotiable post-RTH completeness check, offline behavior.

The scheduled job's first live firing is unattended; these bind the parts that must never
drift: the census counts real session minutes, a non-trading day is a clean no-op, and the
hole classifier treats only `vendor > ours` as loss — a checker that cries HOLES on thin
names' no-trade minutes trains the operator to ignore it (measured 2026-08-01: 2,123 "missing"
minutes on 2026-07-31 were FN 356==356, PSCI 3==3, BBIO 372==372 — true emptiness).
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

os.environ.setdefault("PYTEST_CURRENT_TEST", "boot")

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.rth_completeness_check_v1 import (  # noqa: E402
    classify_hole,
    session_completeness,
)


def test_classifier_only_calls_vendor_surplus_a_loss():
    assert classify_hole(ours=356, vendor=356) == "VENDOR_EMPTY"
    assert classify_hole(ours=3, vendor=3) == "VENDOR_EMPTY"
    assert classify_hole(ours=292, vendor=233) == "VENDOR_EMPTY", (
        "holding MORE than the vendor is not a loss"
    )
    assert classify_hole(ours=100, vendor=390) == "LOST"
    assert classify_hole(ours=0, vendor=None) == "UNSERVABLE"


def test_non_trading_day_is_a_clean_noop(tmp_path):
    db = tmp_path / "d.db"
    sqlite3.connect(str(db)).close()
    rep = session_completeness(str(db), "2026-08-01")  # a Saturday forever
    assert rep["session"] is False
    assert rep["total_missing"] == 0


def test_census_counts_session_minutes_against_the_grid(tmp_path):
    from datetime import datetime, timedelta

    from time_et import ET, is_trading_day_et

    # most recent real trading day
    probe = datetime.now(ET).date()
    while not is_trading_day_et(probe.isoformat()):
        probe -= timedelta(days=1)
    d = probe.isoformat()

    db = tmp_path / "d.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE price_bars_1m (ticker TEXT, bar_start_ts_utc REAL, "
                "bar_end_ts_utc REAL, open REAL, high REAL, low REAL, close REAL, "
                "volume REAL, source TEXT)")
    for k in range(10):  # ten bars ending 09:31..09:40 ET
        ts = datetime(probe.year, probe.month, probe.day, 9, 31 + k, tzinfo=ET).timestamp()
        con.execute("INSERT INTO price_bars_1m VALUES (?,?,?,?,?,?,?,?,?)",
                    ("ZZZ", ts - 60, ts, 1, 1, 1, 100.0, 10.0, "unit"))
    con.commit()
    con.close()

    rep = session_completeness(str(db), d)
    assert rep["session"] is True
    assert rep["tickers"]["ZZZ"]["present"] == 10
    assert rep["tickers"]["ZZZ"]["missing"] == rep["expected_per_ticker"] - 10
