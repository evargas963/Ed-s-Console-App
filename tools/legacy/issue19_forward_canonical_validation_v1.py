#!/usr/bin/env python3
"""
Forward canonical validation: recent 1m pin_neutral health + Issue 19 tier pools (recent window).

Read-only. Used by docs/issue19_forward_canonical_validation.md.

Example:
  python tools/issue19_forward_canonical_validation_v1.py --db data/ed_console.db
  python tools/issue19_forward_canonical_validation_v1.py --db data/ed_console.db --json-out data/issue19_forward_canonical_validation_v1.json
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
from timeframe_config import CANONICAL_TIMEFRAME

from tools.issue19_option_a_post_validate import (  # noqa: E402
    _connect,
    _count_tier_sql,
    load_default_anchors,
)


def _pin_neutral_1m_all_time(conn: sqlite3.Connection) -> dict[str, Any]:
    r = conn.execute(
        get_snapshot_sql("tools/issue19_forward_canonical_validation_v1.py:35"),
        (CANONICAL_TIMEFRAME,),
    ).fetchone()
    return {k: r[k] for k in r.keys()} if r else {}


def _pin_neutral_forward_stats(conn: sqlite3.Connection, since_ts: float) -> dict[str, Any]:
    def _one(sql: str, params: tuple) -> dict[str, Any]:
        r = conn.execute(sql, params).fetchone()
        return {k: r[k] for k in r.keys()} if r else {}

    return {
        "pin_neutral_1m_since": _one(
            get_snapshot_sql("tools/issue19_forward_canonical_validation_v1.py:pin_1m_since"),
            (CANONICAL_TIMEFRAME, since_ts),
        ),
        "pin_neutral_1m_rth_since": _one(
            get_snapshot_sql("tools/issue19_forward_canonical_validation_v1.py:pin_1m_rth_since"),
            (CANONICAL_TIMEFRAME, since_ts),
        ),
        "pin_neutral_5m_since_excluded_from_issue19": _one(
            get_snapshot_sql("tools/issue19_forward_canonical_validation_v1.py:pin_5m_since"),
            (since_ts,),
        ),
    }


def _anchor_feasible_count(conn: sqlite3.Connection, since_ts: float) -> dict[str, Any]:
    """Rows with outcome_1c and a plausible bar anchor (last bar_end <= ts_utc exists)."""
    r = conn.execute(
        get_snapshot_sql("tools/issue19_forward_canonical_validation_v1.py:94"),
        (CANONICAL_TIMEFRAME, since_ts),
    ).fetchone()
    return {"pin_neutral_1m_labeled_anchor_feasible_since": int(r["n"] if r else 0)}


def issue19_pools_for_window(
    conn: sqlite3.Connection,
    anchors: list[dict[str, Any]],
    since_ts: float | None,
    label: str,
) -> dict[str, Any]:
    """Tier1/tier2 counts per anchor; if since_ts is None, all history (no ts filter)."""
    pin_anchors = [a for a in anchors if str(a.get("zone") or "").lower() == "pin_neutral"]
    per: list[dict[str, Any]] = []
    for a in pin_anchors:
        tf = a["timeframe"]
        n1 = _count_tier_sql(
            conn,
            tier=1,
            ticker=a["ticker"],
            timeframe=tf,
            zone=a["zone"],
            vwap_side=a["vwap_side"],
            nearest_above_dist=a.get("nearest_above_dist"),
            nearest_below_dist=a.get("nearest_below_dist"),
            min_ts_utc=since_ts,
        )
        n2 = _count_tier_sql(
            conn,
            tier=2,
            ticker=a["ticker"],
            timeframe=tf,
            zone=a["zone"],
            vwap_side=a["vwap_side"],
            nearest_above_dist=a.get("nearest_above_dist"),
            nearest_below_dist=a.get("nearest_below_dist"),
            min_ts_utc=since_ts,
        )
        per.append(
            {
                "anchor_id": a.get("anchor_id"),
                "ticker": a["ticker"],
                "zone": a["zone"],
                "vwap_side": a["vwap_side"],
                "timeframe": tf,
                "tier1_count": n1,
                "tier2_count": n2,
            }
        )
    t1_any = sum(1 for x in per if x["tier1_count"] > 0)
    t2_any = sum(1 for x in per if x["tier2_count"] > 0)
    max_t1 = max((x["tier1_count"] for x in per), default=0)
    max_t2 = max((x["tier2_count"] for x in per), default=0)
    return {
        "schema": label,
        "since_ts_utc": since_ts,
        "pin_neutral_anchors": len(pin_anchors),
        "anchors_with_tier1_positive": t1_any,
        "anchors_with_tier2_positive": t2_any,
        "max_tier1_pool": max_t1,
        "max_tier2_pool": max_t2,
        "per_anchor": per,
    }


def _funnel_pin_neutral_1m(conn: sqlite3.Connection, since_ts: float) -> dict[str, Any]:
    """Explicit drop-off stages for pin_neutral + canonical 1m + recent window."""
    stages: list[dict[str, Any]] = []

    def count_where(extra: str, params: tuple) -> int:
        base = get_snapshot_sql(
            "tools/issue19_forward_canonical_validation_v1.py:funnel_count_base"
        )
        suffix = (" " + extra.strip()) if extra.strip() else ""
        row = conn.execute(
            base + suffix,
            (CANONICAL_TIMEFRAME, since_ts) + params,
        ).fetchone()
        return int(row["n"] if row else 0)

    n0 = count_where("", ())
    stages.append({"stage": "0_pin_neutral_1m_rows", "count": n0})
    n1 = count_where("AND horizon_outcome_schema_version = 3", ())
    stages.append({"stage": "1_bar_anchor_schema_v3", "count": n1})
    n2 = count_where(
        "AND horizon_outcome_schema_version = 3 AND outcome_1c IS NOT NULL",
        (),
    )
    stages.append({"stage": "2_outcome_1c_not_null", "count": n2})
    n3 = count_where(
        """
        AND horizon_outcome_schema_version = 3 AND outcome_1c IS NOT NULL
        AND outcome_filled = 1
        """,
        (),
    )
    stages.append({"stage": "3_outcome_filled_1", "count": n3})
    return {"schema": "pin_neutral_1m_forward_funnel_v1", "since_ts_utc": since_ts, "stages": stages}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--recent-days", type=float, default=14.0, help="Lookback for forward window")
    ap.add_argument(
        "--include-all-time-pools",
        action="store_true",
        help="Also emit pin_neutral tier counts with no ts filter (contrast vs recent-only)",
    )
    ap.add_argument("--json-out", type=Path, default=None)
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="tools.issue19_forward_canonical_validation_v1", write_capable=False)
    if not args.db.is_file():
        raise SystemExit(f"database not found: {args.db}")

    now = time.time()
    since = now - float(args.recent_days) * 86400.0
    conn = _connect(args.db)
    try:
        anchors = load_default_anchors(ROOT)
        report: dict[str, Any] = {
            "schema": "issue19_forward_canonical_validation_bundle_v1",
            "generated_ts_utc": now,
            "recent_days": args.recent_days,
            "since_ts_utc": since,
            "canonical_timeframe": CANONICAL_TIMEFRAME,
            "db_path": str(args.db.resolve()),
            "pin_neutral_1m_all_time": _pin_neutral_1m_all_time(conn),
            "pin_neutral_forward": _pin_neutral_forward_stats(conn, since),
            "anchor_feasible": _anchor_feasible_count(conn, since),
            "funnel": _funnel_pin_neutral_1m(conn, since),
            "issue19_pin_neutral_pools_recent": issue19_pools_for_window(
                conn, anchors, since, "issue19_pin_neutral_pools_recent_v1"
            ),
        }
        if args.include_all_time_pools:
            report["issue19_pin_neutral_pools_all_time"] = issue19_pools_for_window(
                conn, anchors, None, "issue19_pin_neutral_pools_all_time_v1"
            )
    finally:
        conn.close()

    text = json.dumps(report, indent=2, default=str) + "\n"
    print(text)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
