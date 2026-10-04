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

import sqlite3
from pathlib import Path

from db import EdDB


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
