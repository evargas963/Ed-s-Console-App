"""Pass 6 — session_log dropped (schema + writers + migration).

session_log was scaffolded but never wired (zero production callers per
AST scan + audit map). verification/daily_health.py covers richer per-ticker
session telemetry so the table delivered no incremental value. Pass 6
chose drop over wire.

These tests lock the drop so a future refactor can't accidentally
re-add the table or methods.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from db import EdDB


def test_session_log_migration_idempotent_on_existing_table(tmp_path: Path) -> None:
    """If a pre-Pass-6 install has session_log, the migration drops it without error."""
    db_path = tmp_path / "preexisting.db"
    # Manually create the table BEFORE EdDB runs migrations.
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE session_log ("
            "session_id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT)"
        )
        conn.execute("INSERT INTO session_log (ticker) VALUES ('SPY')")
        conn.commit()
    finally:
        conn.close()
    # EdDB instantiation must drop the table cleanly.
    EdDB(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='session_log'"
        ).fetchone()
    finally:
        conn.close()
    assert row is None, "migration must drop session_log even when pre-existing"
