"""Pass 8 — news_events dropped (table + writer + dead persist path).

Operator-authorized 2026-05-26 after Cursor identified news_events as the
only remaining table-level dormancy with a live writer post-Pass 7. The
writer (EdDB.insert_news_event) had one guarded call site in
news_sentiment.py with zero downstream readers — news headlines reach the
operator UI via ms.news_context (live aggregator), so persistence delivered
no value.

These tests lock the drop so a future refactor can't accidentally re-add
the table, method, or dead persist_events plumbing.
"""

from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

from db import EdDB

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_news_events_table_dropped_by_migration(tmp_path: Path) -> None:
    db_path = tmp_path / "fresh.db"
    EdDB(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='news_events'"
        ).fetchone()
    finally:
        conn.close()
    assert row is None, "news_events should not exist after Pass 8 drop"


def test_news_events_migration_idempotent_on_existing_table(tmp_path: Path) -> None:
    db_path = tmp_path / "preexisting.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE news_events ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, "
            "source TEXT NOT NULL, ticker TEXT, headline TEXT NOT NULL, "
            "sentiment_score REAL, impact_level TEXT, url TEXT, raw_json TEXT)"
        )
        conn.execute(
            "INSERT INTO news_events (timestamp, source, headline) "
            "VALUES ('2026-01-01', 'finnhub', 'test headline')"
        )
        conn.commit()
    finally:
        conn.close()
    EdDB(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='news_events'"
        ).fetchone()
    finally:
        conn.close()
    assert row is None, "migration must drop news_events even when pre-existing"


def test_insert_news_event_method_removed_from_eddb() -> None:
    methods = {m for m in dir(EdDB) if not m.startswith("_")}
    assert "insert_news_event" not in methods, (
        "EdDB.insert_news_event reappeared after Pass 8 drop — revert or open "
        "a wire-or-drop redecision row in OPEN_ITEMS"
    )


def test_news_events_create_table_removed_from_db_py_source() -> None:
    text = (REPO_ROOT / "db.py").read_text(encoding="utf-8")
    upper = text.upper()
    assert "CREATE TABLE IF NOT EXISTS NEWS_EVENTS" not in upper
    assert "CREATE TABLE NEWS_EVENTS" not in upper


def test_persist_events_parameter_removed_from_news_sentiment() -> None:
    """The dead persist_events plumbing in news_sentiment.refresh_and_context /
    refresh_and_context_for_ui must be gone so callers can't reintroduce
    a phantom persist toggle."""
    text = (REPO_ROOT / "news_sentiment.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in ("refresh_and_context", "refresh_and_context_for_ui"):
                arg_names = {a.arg for a in node.args.args}
                kwarg_names = {a.arg for a in node.args.kwonlyargs}
                all_args = arg_names | kwarg_names
                assert "persist_events" not in all_args, (
                    f"news_sentiment.{node.name} still accepts persist_events; "
                    "Pass 8 removed the param + dead persist block — clean the signature"
                )


def test_no_persist_events_kwarg_in_any_refresh_and_context_call() -> None:
    """AST-scan EVERY call to refresh_and_context / refresh_and_context_for_ui
    across the repo — including the news_sentiment.py __main__ probe block
    that the signature-only test missed in the original Pass 8 commit.

    A stale `persist_events=False` at a call site won't fail collection but
    will TypeError at runtime when invoked (broken `python news_sentiment.py
    SPY` CLI). Catch it statically.
    """
    skip_dirs = {".git", ".venv", "venv", "__pycache__", "node_modules", ".claude",
                 "build", "dist", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
    targets = {"refresh_and_context", "refresh_and_context_for_ui"}
    hits: list[str] = []
    for path in REPO_ROOT.rglob("*.py"):
        rel = path.relative_to(REPO_ROOT)
        if any(part in skip_dirs for part in rel.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text)
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            short = None
            if isinstance(fn, ast.Name):
                short = fn.id
            elif isinstance(fn, ast.Attribute):
                short = fn.attr
            if short not in targets:
                continue
            for kw in node.keywords:
                if kw.arg == "persist_events":
                    hits.append(f"{rel}:{node.lineno} {short}(... persist_events=...)")
    assert hits == [], (
        "persist_events kwarg still passed to refresh_and_context* — "
        "would raise TypeError at runtime:\n  " + "\n  ".join(hits)
    )


def test_no_external_references_to_news_writer() -> None:
    targets = {"insert_news_event"}
    skip_dirs = {".git", ".venv", "venv", "__pycache__", "node_modules", ".claude",
                 "build", "dist", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
    hits: list[str] = []
    for path in REPO_ROOT.rglob("*.py"):
        rel = path.relative_to(REPO_ROOT)
        if any(part in skip_dirs for part in rel.parts):
            continue
        if rel.parts[-1] == "db.py":
            continue
        if rel.parts[-1] == "test_news_events_drop.py":
            continue
        try:
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text)
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in targets:
                hits.append(f"{rel}:{node.lineno} Attr(.{node.attr})")
            elif isinstance(node, ast.Name) and node.id in targets:
                hits.append(f"{rel}:{node.lineno} Name({node.id})")
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in targets:
                        hits.append(f"{rel}:{node.lineno} ImportFrom({alias.name})")
    assert hits == [], (
        "insert_news_event referenced outside db.py after Pass 8 drop:\n  "
        + "\n  ".join(hits)
    )
