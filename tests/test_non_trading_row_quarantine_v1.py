"""RC-283 — weekend rows already banked must be repaired, not just stopped.

RC-278 closed the two option-chain WRITERS that gated on the clock and never the calendar.
It repaired nothing already in the tables. The tool that exists for exactly that repair,
`tools/relabel_non_trading_sessions_v1.py`, addressed `snapshots` and nothing else —
Cursor's audit measured `option_chain references: 0` — and was wired to nothing.

MEASURED on the production DB before this change: `option_chain_morning_full` 14 et_dates,
0 non-trading; `option_chain_accrual` 6 et_dates, ONE non-trading row (QQQ, 2026-08-02, a
Sunday, et_minute 919, 212 strikes, source terrain_wide_chain_accrual).

QUARANTINE, NOT DELETE. Those rows are the only evidence of the RC-278 window. Deleting
them leaves a gap indistinguishable from "we were not collecting". Relabelling is not
available either: an accrual row is not mislabelled, it should not exist at all.

These tests drive a temp DB, never the production one.
"""

from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO))

import relabel_non_trading_sessions_v1 as R  # noqa: E402

SUNDAY = "2026-08-02"
FRIDAY = "2026-07-31"


def _db(tmp_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(tmp_path / "q.db")
    con.execute(
        "CREATE TABLE option_chain_accrual (ticker TEXT, ts_utc REAL, et_date TEXT, "
        "et_minute INTEGER, spot REAL, n_strikes INTEGER, per_strike_json TEXT, source TEXT)")
    con.executemany(
        "INSERT INTO option_chain_accrual VALUES (?,?,?,?,?,?,?,?)",
        [("QQQ", 1.0, SUNDAY, 919, 500.0, 212, "[]", "terrain_wide_chain_accrual"),
         ("SPY", 2.0, FRIDAY, 600, 640.0, 300, "[]", "terrain_wide_chain_accrual")])
    con.commit()
    return con


def test_dry_run_reports_without_moving_anything(tmp_path):
    """A repair tool that writes before it reports is one nobody runs twice."""
    con = _db(tmp_path)
    rep = R.quarantine_non_trading_option_rows(con, execute=False, now_utc=time.time())
    assert rep["option_chain_accrual"]["non_trading"] == 1
    assert rep["option_chain_accrual"]["moved"] == 0
    assert con.execute("SELECT COUNT(*) FROM option_chain_accrual").fetchone()[0] == 2


def test_the_sunday_row_leaves_the_live_table(tmp_path):
    con = _db(tmp_path)
    rep = R.quarantine_non_trading_option_rows(con, execute=True, now_utc=1_800_000_000.0)
    assert rep["option_chain_accrual"]["moved"] == 1
    live = con.execute("SELECT ticker, et_date FROM option_chain_accrual").fetchall()
    assert live == [("SPY", FRIDAY)], f"live table still serves a closed-day row: {live}"


def test_the_evidence_survives_intact(tmp_path):
    """Deleting would destroy the only proof of the RC-278 window."""
    con = _db(tmp_path)
    R.quarantine_non_trading_option_rows(con, execute=True, now_utc=1_800_000_000.0)
    row = con.execute(
        "SELECT ticker, et_date, et_minute, n_strikes, source, quarantine_reason, "
        "quarantined_at_utc FROM option_chain_accrual_quarantine").fetchall()
    assert len(row) == 1
    assert row[0][:5] == ("QQQ", SUNDAY, 919, 212, "terrain_wide_chain_accrual")
    assert row[0][5] == "RC-283 non_trading_day"
    assert row[0][6] == 1_800_000_000.0, "the sweep timestamp is not recorded"


def test_a_trading_day_row_is_never_touched(tmp_path):
    """The negative control: a repair that over-reaches is worse than the contamination."""
    con = _db(tmp_path)
    R.quarantine_non_trading_option_rows(con, execute=True, now_utc=time.time())
    assert con.execute(
        "SELECT COUNT(*) FROM option_chain_accrual WHERE et_date=?", (FRIDAY,)
    ).fetchone()[0] == 1
    assert con.execute(
        "SELECT COUNT(*) FROM option_chain_accrual_quarantine WHERE et_date=?", (FRIDAY,)
    ).fetchone()[0] == 0


def test_a_second_run_is_idempotent(tmp_path):
    """A nightly sweep runs forever; it must not duplicate evidence each night."""
    con = _db(tmp_path)
    R.quarantine_non_trading_option_rows(con, execute=True, now_utc=1_800_000_000.0)
    second = R.quarantine_non_trading_option_rows(con, execute=True, now_utc=1_800_000_100.0)
    assert second["option_chain_accrual"]["non_trading"] == 0
    assert second["option_chain_accrual"]["moved"] == 0
    assert con.execute(
        "SELECT COUNT(*) FROM option_chain_accrual_quarantine").fetchone()[0] == 1


def test_a_missing_table_is_reported_not_crashed(tmp_path):
    """option_chain_morning_full may not exist on every machine."""
    con = _db(tmp_path)
    rep = R.quarantine_non_trading_option_rows(con, execute=True, now_utc=time.time())
    assert rep["option_chain_morning_full"]["missing_table"] == 1


def test_the_tool_actually_reaches_the_option_tables():
    """Cursor measured `option_chain references: 0`. That must never read zero again."""
    src = (REPO / "tools" / "relabel_non_trading_sessions_v1.py").read_text(encoding="utf-8")
    assert "option_chain_accrual" in src and "option_chain_morning_full" in src
    assert "OPTION_TABLES" in src


def test_snapshots_are_relabelled_and_option_rows_are_moved():
    """The two surfaces need DIFFERENT repairs and the tool must not confuse them.

    A snapshot taken while the market is shut is a real observation wearing the wrong
    label. An accrual row is a banked wide chain for a session that never happened.
    """
    src = (REPO / "tools" / "relabel_non_trading_sessions_v1.py").read_text(encoding="utf-8")
    assert "UPDATE snapshots SET market_session='closed'" in src
    assert "snapshots" not in R.OPTION_TABLES, (
        "snapshots must be relabelled, never quarantined — it holds real observations")
