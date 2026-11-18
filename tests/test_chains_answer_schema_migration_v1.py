"""#1065 added chains_answer to CREATE/INSERT only; migrate existing #1064-shaped tables."""

from __future__ import annotations

import sqlite3

from calibration.complete_chain_capture import (
    CAPTURE_BASIS,
    ensure_schema,
    persist_complete_chain_capture,
)


def test_ensure_schema_adds_chains_answer_to_a_1064_shaped_table(tmp_path):
    """CREATE IF NOT EXISTS leaves an old table alone; INSERT names chains_answer.

    A production ed.db whose capture table was created at #1064 then failed every history write
    (OperationalError) while the live chain still published — silent banked-capture loss.
    """
    path = tmp_path / "ed.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE complete_chain_captures (
            ticker TEXT NOT NULL,
            expiry TEXT NOT NULL,
            ts_utc REAL NOT NULL,
            spot REAL,
            completeness_basis TEXT NOT NULL,
            chain_json TEXT NOT NULL,
            chain_spot REAL,
            chain_spot_ts REAL,
            PRIMARY KEY (ticker, expiry, ts_utc)
        );
        """
    )
    ensure_schema(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(complete_chain_captures)")}
    assert "chains_answer" in cols
    out = persist_complete_chain_capture(
        conn,
        ticker="SPY",
        expiry="2026-11-20",
        contracts=[{"strike": 500}],
        spot=500.0,
        completeness_basis=CAPTURE_BASIS,
        ts_utc=1.0,
        chains_answer='{"ok": true}',
    )
    assert out["status"] == "written"
    conn.close()
