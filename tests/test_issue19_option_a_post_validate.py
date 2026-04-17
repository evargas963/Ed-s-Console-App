"""Smoke tests for tools/issue19_option_a_post_validate.py (read-only helpers)."""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_post_validate_module():
    path = ROOT / "tools" / "issue19_option_a_post_validate.py"
    spec = importlib.util.spec_from_file_location("issue19_option_a_post_validate", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_discover_distance_tables_finds_snapshots_columns(tmp_path):
    mod = _load_post_validate_module()
    db = tmp_path / "t.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        """
        CREATE TABLE snapshots (
            snapshot_id INTEGER PRIMARY KEY,
            nearest_above_dist REAL,
            nearest_below_dist REAL
        )
        """
    )
    conn.commit()
    conn.close()
    conn = mod._connect(db)
    try:
        assert mod.discover_distance_tables(conn) == ["snapshots"]
    finally:
        conn.close()


def test_issue19_tier_counts_mirror_sql(tmp_path):
    mod = _load_post_validate_module()
    db = tmp_path / "t.db"
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE snapshots (
            snapshot_id INTEGER PRIMARY KEY,
            ticker TEXT,
            timeframe TEXT,
            zone TEXT,
            vwap_side TEXT,
            nearest_above_dist REAL,
            nearest_below_dist REAL,
            outcome_1c TEXT,
            ts_utc REAL
        );
        INSERT INTO snapshots VALUES
          (1, 'ZZZ', '1m', 'pin_bull', 'above', 0.5, 0.5, 'up', 1720000000.0),
          (2, 'ZZZ', '1m', 'pin_bull', 'above', 0.6, 10.0, 'up', 1720000060.0),
          (3, 'ZZZ', '1m', 'pin_bull', 'above', 0.5, 0.7, 'down', 1720000120.0);
        """
    )
    conn.commit()
    anchors = [
        {
            "anchor_id": "test",
            "ticker": "ZZZ",
            "timeframe": "1m",
            "zone": "pin_bull",
            "vwap_side": "above",
            "nearest_above_dist": 0.55,
            "nearest_below_dist": 0.55,
        }
    ]
    n1 = mod._count_tier_sql(
        conn,
        tier=1,
        ticker="ZZZ",
        timeframe="1m",
        zone="pin_bull",
        vwap_side="above",
        nearest_above_dist=0.55,
        nearest_below_dist=0.55,
    )
    n2 = mod._count_tier_sql(
        conn,
        tier=2,
        ticker="ZZZ",
        timeframe="1m",
        zone="pin_bull",
        vwap_side="above",
        nearest_above_dist=0.55,
        nearest_below_dist=0.55,
    )
    n1_recent = mod._count_tier_sql(
        conn,
        tier=1,
        ticker="ZZZ",
        timeframe="1m",
        zone="pin_bull",
        vwap_side="above",
        nearest_above_dist=0.55,
        nearest_below_dist=0.55,
        min_ts_utc=1_720_000_100.0,
    )
    assert n1 == 2
    assert n2 == 3
    assert n1_recent == 1
    conn.close()
