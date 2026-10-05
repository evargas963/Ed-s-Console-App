"""DATA_FLOW decision 6: no table is dropped by code. Starting the console's database (EdDB) leaves
every table it finds, with its rows.

The console dropped session_log, confluence_log and news_events (with news_events' two indexes)
on every start. Each table is built here with the schema it had when the console wrote it (the
first commit, 4b3dce45), and given a row. news_events holds a NEWS_HEADLINE item as Schwab sent
it (tests/fixtures/real_schwab_news_headline_spx_2026_10_05.json). STAND-INS: the session_log and
confluence_log rows (the console's own derived values; no captured row of either exists, both
tables are absent in production) are built from that item's symbol and time.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from db import EdDB

_NEWS = json.loads((Path(__file__).parent / "fixtures" / "real_schwab_news_headline_spx_2026_10_05.json")
                   .read_text(encoding="utf-8"))

_OLD_SCHEMA = """
CREATE TABLE session_log (
    session_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker          TEXT,
    started_at      TEXT DEFAULT (datetime('now')),
    ended_at        TEXT,
    snapshots_taken INTEGER DEFAULT 0,
    crosses_logged  INTEGER DEFAULT 0
);
CREATE TABLE confluence_log (
    conf_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc              REAL    NOT NULL,
    ts_et               TEXT    NOT NULL,
    primary_ticker      TEXT    NOT NULL,
    confluence_signal   TEXT,
    confluence_score    REAL,
    instruments_agree   INTEGER,
    instruments_total   INTEGER,
    spy_state           TEXT,
    qqq_state           TEXT,
    iwm_state           TEXT,
    vix_state           TEXT,
    spy_constituents    TEXT,
    iwm_sectors         TEXT,
    spy_push            REAL,
    iwm_push            REAL,
    qqq_vs_spy_delta    REAL,
    created_at          TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_conf_ts ON confluence_log(ts_utc);
CREATE TABLE news_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,
    source          TEXT    NOT NULL,
    ticker          TEXT,
    headline        TEXT    NOT NULL,
    sentiment_score REAL,
    impact_level    TEXT,
    url             TEXT,
    raw_json        TEXT
);
CREATE INDEX idx_news_ticker_ts ON news_events(ticker, timestamp);
CREATE INDEX idx_news_impact_ts ON news_events(impact_level, timestamp);
"""


def _contents(db: Path) -> dict:
    with sqlite3.connect(db) as conn:
        objects = sorted(r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE name IN ('session_log', 'confluence_log', "
            "'news_events', 'idx_conf_ts', 'idx_news_ticker_ts', 'idx_news_impact_ts')"))
        return {"objects": objects,
                "rows": {t: conn.execute(f"SELECT * FROM {t}").fetchall()
                         for t in ("session_log", "confluence_log", "news_events") if t in objects}}


def test_starting_the_database_keeps_every_table_it_finds_with_its_rows(tmp_path):
    db = tmp_path / "ed_console.db"
    item = _NEWS["content"]
    with sqlite3.connect(db) as conn:
        conn.executescript(_OLD_SCHEMA)
        conn.execute("INSERT INTO session_log (ticker, started_at) VALUES (?, ?)",
                     (_NEWS["symbol"], str(_NEWS["ts_recv"])))
        conn.execute("INSERT INTO confluence_log (ts_utc, ts_et, primary_ticker) VALUES (?, ?, ?)",
                     (_NEWS["ts_recv"], str(_NEWS["schwab_ts"]), _NEWS["symbol"]))
        conn.execute("INSERT INTO news_events (timestamp, source, ticker, headline, raw_json) "
                     "VALUES (?, ?, ?, ?, ?)",
                     (str(item["1"]), _NEWS["src"], item["key"], item["4"], json.dumps(item)))
    before = _contents(db)
    assert len(before["objects"]) == 6 and all(len(r) == 1 for r in before["rows"].values())

    EdDB(db, allow_noncanonical=True)

    assert _contents(db) == before, "starting the database dropped a table or its rows"
