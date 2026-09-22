"""db.py SQL string-template builder cluster (RC-REHAB-1, db.py decomposition follow-up).

Pure SQL-fragment builders (no `self`, no connection, no coupling to `EdDB`) consumed by
several OTHER production modules -- db_health_audit.py, ml_data_common.py,
similarity_feature_search.py, adaptive_similarity_engine.py, math_probabilities.py,
verification/db_coverage.py, normalized_training_sync.py, tools/issue19_option_a_post_validate.py
-- verified via a repo-wide, word-boundary-exact search before moving (an earlier same-file-only
check wrongly suggested most of these were dead code; they are not, they are just never called
FROM db.py itself).

SNAPSHOT SQL REGISTRY (strict BYPASS closure v3): static SQL strings for callers live under
snapshot_sql/*.json (merged by get_snapshot_sql). Only this module may define loaders/builders
that embed FROM + snapshots in Python source -- this constraint is design intent documented in
this comment, not currently machine-enforced (tools/build_snapshot_sql_registry.py, the one-off
script that audits it, excludes only "db.py" from its own scan; it has been updated here to also
exclude this file, its new home, so a future manual run stays correct).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

_ISSUE19_CTX_GROUP_COLS = frozenset(
    {"session_bucket", "regime_primary", "vix_bucket", "market_session"}
)


def sql_flow_audit_count_where(base_where: str) -> str:
    return f"SELECT COUNT(*) FROM snapshots {base_where}"


def sql_flow_audit_rows_where(base_where: str) -> str:
    return (
        "SELECT snapshot_id, spot, flow_imbalance, option_chain_json\n        FROM snapshots\n        "
        + base_where.strip()
        + "\n    "
    )


def sql_select_snapshots_columns(cols_sql: str) -> str:
    return f"SELECT {cols_sql} FROM snapshots"


def sql_select_snapshots_ticker_tf_order(sel: str, *, order_suffix: str) -> str:
    return f"SELECT {sel} FROM snapshots WHERE ticker = ? AND timeframe = ? {order_suffix}"


def sql_overlay_count_zpred(zpred: str) -> str:
    return (
        "SELECT COUNT(*) FROM snapshots WHERE ticker = ? AND timeframe = ? AND ("
        + zpred
        + ") AND outcome_1c IS NOT NULL"
    )


def sql_overlay_count_zpred_vwap(zpred: str) -> str:
    return (
        "SELECT COUNT(*) FROM snapshots\n            WHERE ticker = ? AND timeframe = ? AND ("
        + zpred
        + ") AND vwap_side = ? AND outcome_1c IS NOT NULL\n            "
    )


def sql_overlay_count_zpred_vwap_bucket(zpred: str, bsql: str) -> str:
    return (
        "SELECT COUNT(*) FROM snapshots\n            WHERE ticker = ? AND timeframe = ? AND ("
        + zpred
        + ") AND vwap_side = ? AND outcome_1c IS NOT NULL\n              AND ("
        + bsql
        + ")\n            "
    )


def sql_overlay_select_star_where(where_clause: str) -> str:
    return (
        "SELECT * FROM snapshots\n                WHERE "
        + where_clause
        + "\n                ORDER BY ts_utc DESC, snapshot_id DESC\n                LIMIT 1\n            "
    )


def sql_issue19_tier1_candidate_rows(asof_sql: str) -> str:
    return (
        "SELECT * FROM snapshots\n            WHERE ticker = ? AND timeframe = ? AND zone = ? AND vwap_side = ?\n"
        "              AND outcome_1c IS NOT NULL\n"
        "              AND (\n"
        "                (nearest_above_dist IS NULL AND ? IS NULL)\n"
        "                OR (nearest_above_dist BETWEEN ? AND ?)\n"
        "              )\n"
        "              AND (\n"
        "                (nearest_below_dist IS NULL AND ? IS NULL)\n"
        "                OR (nearest_below_dist BETWEEN ? AND ?)\n"
        "              )\n            "
        + asof_sql
        + "\n            ORDER BY ts_utc DESC, snapshot_id DESC\n            LIMIT ?\n            "
    )


def sql_adaptive_broad_similarity_pool(asof_sql: str) -> str:
    return (
        "SELECT * FROM snapshots\n            WHERE ticker = ? AND timeframe = ?\n"
        "              AND outcome_1c IS NOT NULL\n            "
        + asof_sql
        + "\n            ORDER BY ts_utc DESC, snapshot_id DESC\n            LIMIT ?\n            "
    )


def sql_db_coverage_snap_tot() -> str:
    return "SELECT COUNT(*) FROM snapshots WHERE ticker=? AND timeframe=?"


def sql_db_coverage_col_nonnull(col: str) -> str:
    return f"SELECT COUNT(*) FROM snapshots WHERE ticker=? AND timeframe=? AND {col} IS NOT NULL"


def sql_db_coverage_col_labeled(col: str) -> str:
    return (
        "SELECT COUNT(*) FROM snapshots WHERE ticker=? AND timeframe=? AND "
        + col
        + " IN ('up','down','flat')"
    )


def sql_db_coverage_gap_lag() -> str:
    return (
        "SELECT COUNT(*) FROM (\n"
        "                      SELECT ts_utc,\n"
        "                        LAG(ts_utc) OVER (ORDER BY ts_utc) AS prev_ts\n"
        "                      FROM snapshots\n"
        "                      WHERE ticker=? AND timeframe=?\n"
        "                    ) x\n"
        "                    WHERE prev_ts IS NOT NULL AND (ts_utc - prev_ts) > 120\n"
        "                    "
    )


def sql_snapshots_training_fingerprint_select(aggs_csv: str) -> str:
    """Grouped aggregate over snapshots for training fingerprinting (caller supplies SELECT list)."""
    return (
        f"SELECT timeframe, {aggs_csv} FROM snapshots "
        "WHERE timeframe IN (?, ?) GROUP BY timeframe ORDER BY timeframe"
    )


def sql_issue19_snapshots_context_group(col: str) -> str:
    """Labeled-row distribution for Issue 19 context audit (whitelist columns only)."""
    if col not in _ISSUE19_CTX_GROUP_COLS:
        raise ValueError(f"unsupported context group column: {col!r}")
    return (
        f"SELECT COALESCE({col}, '(null)') AS k, COUNT(*) AS n FROM snapshots "
        "WHERE timeframe = ? AND outcome_1c IS NOT NULL "
        "GROUP BY k ORDER BY n DESC LIMIT 50"
    )


_snapshot_sql_registry: Optional[dict[str, str]] = None


def get_snapshot_sql(key: str) -> str:
    """Return a registered snapshot SELECT/DELETE/COUNT SQL fragment by key."""
    global _snapshot_sql_registry
    if _snapshot_sql_registry is None:
        import json as _json

        d = Path(__file__).resolve().parent / "snapshot_sql"
        if not d.is_dir():
            raise FileNotFoundError(f"snapshot_sql/ directory missing next to db.py: {d}")
        merged: dict[str, str] = {}
        for p in sorted(d.glob("*.json")):
            merged.update(_json.loads(p.read_text(encoding="utf-8")))
        _snapshot_sql_registry = merged
    if key not in _snapshot_sql_registry:
        raise KeyError(f"Unknown snapshot SQL registry key: {key!r}")
    return _snapshot_sql_registry[key]
