"""RC-51: db_maintenance runs ANALYZE (populates the empty planner stats), checkpoints the
WAL, and aborts on a missing file or failed integrity — never touching data."""
import sqlite3
import tempfile
from pathlib import Path

from tools.db_maintenance import (
    analyze,
    db_stats,
    quick_check,
    run_maintenance,
    wal_checkpoint_truncate,
)


def _build(p: Path) -> None:
    c = sqlite3.connect(str(p))
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("CREATE TABLE snapshots (ticker TEXT, timeframe TEXT, ts_utc INTEGER, spot REAL)")
    c.execute("CREATE INDEX idx_snap ON snapshots(ticker, timeframe, ts_utc)")
    c.executemany("INSERT INTO snapshots VALUES (?,?,?,?)",
                  [("SPY", "1m", 1000 + i, 400.0 + i) for i in range(500)])
    c.commit()
    c.close()


def test_analyze_populates_empty_planner_stats():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "m.db"
        _build(p)
        c = sqlite3.connect(str(p))
        try:
            assert db_stats(c)["stat1_rows"] == 0          # ANALYZE has never run
            assert quick_check(c) == "ok"
            analyze(c)
            assert db_stats(c)["stat1_rows"] > 0            # now the planner has statistics
        finally:
            c.close()


def test_wal_checkpoint_truncate_runs():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "m.db"
        _build(p)
        c = sqlite3.connect(str(p))
        try:
            busy, log_pages, ckpt = wal_checkpoint_truncate(c)
            assert busy == 0                                # no competing writer in the test
        finally:
            c.close()


def test_run_maintenance_succeeds_and_preserves_rows():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "m.db"
        _build(p)
        assert run_maintenance(str(p)) == 0
        c = sqlite3.connect(str(p))
        try:
            assert c.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 500  # data untouched
            assert db_stats(c)["stat1_rows"] > 0
        finally:
            c.close()


def test_run_maintenance_aborts_on_missing_file():
    assert run_maintenance(str(Path(tempfile.gettempdir()) / "does_not_exist_ed.db")) == 2
