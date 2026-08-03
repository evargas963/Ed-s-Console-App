"""repair_canonical_1m_bars_for_outcomes fail-closed outcome refresh contract."""

from __future__ import annotations

import importlib
import logging
import sqlite3
from pathlib import Path


from horizon_outcomes import forward_bar_start_utc


def _seed_minimal_db(db_path: Path, *, snapshot_id: int = 1, ts_utc: float = 1_700_000_000.0) -> float:
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE snapshots (
            snapshot_id INTEGER PRIMARY KEY,
            ticker TEXT NOT NULL,
            ts_utc REAL NOT NULL,
            timeframe TEXT NOT NULL
        );
        CREATE TABLE price_bars_1m (
            ticker TEXT NOT NULL,
            bar_start_ts_utc REAL NOT NULL,
            bar_end_ts_utc REAL NOT NULL,
            open REAL, high REAL, low REAL, close REAL, volume REAL,
            source TEXT,
            PRIMARY KEY (ticker, bar_start_ts_utc)
        );
        """
    )
    conn.execute(
        "INSERT INTO snapshots (snapshot_id, ticker, ts_utc, timeframe) VALUES (?, ?, ?, ?)",
        (snapshot_id, "SPY", ts_utc, "1m"),
    )
    prior = ts_utc - 120.0
    conn.execute(
        """
        INSERT INTO price_bars_1m
          (ticker, bar_start_ts_utc, bar_end_ts_utc, open, high, low, close, volume, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("SPY", prior, prior + 60.0, 100.0, 100.0, 100.0, 100.0, 1.0, "seed"),
    )
    conn.commit()
    conn.close()
    return forward_bar_start_utc(ts_utc, 1)


def test_eddb_import_fallback_warns(monkeypatch, caplog):
    import db
    import calibration.repair_canonical_1m_bars_for_outcomes as rep

    real_edb = db.EdDB
    monkeypatch.delattr(db, "EdDB", raising=False)
    try:
        with caplog.at_level(logging.WARNING):
            importlib.reload(rep)
        assert any("outcome refresh disabled" in r.message for r in caplog.records)
    finally:
        db.EdDB = real_edb
        importlib.reload(rep)


def test_repair_rolls_back_inserts_when_eddb_unavailable(tmp_path, monkeypatch):
    import calibration.repair_canonical_1m_bars_for_outcomes as rep

    db_path = tmp_path / "t.db"
    ts = 1_785_506_490.0  # 2026-07-31 10:01:30 ET — in-window (RC-183), so the repair genuinely inserts
    missing_start = _seed_minimal_db(db_path, ts_utc=ts)

    monkeypatch.setattr(rep, "EdDB", None)

    out = rep.repair_snapshot_horizon_bars(db_path, snapshot_id=1, dry_run=False)
    assert out.get("error") == "outcome_refresh_unavailable_eddb_import_failed"
    assert out.get("governed_outcome_refresh_status") == "skipped_eddb_unavailable"

    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT 1 FROM price_bars_1m WHERE ticker = ? AND bar_start_ts_utc = ?",
        ("SPY", missing_start),
    ).fetchone()
    conn.close()
    assert row is None
