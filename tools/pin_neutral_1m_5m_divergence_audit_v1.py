#!/usr/bin/env python3
"""
Issue 19 — pin_neutral 1m vs 5m population + eligibility evidence (read-only).

Outputs JSON for docs/issue19_pin_neutral_1m_5m_divergence_audit.md.

Usage:
  python tools/pin_neutral_1m_5m_divergence_audit_v1.py --db data/ed_console.db
  python tools/pin_neutral_1m_5m_divergence_audit_v1.py --db data/ed_console.db \\
      --json-out data/pin_neutral_1m_5m_divergence_audit_v1.json
"""
from __future__ import annotations

from db import get_snapshot_sql


import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.paths import DEFAULT_DB
from horizon_outcomes import HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1
from timeframe_config import CANONICAL_TIMEFRAME, DERIVED_TIMEFRAME

from tools.issue19_option_a_post_validate import _count_tier_sql, load_default_anchors

V1 = HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1
TF1 = CANONICAL_TIMEFRAME
TF5 = DERIVED_TIMEFRAME


def connect(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db.resolve()), timeout=60)
    conn.row_factory = sqlite3.Row
    return conn


def _cnt(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> int:
    r = conn.execute(sql, params).fetchone()
    if r is None or r[0] is None:
        return 0
    return int(r[0])


def bar_anchor_scope_sql(extra: str = "", alias: str = "") -> str:
    p = f"{alias}." if alias else ""
    base = f"""
        {p}zone = 'pin_neutral'
        AND {p}timeframe = ?
        AND COALESCE({p}horizon_outcome_schema_version, ?) = ?
    """.strip()
    if extra:
        return base + " AND " + extra
    return base


def inventory_timeframe(conn: sqlite3.Connection, tf: str) -> dict[str, Any]:
    scope = (tf, V1, V1)
    _cs = get_snapshot_sql("tools/pin_neutral_1m_5m_divergence_audit_v1.py:count_star")
    total = _cnt(
        conn,
        _cs + " WHERE " + bar_anchor_scope_sql(),
        scope,
    )
    filled = _cnt(
        conn,
        _cs + " WHERE " + bar_anchor_scope_sql("COALESCE(outcome_filled,0)=1"),
        scope,
    )
    unfilled = _cnt(
        conn,
        _cs + " WHERE " + bar_anchor_scope_sql("COALESCE(outcome_filled,0)=0"),
        scope,
    )
    anch_ok = _cnt(
        conn,
        get_snapshot_sql("tools/pin_neutral_1m_5m_divergence_audit_v1.py:unfilled_has_anchor"),
        scope,
    )
    anch_bad = unfilled - anch_ok
    labeled_o1 = _cnt(
        conn,
        _cs + " WHERE " + bar_anchor_scope_sql("outcome_1c IS NOT NULL"),
        scope,
    )
    return {
        "timeframe": tf,
        "total_bar_anchor_scope": total,
        "outcome_filled_1": filled,
        "outcome_filled_0": unfilled,
        "unfilled_anchor_feasible": anch_ok,
        "unfilled_anchor_infeasible": anch_bad,
        "outcome_1c_nonnull": labeled_o1,
    }


def by_ticker_breakdown(conn: sqlite3.Connection, tf: str) -> list[dict[str, Any]]:
    scope = (tf, V1, V1)
    rows = conn.execute(
        get_snapshot_sql("tools/pin_neutral_1m_5m_divergence_audit_v1.py:by_ticker_agg")
        + " WHERE "
        + bar_anchor_scope_sql()
        + "\n        GROUP BY ticker ORDER BY n_total DESC",
        scope,
    ).fetchall()
    return [dict(r) for r in rows]


def issue19_funnel_for_tf(conn: sqlite3.Connection, tf: str) -> dict[str, Any]:
    """Stages 1–9 for one timeframe (pin_neutral BAR_ANCHOR scope only)."""
    scope = (tf, V1, V1)
    _cs = get_snapshot_sql("tools/pin_neutral_1m_5m_divergence_audit_v1.py:count_star")
    s1 = _cnt(conn, _cs + " WHERE " + bar_anchor_scope_sql(), scope)
    s2 = _cnt(
        conn,
        _cs + " WHERE " + bar_anchor_scope_sql("outcome_1c IS NOT NULL"),
        scope,
    )
    s3 = s1  # schema already in scope
    s4 = s1  # ticker identity: rows exist in snapshots as stored
    s5 = s1  # zone pinned by scope
    s6 = s2  # vwap_side: any value; labeled subset still in zone
    per_anchor_t1: list[dict[str, Any]] = []
    per_anchor_t2: list[dict[str, Any]] = []
    anchors = [a for a in load_default_anchors(ROOT) if (a.get("zone") or "") == "pin_neutral"]
    for a in anchors:
        t1 = _count_tier_sql(
            conn,
            tier=1,
            ticker=a["ticker"],
            timeframe=tf,
            zone=a["zone"],
            vwap_side=a["vwap_side"],
            nearest_above_dist=a.get("nearest_above_dist"),
            nearest_below_dist=a.get("nearest_below_dist"),
        )
        t2 = _count_tier_sql(
            conn,
            tier=2,
            ticker=a["ticker"],
            timeframe=tf,
            zone=a["zone"],
            vwap_side=a["vwap_side"],
            nearest_above_dist=a.get("nearest_above_dist"),
            nearest_below_dist=a.get("nearest_below_dist"),
        )
        per_anchor_t1.append({"anchor_id": a.get("anchor_id"), "tier1": t1})
        per_anchor_t2.append({"anchor_id": a.get("anchor_id"), "tier2": t2})
    s8 = sum(x["tier1"] for x in per_anchor_t1)  # sum not distinct
    s9 = sum(x["tier2"] for x in per_anchor_t2)
    max_t1 = max((x["tier1"] for x in per_anchor_t1), default=0)
    max_t2 = max((x["tier2"] for x in per_anchor_t2), default=0)
    collapse = None
    if s1 == 0:
        collapse = {"stage": 1, "reason": "zero rows in pin_neutral BAR_ANCHOR scope for this timeframe"}
    elif s2 == 0:
        collapse = {"stage": 2, "reason": "no rows with outcome_1c IS NOT NULL at this timeframe"}
    elif max_t1 == 0:
        collapse = {
            "stage": "7_8",
            "reason": "labeled rows fail ticker+zone+vwap_side+distance match for every pin_neutral anchor at Issue 19 tier1 SQL",
            "max_tier1_any_anchor": 0,
        }
    return {
        "timeframe": tf,
        "stage1_total": s1,
        "stage2_labeled_outcome_1c": s2,
        "stage3_schema_bar_anchor_v1": s3,
        "stage4_ticker_rows_exist": s4,
        "stage5_zone_pin_neutral": s5,
        "stage6_labeled_with_zone_ok": s6,
        "stage7_note": "vwap_side+distance validity encoded in per-anchor tier SQL (not a single global count)",
        "stage8_tier1_sum_over_anchors": s8,
        "stage8_tier1_max_single_anchor": max_t1,
        "stage9_tier2_sum_over_anchors": s9,
        "stage9_tier2_max_single_anchor": max_t2,
        "per_anchor_tier1": per_anchor_t1,
        "per_anchor_tier2": per_anchor_t2,
        "collapse_if_zero_pool": collapse,
    }


def pin_neutral_any_schema(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        get_snapshot_sql("tools/pin_neutral_1m_5m_divergence_audit_v1.py:198")
    ).fetchall()
    return {"by_timeframe_any_schema": [dict(r) for r in rows]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--json-out", type=Path, default=None)
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="tools.pin_neutral_1m_5m_divergence_audit_v1", write_capable=False)
    if not args.db.is_file():
        raise SystemExit(f"DB not found: {args.db}")

    conn = connect(args.db)
    try:
        out: dict[str, Any] = {
            "schema": "pin_neutral_1m_5m_divergence_audit_v1",
            "generated_ts_utc": time.time(),
            "db_path": str(args.db.resolve()),
            "canonical_timeframes": {"1m": TF1, "5m": TF5},
            "bar_anchor_schema_version": V1,
            "population_bar_anchor_scope": {
                TF1: inventory_timeframe(conn, TF1),
                TF5: inventory_timeframe(conn, TF5),
            },
            "by_ticker_bar_anchor_scope": {
                TF1: by_ticker_breakdown(conn, TF1),
                TF5: by_ticker_breakdown(conn, TF5),
            },
            "pin_neutral_all_schemas": pin_neutral_any_schema(conn),
            "issue19_funnel": {
                TF1: issue19_funnel_for_tf(conn, TF1),
                TF5: issue19_funnel_for_tf(conn, TF5),
            },
            "code_reference_notes": {
                "live_fill_outcomes": "db.py EdDB.fill_outcomes returns immediately if timeframe != CANONICAL_TIMEFRAME (1m)",
                "live_server": "server.py calls fill_outcomes(ticker, CANONICAL_TIMEFRAME, _snap_ts); inserts timeframe=CANONICAL_TIMEFRAME",
                "pin_neutral_repair": "db.py fill_outcomes_pin_neutral_backfill_v1 includes timeframe IN (1m,5m); _apply_bar_based_outcome_updates has no timeframe branch",
                "issue19_tier_sql": "tools/issue19_option_a_post_validate._count_tier_sql requires snapshots.timeframe = anchor time (default 1m from JSON)",
                "timeframe_config": "timeframe_config.py documents 1m as canonical for snapshots/features/training",
            },
        }
    finally:
        conn.close()

    text = json.dumps(out, indent=2, default=str) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
