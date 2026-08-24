"""Pass 6 — session_log dropped (schema + writers + migration).

session_log was scaffolded but never wired (zero production callers per
AST scan + audit map). verification/daily_health.py covers richer per-ticker
session telemetry so the table delivered no incremental value. Pass 6
chose drop over wire.

These tests lock the drop so a future refactor can't accidentally
re-add the table or methods.
"""

from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

from db import EdDB

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_session_log_table_dropped_by_migration(tmp_path: Path) -> None:
    """New EdDB on a fresh DB must NOT have session_log."""
    db_path = tmp_path / "fresh.db"
    EdDB(db_path)  # triggers _init_schema + migrations
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='session_log'"
        ).fetchone()
    finally:
        conn.close()
    assert row is None, "session_log table should not exist after Pass 6 drop"


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


def test_session_writer_methods_removed_from_eddb() -> None:
    """EdDB must not expose start_session / end_session / update_session_counts."""
    edb_methods = {m for m in dir(EdDB) if not m.startswith("_")}
    for removed in ("start_session", "end_session", "update_session_counts"):
        assert removed not in edb_methods, (
            f"EdDB.{removed} reappeared after Pass 6 drop — revert or open a "
            "wire-or-drop redecision row in OPEN_ITEMS"
        )


def test_session_log_create_table_removed_from_db_py_source() -> None:
    """Source-level lock: db.py must not contain a CREATE TABLE session_log
    block. Catches the regression where someone re-adds the table via a copy
    from git history without realising it was intentionally dropped."""
    text = (REPO_ROOT / "db.py").read_text(encoding="utf-8")
    upper = text.upper()
    assert "CREATE TABLE IF NOT EXISTS SESSION_LOG" not in upper
    assert "CREATE TABLE SESSION_LOG" not in upper


def test_no_external_references_to_session_writers(repo_index) -> None:
    """AST sweep: zero references to SessionLog / start_session / end_session /
    update_session_counts anywhere in repo .py files outside db.py."""
    targets = {"SessionLog", "start_session", "end_session", "update_session_counts"}
    hits: list[str] = []
    for rel, text, tree in repo_index.items():
        if rel.parts[-1] == "db.py":
            continue
        if rel.parts[-1] == "test_session_log_drop.py":
            continue
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in targets:
                hits.append(f"{rel}:{node.lineno} Name({node.id})")
            elif isinstance(node, ast.Attribute) and node.attr in targets:
                hits.append(f"{rel}:{node.lineno} Attr(.{node.attr})")
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in targets:
                        hits.append(f"{rel}:{node.lineno} ImportFrom({alias.name})")
    assert hits == [], (
        "Session-log symbols referenced outside db.py after Pass 6 drop:\n  "
        + "\n  ".join(hits)
    )
