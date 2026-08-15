"""P2 read-side gate seams: only a completed, full, certified run is readable."""
from __future__ import annotations

import sqlite3

from tools.backfill_greeks_from_chain_archive_v1 import (
    RECOMPUTE_VERSION,
    recomputed_greeks_ready,
)

_META_DDL = (
    "CREATE TABLE greeks_recomputed_v1_meta ("
    "recompute_version TEXT PRIMARY KEY, certified_parity REAL NOT NULL,"
    "certification_report TEXT NOT NULL, started_utc REAL NOT NULL,"
    "completed_utc REAL, full_run INTEGER NOT NULL, n_rows_written INTEGER NOT NULL)"
)


def _db_with_meta(completed, full_run, parity):
    con = sqlite3.connect(":memory:")
    con.execute(_META_DDL)
    con.execute(
        "INSERT INTO greeks_recomputed_v1_meta VALUES (?,?,?,?,?,?,?)",
        (RECOMPUTE_VERSION, parity, "reports/p1.json", 1.0, completed, full_run, 100),
    )
    return con


def test_gate_fails_closed_without_tables_or_meta_row():
    empty = sqlite3.connect(":memory:")
    assert recomputed_greeks_ready(empty) is False       # no table at all
    con = sqlite3.connect(":memory:")
    con.execute(_META_DDL)
    assert recomputed_greeks_ready(con) is False          # table, no row


def test_gate_refuses_partial_incomplete_and_uncertified_runs():
    assert recomputed_greeks_ready(_db_with_meta(None, 1, 1.0)) is False   # in-flight
    assert recomputed_greeks_ready(_db_with_meta(2.0, 0, 1.0)) is False    # partial run
    assert recomputed_greeks_ready(_db_with_meta(2.0, 1, 0.5)) is False    # parity below gate


def test_gate_opens_only_for_completed_full_certified_run():
    assert recomputed_greeks_ready(_db_with_meta(2.0, 1, 1.0)) is True
    assert recomputed_greeks_ready(_db_with_meta(2.0, 1, 0.99)) is True    # exact gate boundary
