"""Smoke tests for pin_neutral 1m/5m divergence audit helper SQL."""
from __future__ import annotations

import sqlite3

from db import EdDB, configure_sqlite_connection
from horizon_outcomes import HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1
from tools.pin_neutral_1m_5m_divergence_audit_v1 import (
    bar_anchor_scope_sql,
    by_ticker_breakdown,
    inventory_timeframe,
)


def test_bar_anchor_scope_supports_table_alias():
    s = bar_anchor_scope_sql("s.outcome_filled=0", alias="s")
    assert "s.zone" in s
    assert "s.timeframe" in s
    assert "s.outcome_filled=0" in s


def test_no_fallback_lock_repair_2026_09_17_no_coalesce_left_in_scope_sql():
    """
    No-fallback lock repair (FB-00091-shape reuse): bar_anchor_scope_sql used to
    SQL-default a NULL horizon_outcome_schema_version to a caller-supplied value --
    same genuine-nullable root cause already repaired across this branch's other
    snapshots-scoping queries. It now compares the column directly.
    """
    s = bar_anchor_scope_sql()
    assert "COALESCE" not in s
    assert "horizon_outcome_schema_version = ?" in s


def test_inventory_timeframe_and_by_ticker_breakdown_run_against_real_db(tmp_path):
    """
    Regression proof for the parameter-count fix that accompanied simplifying the
    schema-version default-on-NULL comparison to a bare equality: scope tuples shrank
    from 3 elements to 2, and the JSON-registered unfilled_has_anchor/by_ticker_agg SQL
    templates (snapshot_sql/registry_full_c.json) had to be updated in lockstep.
    A parameter-count mismatch would raise sqlite3.ProgrammingError here.
    """
    db_path = tmp_path / "divergence.db"
    _ = EdDB(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    conn.execute(
        """
        INSERT INTO snapshots (
            ticker, timeframe, ts_utc, ts_et, spot, zone,
            horizon_outcome_schema_version, outcome_filled, outcome_1c
        )
        VALUES ('SPY', '1m', 1900000100.0, 'et', 100.0, 'pin_neutral', ?, 1, 'up')
        """,
        (HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,),
    )
    conn.commit()

    inv = inventory_timeframe(conn, "1m")
    assert inv["total_bar_anchor_scope"] == 1
    assert inv["outcome_filled_1"] == 1
    assert inv["outcome_filled_0"] == 0
    assert inv["outcome_1c_nonnull"] == 1

    breakdown = by_ticker_breakdown(conn, "1m")
    conn.close()
    assert breakdown == [{"ticker": "SPY", "n_total": 1, "n_filled": 1, "n_o1": 1}]
