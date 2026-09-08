"""Phase 4 distance Option A backfill — isolated DB transactions and invariants."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db import EdDB, get_snapshot_sql
from distance_option_a_backfill_v1 import (
    FLAG_COMPLETE,
    FLAG_KEY,
    discover_distance_tables,
    distance_column_stats,
    run_distance_option_a_backfill_v1,
)
from timeframe_config import CANONICAL_TIMEFRAME


def _insert_snapshot(
    conn: sqlite3.Connection,
    *,
    ticker: str,
    ts: float,
    nad: float,
    nbd: float,
) -> None:
    conn.execute(
        """
        INSERT INTO snapshots (
          ticker, timeframe, ts_utc, ts_et, spot, zone, vwap_side,
          nearest_above_dist, nearest_below_dist,
          outcome_1c, horizon_outcome_schema_version
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            ticker,
            CANONICAL_TIMEFRAME,
            ts,
            "t",
            450.0,
            "pin_neutral",
            "above",
            nad,
            nbd,
            "up",
            3,
        ),
    )


@pytest.fixture
def db_mixed(tmp_path):
    dbp = tmp_path / "opta.db"
    db = EdDB(dbp)
    with db._connect() as conn:
        _insert_snapshot(conn, ticker="SPY", ts=1000.0, nad=1.5, nbd=-2.25)
        _insert_snapshot(conn, ticker="SPY", ts=1060.0, nad=-0.1, nbd=-0.5)
        conn.commit()
    return dbp


def test_discover_tables_includes_snapshots(db_mixed):
    conn = sqlite3.connect(str(db_mixed))
    t = discover_distance_tables(conn)
    conn.close()
    assert "snapshots" in t


def test_backfill_flips_negative_only_and_sets_flag(db_mixed):
    out = run_distance_option_a_backfill_v1(
        db_mixed,
        skip_backup=True,
        force=True,
    )
    assert out["status"] == "backfill_complete"
    assert out["flag_after"] == FLAG_COMPLETE

    db = EdDB(db_mixed)
    assert db.get_schema_flag(FLAG_KEY) == FLAG_COMPLETE

    conn = sqlite3.connect(str(db_mixed))
    conn.row_factory = sqlite3.Row
    st = distance_column_stats(conn, "snapshots")
    assert st["nearest_below_dist_lt_0"] == 0
    assert st["nearest_above_dist_lt_0"] == 0
    r0 = conn.execute(
        get_snapshot_sql("tests/test_distance_option_a_backfill_v1.py:93"),
        (CANONICAL_TIMEFRAME,),
    ).fetchone()
    assert float(r0["nearest_above_dist"]) == 1.5
    assert float(r0["nearest_below_dist"]) == 2.25
    r1 = conn.execute(
        get_snapshot_sql("tests/test_distance_option_a_backfill_v1.py:99"),
        (CANONICAL_TIMEFRAME,),
    ).fetchone()
    assert float(r1["nearest_above_dist"]) == pytest.approx(0.1)
    assert float(r1["nearest_below_dist"]) == pytest.approx(0.5)
    conn.close()


def test_dry_run_does_not_mutate(tmp_path):
    dbp = tmp_path / "dry.db"
    db = EdDB(dbp)
    with db._connect() as conn:
        _insert_snapshot(conn, ticker="X", ts=1.0, nad=1.0, nbd=-3.0)
        conn.commit()
    out = run_distance_option_a_backfill_v1(dbp, dry_run=True)
    assert out["dry_run"] is True
    conn = sqlite3.connect(str(dbp))
    n = conn.execute(
        get_snapshot_sql("tests/test_distance_option_a_backfill_v1.py:117"),
        (CANONICAL_TIMEFRAME,),
    ).fetchone()[0]
    conn.close()
    assert int(n) == 1


def test_refuses_second_run_without_force(tmp_path):
    dbp = tmp_path / "twice.db"
    db = EdDB(dbp)
    with db._connect() as conn:
        _insert_snapshot(conn, ticker="Y", ts=1.0, nad=1.0, nbd=-1.0)
        conn.commit()
    run_distance_option_a_backfill_v1(dbp, skip_backup=True, force=True)
    with pytest.raises(RuntimeError, match="NO-GO"):
        run_distance_option_a_backfill_v1(dbp, skip_backup=True, force=False)
