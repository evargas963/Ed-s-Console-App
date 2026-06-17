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

import ast
import sqlite3
from pathlib import Path

from db import EdDB

REPO_ROOT = Path(__file__).resolve().parent.parent


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


def test_confluence_log_create_table_removed_from_db_py_source() -> None:
    """Source lock: db.py must not contain a CREATE TABLE confluence_log block."""
    text = (REPO_ROOT / "db.py").read_text(encoding="utf-8")
    upper = text.upper()
    assert "CREATE TABLE IF NOT EXISTS CONFLUENCE_LOG" not in upper
    assert "CREATE TABLE CONFLUENCE_LOG" not in upper


def test_confluence_log_dataclass_removed_from_db_py_source() -> None:
    """Source lock: ConfluenceLog dataclass must be gone from db.py."""
    text = (REPO_ROOT / "db.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "ConfluenceLog":
            raise AssertionError(
                f"ConfluenceLog dataclass reappeared in db.py at line {node.lineno}; "
                "Pass 7 removed it — revert or open redecision"
            )


def test_no_external_references_to_confluence_writer() -> None:
    """AST sweep: zero references to ConfluenceLog / log_confluence anywhere
    in repo .py files outside db.py."""
    targets = {"ConfluenceLog", "log_confluence"}
    skip_dirs = {".git", ".venv", "venv", "__pycache__", "node_modules", ".claude",
                 "build", "dist", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
    hits: list[str] = []
    for path in REPO_ROOT.rglob("*.py"):
        rel = path.relative_to(REPO_ROOT)
        if any(part in skip_dirs for part in rel.parts):
            continue
        if rel.parts[-1] == "db.py":
            continue
        if rel.parts[-1] == "test_confluence_log_drop.py":
            continue
        try:
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text)
        except (OSError, SyntaxError):
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
        "Confluence-log symbols referenced outside db.py after Pass 7 drop:\n  "
        + "\n  ".join(hits)
    )
