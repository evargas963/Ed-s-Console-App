"""Immutable production decision records (I-31) + retrieval for blind reconstruction."""
from __future__ import annotations

import sqlite3



PRODUCTION_DECISION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS production_decision_records (
    decision_id             TEXT PRIMARY KEY,
    decision_generation_id  INTEGER,
    decision_ts_utc         REAL NOT NULL,
    ticker                  TEXT NOT NULL,
    route                   TEXT NOT NULL,
    release_id              TEXT NOT NULL,
    release_json            TEXT NOT NULL,
    git_sha                 TEXT,
    market_inputs_json      TEXT,
    risk_state_json         TEXT,
    validation_summary      TEXT,
    model_outputs_json      TEXT,
    fusion_json             TEXT,
    final_signal            TEXT,
    call_conviction         TEXT,
    overrides_json          TEXT,
    staleness_json          TEXT,
    quarantine_json         TEXT,
    reconstruction_json     TEXT NOT NULL,
    created_at_utc          REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_production_decision_ts
    ON production_decision_records (decision_ts_utc DESC);
CREATE INDEX IF NOT EXISTS idx_production_decision_ticker_ts
    ON production_decision_records (ticker, decision_ts_utc DESC);
"""


def ensure_production_decision_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(PRODUCTION_DECISION_TABLE_SQL)




























