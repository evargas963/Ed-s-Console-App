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

import json  # noqa: E402
import types  # noqa: E402

import tools.rth_completeness_check_v1 as C  # noqa: E402
from tools.rth_completeness_check_v1 import (  # noqa: E402
    classify_hole,
    session_completeness,
)


def _queued_sessions(*reports):
    """A session_completeness stand-in that returns the queued reports in order (measure,
    then re-measure after backfill)."""
    it = iter(reports)
    return lambda db, et_date: next(it)


def _holes_report(total=2144):
    return {"session": True, "total_missing": total, "tickers_with_holes": 1,
            "expected_per_ticker": 420,
            "tickers": {"FN": {"expected": 420, "present": 356, "missing": 64}}}


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

    from app.domain.time_et import ET, is_trading_day_et

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


# ── Observability (RC-181 follow-up): the durable final record the scheduled task leaves ──
# The operator saw only "HOLES total_missing=2144" and had no durable way to see it ended a PASS.
# These bind the four outcomes to a readable artifact + fail-closed exit code.


def test_apparent_holes_zero_vendor_loss_leaves_durable_pass(tmp_path, monkeypatch):
    """Scenario 1: grid holes remain after backfill, but the vendor has no more than us → the
    artifact says COMPLETE_VS_VENDOR / VENDOR_RECONCILED_ZERO_LOSS and the exit code is 0."""
    report = tmp_path / "rth_completeness_latest.json"
    monkeypatch.setattr(C, "session_completeness",
                        _queued_sessions(_holes_report(2144), _holes_report(2144)))
    monkeypatch.setattr(C, "vendor_reconcile", lambda db, d, tks: {
        "tickers": {"FN": {"ours": 356, "vendor": 356, "verdict": "VENDOR_EMPTY"}},
        "lost_minutes": 0})
    monkeypatch.setattr(C, "subprocess", types.SimpleNamespace(
        run=lambda *a, **k: types.SimpleNamespace(returncode=0, stdout="backfilled", stderr="")))

    rc = C.run("db", "2026-08-27", 0, True, report)

    assert rc == 0, "zero real loss must exit 0 (fail-closed preserved)"
    rec = json.loads(report.read_text(encoding="utf-8"))
    assert rec["final_status"] == "COMPLETE_VS_VENDOR"
    assert rec["completion_path"] == "VENDOR_RECONCILED_ZERO_LOSS"
    assert rec["grid_missing"] == 2144 and rec["lost_vs_vendor"] == 0
    assert rec["backfill_exit"] == 0 and rec["exit_code"] == 0
    # HOLES is a recorded step, never the final word
    assert any("HOLES" in s for s in rec["steps"]) and rec["final_status"] != "HOLES"


def test_vendor_has_bars_we_lack_is_durable_lost_data_nonzero_exit(tmp_path, monkeypatch):
    """Scenario 2: the vendor holds minutes we do not → durable LOST_DATA and a non-zero exit."""
    report = tmp_path / "rth_completeness_latest.json"
    monkeypatch.setattr(C, "session_completeness",
                        _queued_sessions(_holes_report(2144), _holes_report(2144)))
    monkeypatch.setattr(C, "vendor_reconcile", lambda db, d, tks: {
        "tickers": {"FN": {"ours": 100, "vendor": 390, "verdict": "LOST"}},
        "lost_minutes": 290})
    monkeypatch.setattr(C, "subprocess", types.SimpleNamespace(
        run=lambda *a, **k: types.SimpleNamespace(returncode=0, stdout="", stderr="")))

    rc = C.run("db", "2026-08-27", 0, True, report)

    assert rc == 1, "real vendor loss must exit non-zero (fail-closed)"
    rec = json.loads(report.read_text(encoding="utf-8"))
    assert rec["final_status"] == "LOST_DATA" and rec["completion_path"] == "LOST_DATA"
    assert rec["lost_vs_vendor"] == 290 and rec["exit_code"] == 1


def test_measurement_failure_is_durable_and_exits_2(tmp_path, monkeypatch):
    """Scenario 3: a measurement error is never a pass — durable MEASUREMENT_FAILED, exit 2."""
    report = tmp_path / "rth_completeness_latest.json"

    def boom(db, et_date):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(C, "session_completeness", boom)

    rc = C.run("db", "2026-08-27", 0, True, report)

    assert rc == 2, "unmeasurable is never a pass (RC-57)"
    rec = json.loads(report.read_text(encoding="utf-8"))
    assert rec["final_status"] == "MEASUREMENT_FAILED" and rec["exit_code"] == 2
    assert "database is locked" in rec["error"]


def test_scheduled_task_leaves_readable_artifact_after_process_exits(tmp_path):
    """Scenario 4: run the tool as a real subprocess; the artifact is present + parseable AFTER
    the process has exited. A non-trading date reaches NO_SESSION without touching a live db."""
    import subprocess as _sp

    report = tmp_path / "rth_completeness_latest.json"
    r = _sp.run(
        [sys.executable, str(REPO / "tools" / "rth_completeness_check_v1.py"),
         "--db", str(tmp_path / "none.db"), "--date", "2026-08-01",  # a Saturday forever
         "--report", str(report)],
        capture_output=True, text=True, timeout=120,
        env={**os.environ, "PYTEST_CURRENT_TEST": "boot"})

    assert r.returncode == 0, f"NO_SESSION must exit 0; stderr={r.stderr[-400:]}"
    assert report.exists(), "no durable artifact was left after the process exited"
    rec = json.loads(report.read_text(encoding="utf-8"))
    assert rec["final_status"] == "NO_SESSION" and rec["exit_code"] == 0
    assert "written_at_utc" in rec


def test_persistence_failure_on_a_complete_path_exits_nonzero(tmp_path, monkeypatch, capsys):
    """The pythonw silent-success hole: a report-write failure on a 0-verdict COMPLETE run must
    NOT exit 0 — otherwise Task Scheduler reports success with no console and no artifact. Force
    the atomic write/rename to fail on an otherwise-COMPLETE path and prove the process exits
    non-zero while still emitting the underlying data verdict."""
    # a report path whose PARENT is a regular file: mkdir(parents=True, exist_ok=True) raises,
    # so the temp-write + rename cannot proceed — a real, forced persistence failure.
    blocker = tmp_path / "parent_is_a_file"
    blocker.write_text("x", encoding="utf-8")
    report = blocker / "rth_completeness_latest.json"
    complete = {"session": True, "total_missing": 0, "tickers": {},
                "expected_per_ticker": 420, "tickers_with_holes": 0}
    monkeypatch.setattr(C, "session_completeness", _queued_sessions(complete))

    rc = C.run("db", "2026-08-27", 0, False, report)

    assert rc != 0, "a durable-observability failure must not exit 0 (pythonw silent success)"
    assert rc == C.PERSIST_FAILED_EXIT
    assert not report.exists(), "the artifact genuinely could not be persisted"
    seen = capsys.readouterr()
    # the underlying data verdict (COMPLETE / data-exit 0) is retained in stderr + stdout
    assert "COMPLETE" in (seen.out + seen.err)
    assert '"data_verdict_exit": 0' in seen.out
