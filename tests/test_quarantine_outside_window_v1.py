"""RC-183 — the quarantine mover: reversible, exact, and judged by the seam's own authority.

Named check: collect_window_single_law (the mover is the disposition arm of that law).
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

os.environ.setdefault("PYTEST_CURRENT_TEST", "boot")

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from app.domain.time_et import ET  # noqa: E402

TOOL = REPO / "tools" / "quarantine_outside_window_bars_v1.py"


def _mk_db(p: Path) -> tuple[int, int]:
    con = sqlite3.connect(str(p))
    con.execute("CREATE TABLE price_bars_1m (ticker TEXT, bar_start_ts_utc REAL, "
                "bar_end_ts_utc REAL, open REAL, high REAL, low REAL, close REAL, "
                "volume REAL, source TEXT)")
    mon = lambda h, m: datetime(2026, 8, 3, h, m, tzinfo=ET).timestamp()  # noqa: E731
    legal = [mon(9, 16), mon(12, 0), mon(16, 15)]
    illegal = [mon(5, 0), mon(9, 15), mon(16, 30),
               datetime(2026, 8, 1, 11, 0, tzinfo=ET).timestamp()]  # Saturday
    for ts in legal + illegal:
        con.execute("INSERT INTO price_bars_1m VALUES (?,?,?,?,?,?,?,?,?)",
                    ("ZZZ", ts - 60, ts, 1, 1, 1, 100.0, 10.0, "unit"))
    con.commit()
    con.close()
    return len(legal), len(illegal)


def _run(db: Path, *flags: str) -> dict:
    r = subprocess.run([sys.executable, str(TOOL), "--db", str(db), *flags],
                       capture_output=True, text=True, timeout=300)
    last = [ln for ln in (r.stdout or "").splitlines() if ln.strip().startswith("{")][-1]
    return json.loads(last)


def test_dry_run_counts_and_never_writes(tmp_path):
    db = tmp_path / "q.db"
    n_legal, n_illegal = _mk_db(db)
    rep = _run(db, )
    assert rep["status"] == "DRY_RUN"
    assert rep["outside_law_rows"] == n_illegal
    con = sqlite3.connect(str(db))
    assert con.execute("SELECT COUNT(*) FROM price_bars_1m").fetchone()[0] == n_legal + n_illegal
    assert not con.execute("SELECT name FROM sqlite_master WHERE name='price_bars_1m_quarantine'"
                           ).fetchone(), "a dry run created the quarantine table"
    con.close()


def test_execute_moves_exactly_and_restore_reverses(tmp_path, monkeypatch):
    db = tmp_path / "q.db"
    n_legal, n_illegal = _mk_db(db)
    # the tool demands a fresh backup — point its glob at a fixture backup dir via cwd trickery
    # is not possible (ROOT-anchored), so create a real dated backup file in the repo location
    # would touch the real tree; instead call the module functions directly for execute.
    sys.path.insert(0, str(REPO / "tools"))
    import importlib

    m = importlib.import_module("quarantine_outside_window_bars_v1")
    monkeypatch.setattr(m, "_fresh_backup_exists", lambda: "fixture-backup")
    monkeypatch.setattr(sys, "argv",
                        ["x", "--db", str(db), "--execute", "--expected", str(n_illegal)])
    rc = m.main()
    assert rc == 0
    con = sqlite3.connect(str(db))
    assert con.execute("SELECT COUNT(*) FROM price_bars_1m").fetchone()[0] == n_legal
    assert con.execute("SELECT COUNT(*) FROM price_bars_1m_quarantine").fetchone()[0] == n_illegal
    reasons = {r[0] for r in con.execute("SELECT DISTINCT reason FROM price_bars_1m_quarantine")}
    assert reasons == {"RC-183 outside 08:15-15:15 CT collect window"}
    con.close()

    # reversibility — the exact inverse
    monkeypatch.setattr(sys, "argv", ["x", "--db", str(db), "--restore", "--execute"])
    rc = m.main()
    assert rc == 0
    con = sqlite3.connect(str(db))
    assert con.execute("SELECT COUNT(*) FROM price_bars_1m").fetchone()[0] == n_legal + n_illegal
    assert con.execute("SELECT COUNT(*) FROM price_bars_1m_quarantine").fetchone()[0] == 0
    con.close()


def test_expected_mismatch_refuses(tmp_path, monkeypatch):
    db = tmp_path / "q.db"
    _mk_db(db)
    sys.path.insert(0, str(REPO / "tools"))
    import importlib

    m = importlib.import_module("quarantine_outside_window_bars_v1")
    monkeypatch.setattr(m, "_fresh_backup_exists", lambda: "fixture-backup")
    monkeypatch.setattr(sys, "argv", ["x", "--db", str(db), "--execute", "--expected", "999"])
    assert m.main() == 2, "a count mismatch must refuse to execute — that is the checkpoint"
