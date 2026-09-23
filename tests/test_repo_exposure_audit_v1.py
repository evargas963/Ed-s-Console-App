"""No-fallback lock repair (2026-09-17, FB-01110): tools/repo_exposure_audit.py's
level_crosses duplication count used a SQL-level default-on-NULL around its SUM aggregate.
Unlike every other aggregate-over-possibly-empty-set site this repair touched, this one had NO
pre-existing Python-side `or 0` guard -- the SUM over zero duplicate-groups (the common,
healthy-database case with no repeated level crosses) is a legal SQL NULL, and removing the
SQL-level default without adding a Python-side one would have made the f-string/division
right below it crash on exactly the common case. This test proves the fix handles both the
zero-duplicates and some-duplicates cases without a NULL/TypeError crash.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.repo_exposure_audit as rea  # noqa: E402


def _make_db(tmp_path: Path, rows: list[tuple]) -> Path:
    db = tmp_path / "audit.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE level_crosses (ticker TEXT, ts_utc REAL, level_value REAL)"
    )
    conn.executemany(
        "INSERT INTO level_crosses (ticker, ts_utc, level_value) VALUES (?,?,?)", rows
    )
    conn.commit()
    conn.close()
    return db


def test_section_db_no_duplicates_does_not_crash_on_null_sum(tmp_path, monkeypatch):
    db = _make_db(tmp_path, [("SPY", 1.0, 100.0), ("QQQ", 2.0, 200.0)])
    monkeypatch.setattr(rea, "canonical_console_db_path", lambda: db)
    out = rea.section_db()
    assert "level_crosses_duplication" in out
    assert out["level_crosses_duplication"].startswith("0 of 2 rows")


def test_section_db_with_duplicates_counts_correctly(tmp_path, monkeypatch):
    db = _make_db(tmp_path, [
        ("SPY", 1.0, 100.0), ("SPY", 1.0, 100.0), ("SPY", 1.0, 100.0),  # 3 rows, 1 group, 2 extra
        ("QQQ", 2.0, 200.0),
    ])
    monkeypatch.setattr(rea, "canonical_console_db_path", lambda: db)
    out = rea.section_db()
    assert out["level_crosses_duplication"].startswith("2 of 4 rows")


def test_section_db_empty_table_does_not_crash(tmp_path, monkeypatch):
    db = _make_db(tmp_path, [])
    monkeypatch.setattr(rea, "canonical_console_db_path", lambda: db)
    out = rea.section_db()
    assert out["level_crosses_duplication"].startswith("0 of 0 rows")
