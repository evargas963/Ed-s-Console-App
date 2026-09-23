"""get_similar_setups' tier-4 probe (zone only, vwap_side dropped) must be index-served —
not a full ticker+timeframe scan.

RC-REHAB-1 (2026-09-22, live-RTH trace): idx_snap_similarity_zone_vwap
(ticker, timeframe, zone, vwap_side, ts_utc) exists and correctly serves tiers 1-3
(zone AND vwap_side both fixed) — but tier 4 drops vwap_side, and using just this
index's (ticker, timeframe, zone) prefix would still require SQLite to sort the matches
by ts_utc separately (this index's own trailing ts_utc ordering is only valid within one
fixed vwap_side). Confirmed live: SQLite's planner instead picks idx_snap_ticker_tf_ts
(ticker, timeframe, ts_utc) for tier 4 — sort-free, but with no index support for zone at
all, so it scans every ticker+timeframe row (in ts_utc order) filtering zone row-by-row
until it finds n_similar matches or exhausts the partition. MEASURED on SPY's real 1m
data (76,957 rows / 39,812 with outcome_1c IS NOT NULL): 1,227ms for a single tier-4
probe that matched zero rows — reached on nearly every real call, since tiers 1-3's much
narrower zone+vwap_side+distance match is rare.

idx_snap_similarity_zone_only (ticker, timeframe, zone, ts_utc) closes this gap: it
satisfies both the WHERE filter and the ORDER BY from its own trailing ts_utc column, so
SQLite can use it directly with no scan and no sort.

A THIRD, related defect lives in get_avg_move (same hot path, called right after
get_similar_setups by compute_prediction_core): it filters
WHERE outcome_1c_pts IS NOT NULL -- a DIFFERENT column from idx_snap_similarity_zone_vwap's
own partial-index predicate (outcome_1c IS NOT NULL). SQLite cannot use that index for a
query it cannot prove is a subset of, even though the two columns are in practice always
set together -- confirmed live: the same idx_snap_ticker_tf_ts scan-until-exhausted
fallback. MEASURED: 2,332ms for a single call matching zero rows; 107ms with
idx_snap_avg_move_zone_vwap (ticker, timeframe, zone, vwap_side, ts_utc)
WHERE outcome_1c_pts IS NOT NULL.

Asserting the PLAN, not the wall clock (same discipline as test_spot_authority_v1.py's
own copy of this reasoning): a timing assertion would be flaky and would pass on a small
fixture database. A missing index in the plan is the defect itself.
"""
from __future__ import annotations

import sqlite3


def _snapshots_fixture(*, with_zone_only_index: bool, with_avg_move_index: bool = False) -> sqlite3.Connection:
    """Minimal table + the real production indexes, so the plan is the production plan."""
    con = sqlite3.connect(":memory:")
    con.execute(
        "CREATE TABLE snapshots (snapshot_id INTEGER PRIMARY KEY, ticker TEXT, "
        "timeframe TEXT, ts_utc REAL, zone TEXT, vwap_side TEXT, outcome_1c TEXT, "
        "outcome_1c_pts REAL)"
    )
    con.execute(
        "CREATE INDEX idx_snap_ticker_tf_ts ON snapshots(ticker, timeframe, ts_utc)"
    )
    con.execute(
        "CREATE INDEX idx_snap_similarity_zone_vwap "
        "ON snapshots(ticker, timeframe, zone, vwap_side, ts_utc) WHERE outcome_1c IS NOT NULL"
    )
    if with_zone_only_index:
        con.execute(
            "CREATE INDEX idx_snap_similarity_zone_only "
            "ON snapshots(ticker, timeframe, zone, ts_utc) WHERE outcome_1c IS NOT NULL"
        )
    if with_avg_move_index:
        con.execute(
            "CREATE INDEX idx_snap_avg_move_zone_vwap "
            "ON snapshots(ticker, timeframe, zone, vwap_side, ts_utc) "
            "WHERE outcome_1c_pts IS NOT NULL"
        )
    return con


_TIER4_SQL = (
    "SELECT *, 4 as match_tier FROM snapshots "
    "WHERE ticker = ? AND timeframe = ? AND zone = ? AND outcome_1c IS NOT NULL "
    "ORDER BY ts_utc DESC LIMIT ?"
)
_TIER4_PARAMS = ("SPY", "1m", "pin_neutral", 500)

_AVG_MOVE_SQL = (
    "SELECT outcome_1c_pts FROM snapshots "
    "WHERE ticker = ? AND timeframe = ? AND zone = ? AND vwap_side = ? "
    "AND outcome_1c_pts IS NOT NULL ORDER BY ts_utc DESC"
)
_AVG_MOVE_PARAMS = ("SPY", "1m", "pin_neutral", "above")


def _plan(con: sqlite3.Connection, sql: str, params: tuple) -> str:
    return " | ".join(str(r[3]) for r in con.execute("EXPLAIN QUERY PLAN " + sql, params))


def test_tier4_without_the_new_index_reproduces_the_scan_defect():
    """Proves the defect is real and that this test can see it -- without
    idx_snap_similarity_zone_only, SQLite falls back to idx_snap_ticker_tf_ts (a scan with
    no zone filter support), never the zone-aware index at all."""
    con = _snapshots_fixture(with_zone_only_index=False)
    try:
        plan = _plan(con, _TIER4_SQL, _TIER4_PARAMS)
        assert "idx_snap_ticker_tf_ts" in plan, plan
        assert "idx_snap_similarity_zone" not in plan, plan
    finally:
        con.close()


def test_tier4_with_the_new_index_is_fully_index_served():
    """The shipped fix: tier 4's query must be served by idx_snap_similarity_zone_only,
    with no separate scan of idx_snap_ticker_tf_ts and no temp b-tree sort."""
    con = _snapshots_fixture(with_zone_only_index=True)
    try:
        plan = _plan(con, _TIER4_SQL, _TIER4_PARAMS)
        assert "idx_snap_similarity_zone_only" in plan, plan
        assert "TEMP B-TREE" not in plan.upper(), plan
        assert "idx_snap_ticker_tf_ts" not in plan, plan
    finally:
        con.close()


def test_tiers_1_through_3_are_unaffected_by_the_new_index():
    """The new index must not change how tiers 1-3 (zone AND vwap_side both fixed) are
    served -- they already use idx_snap_similarity_zone_vwap correctly; this is purely
    additive for tier 4's own access pattern."""
    con = _snapshots_fixture(with_zone_only_index=True)
    try:
        sql = (
            "SELECT *, 3 as match_tier FROM snapshots "
            "WHERE ticker = ? AND timeframe = ? AND zone = ? AND vwap_side = ? "
            "AND outcome_1c IS NOT NULL ORDER BY ts_utc DESC LIMIT ?"
        )
        plan = _plan(con, sql, ("SPY", "1m", "pin_neutral", "above", 500))
        assert "idx_snap_similarity_zone_vwap" in plan, plan
        assert "TEMP B-TREE" not in plan.upper(), plan
    finally:
        con.close()


def test_avg_move_without_the_new_index_reproduces_the_scan_defect():
    """Proves the get_avg_move defect is real: idx_snap_similarity_zone_vwap's own
    partial-index predicate is outcome_1c IS NOT NULL, a different column from this
    query's outcome_1c_pts IS NOT NULL filter, so SQLite cannot use it -- falls back to
    idx_snap_ticker_tf_ts and a full scan, same as the tier-4 defect above."""
    con = _snapshots_fixture(with_zone_only_index=True, with_avg_move_index=False)
    try:
        plan = _plan(con, _AVG_MOVE_SQL, _AVG_MOVE_PARAMS)
        assert "idx_snap_ticker_tf_ts" in plan, plan
        assert "idx_snap_avg_move" not in plan, plan
    finally:
        con.close()


def test_avg_move_with_the_new_index_is_fully_index_served():
    """The shipped fix: get_avg_move's query must be served by
    idx_snap_avg_move_zone_vwap, with no separate scan and no temp b-tree sort."""
    con = _snapshots_fixture(with_zone_only_index=True, with_avg_move_index=True)
    try:
        plan = _plan(con, _AVG_MOVE_SQL, _AVG_MOVE_PARAMS)
        assert "idx_snap_avg_move_zone_vwap" in plan, plan
        assert "TEMP B-TREE" not in plan.upper(), plan
        assert "idx_snap_ticker_tf_ts" not in plan, plan
    finally:
        con.close()


def test_eddb_schema_init_creates_the_new_index(tmp_path):
    """A fresh EdDB instance creates idx_snap_similarity_zone_only and
    idx_snap_avg_move_zone_vwap automatically, the same way it already creates
    idx_snap_similarity_zone_vwap -- all three guarded, all three
    CREATE INDEX IF NOT EXISTS, added at the same point in schema init."""
    import db as db_module

    d = db_module.EdDB(tmp_path / "fresh.db", allow_noncanonical=True)
    con = d._connect()
    try:
        names = {
            r["name"]
            for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='snapshots'"
            )
        }
        assert "idx_snap_similarity_zone_only" in names
        assert "idx_snap_similarity_zone_vwap" in names
        assert "idx_snap_avg_move_zone_vwap" in names
    finally:
        con.close()
