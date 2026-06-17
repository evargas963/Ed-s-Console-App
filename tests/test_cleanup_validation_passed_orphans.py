"""cleanup_zero_normalized_snapshots reports orphan validation_passed rows (dry-run)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from tools.cleanup_zero_normalized_snapshots import _report_validation_passed_orphans


def test_report_validation_passed_orphans_counts_empty_summary(tmp_path: Path):
    db = tmp_path / "test.db"
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE snapshots (
            ticker TEXT,
            ts_utc REAL,
            validation_passed INTEGER,
            validation_summary TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO snapshots VALUES ('SPY', 1.0, 1, '')"
    )
    conn.execute(
        "INSERT INTO snapshots VALUES ('SPY', 2.0, 1, 'gate ok')"
    )
    conn.execute(
        "INSERT INTO snapshots VALUES ('SPY', 3.0, 0, '')"
    )
    conn.commit()
    n = _report_validation_passed_orphans(conn)
    conn.close()
    assert n == 1
