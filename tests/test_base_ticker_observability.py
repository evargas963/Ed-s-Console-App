"""Tests for base/guest ticker tiers and RTH observability checker."""
from __future__ import annotations

from pathlib import Path


def test_insert_snapshot_persists_logger_source(tmp_path: Path):
    from db import EdDB, SnapshotRow
    from timeframe_config import CANONICAL_TIMEFRAME

    db = EdDB(tmp_path / "src.db")
    row = SnapshotRow(
        ticker="IWM",
        timeframe=CANONICAL_TIMEFRAME,
        ts_utc=1_781_800_000.0,
        ts_et="2026-06-18 10:00:00 ET",
        et_hour=10,
        et_minute=0,
        market_session="rth",
        spot=200.0,
        logger_source="base_money_path",
    )
    db.insert_snapshot(row)
    with db._connect() as conn:
        src = conn.execute(
            "SELECT logger_source FROM snapshots WHERE ticker='IWM'"
        ).fetchone()[0]
    assert src == "base_money_path"
