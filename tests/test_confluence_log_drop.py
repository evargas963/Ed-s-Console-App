"""Pass 7 — confluence_log dropped (schema + writer + dataclass + migration).

confluence_log was scaffolded but never wired (zero production callers per
AST scan + zero read consumers per audit map). Cross-instrument confluence
state is computed live in market_state per refresh and consumed via /api/state;
persisting it added no incremental value. Pass 7 chose drop over wire per
Cursor's "drop is default unless Pass 2 names a real product reader" rule.

Lock the drop so a future refactor can't accidentally re-add the table,
method, or dataclass.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from db import EdDB


def test_confluence_log_table_dropped_by_migration(tmp_path: Path) -> None:
    """Fresh EdDB must NOT have confluence_log."""
    db_path = tmp_path / "fresh.db"
    EdDB(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='confluence_log'"
        ).fetchone()
    finally:
        conn.close()
    assert row is None, "confluence_log should not exist after Pass 7 drop"


def test_confluence_log_migration_idempotent_on_existing_table(tmp_path: Path) -> None:
    """Pre-existing confluence_log gets dropped cleanly with no error."""
    db_path = tmp_path / "preexisting.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE confluence_log ("
            "conf_id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "ts_utc REAL NOT NULL, ts_et TEXT NOT NULL, "
            "primary_ticker TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO confluence_log (ts_utc, ts_et, primary_ticker) "
            "VALUES (1.0, 'ET', 'SPY')"
        )
        conn.commit()
    finally:
        conn.close()
    EdDB(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='confluence_log'"
        ).fetchone()
    finally:
        conn.close()
    assert row is None, "migration must drop confluence_log even when pre-existing"


def test_log_confluence_method_removed_from_eddb() -> None:
    """EdDB must not expose log_confluence."""
    methods = {m for m in dir(EdDB) if not m.startswith("_")}
    assert "log_confluence" not in methods, (
        "EdDB.log_confluence reappeared after Pass 7 drop — revert or open a "
        "wire-or-drop redecision row in OPEN_ITEMS"
    )
