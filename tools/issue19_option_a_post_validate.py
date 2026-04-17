#!/usr/bin/env python3
"""
Post-backfill validation for Option A distance magnitudes (read-only on DB).

Emits JSON suitable for docs/issue19_option_a_post_backfill_validation.md evidence.
Does not mutate the database.

Example:
  python tools/issue19_option_a_post_validate.py --db data/ed_console.db
  python tools/issue19_option_a_post_validate.py --db data/ed_console.db --json-out data/option_a_post_validate_last.json
"""
from __future__ import annotations

import argparse
import json
import statistics
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

# repo root = parent of tools/
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.paths import DEFAULT_DB
from db import get_snapshot_sql, sql_issue19_snapshots_context_group
from timeframe_config import CANONICAL_TIMEFRAME


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=60)
    conn.row_factory = sqlite3.Row
    return conn


def discover_distance_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT name FROM sqlite_master
        WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    out: list[str] = []
    for (name,) in rows:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({name})").fetchall()}
        if "nearest_above_dist" in cols and "nearest_below_dist" in cols:
            out.append(name)
    return out


def table_distance_stats(conn: sqlite3.Connection, table: str) -> dict[str, Any]:
    t = table
    total = int(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
    nad_neg = int(
        conn.execute(f"SELECT COUNT(*) FROM {t} WHERE nearest_above_dist < 0").fetchone()[0]
    )
    nbd_neg = int(
        conn.execute(f"SELECT COUNT(*) FROM {t} WHERE nearest_below_dist < 0").fetchone()[0]
    )
    nad_null = int(
        conn.execute(f"SELECT COUNT(*) FROM {t} WHERE nearest_above_dist IS NULL").fetchone()[0]
    )
    nbd_null = int(
        conn.execute(f"SELECT COUNT(*) FROM {t} WHERE nearest_below_dist IS NULL").fetchone()[0]
    )
    viol_a = int(
        conn.execute(
            f"SELECT COUNT(*) FROM {t} WHERE nearest_above_dist IS NOT NULL AND nearest_above_dist < 0"
        ).fetchone()[0]
    )
    viol_b = int(
        conn.execute(
            f"SELECT COUNT(*) FROM {t} WHERE nearest_below_dist IS NOT NULL AND nearest_below_dist < 0"
        ).fetchone()[0]
    )
    return {
        "table": t,
        "total_rows": total,
        "nearest_above_dist_lt_0": nad_neg,
        "nearest_below_dist_lt_0": nbd_neg,
        "nearest_above_dist_null": nad_null,
        "nearest_below_dist_null": nbd_null,
        "non_null_negative_violations": {"nearest_above_dist": viol_a, "nearest_below_dist": viol_b},
    }


def load_prior_backfill_audit(repo_root: Path) -> Optional[dict[str, Any]]:
    p = repo_root / "data" / "distance_option_a_backfill_v1_last_audit.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def schema_flag_status(conn: sqlite3.Connection) -> dict[str, Any]:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ed_schema_flags (
            flag_key    TEXT PRIMARY KEY,
            flag_value  TEXT NOT NULL,
            set_ts_utc  REAL
        )
        """
    )
    row = conn.execute(
        "SELECT flag_key, flag_value, set_ts_utc FROM ed_schema_flags WHERE flag_key = ?",
        ("distance_magnitude_option_a_v1",),
    ).fetchone()
    if not row:
        return {
            "flag_key": "distance_magnitude_option_a_v1",
            "flag_value": None,
            "set_ts_utc": None,
            "row_present": False,
        }
    return {
        "flag_key": row["flag_key"],
        "flag_value": row["flag_value"],
        "set_ts_utc": row["set_ts_utc"],
        "row_present": True,
    }


def _count_tier_sql(
    conn: sqlite3.Connection,
    *,
    tier: int,
    ticker: str,
    timeframe: str,
    zone: str,
    vwap_side: str,
    nearest_above_dist: Optional[float],
    nearest_below_dist: Optional[float],
    min_ts_utc: Optional[float] = None,
) -> int:
    """Mirror Issue 19 tier 1/2 WHERE clauses (snapshots only).

    When ``min_ts_utc`` is set, only rows with ``ts_utc >= min_ts_utc`` are counted
    (forward / recent-window validation).
    """
    from math_exposure import bucket_hi, bucket_lo, dist_bucket

    t = (ticker or "").upper().strip()
    above_bucket = dist_bucket(nearest_above_dist)
    below_bucket = dist_bucket(nearest_below_dist)
    alo, ahi = bucket_lo(above_bucket), bucket_hi(above_bucket)
    blo, bhi = bucket_lo(below_bucket), bucket_hi(below_bucket)
    _recent = "" if min_ts_utc is None else " AND ts_utc >= ? "

    if tier == 1:
        params1: tuple[Any, ...] = (
            t,
            timeframe,
            zone,
            vwap_side,
            nearest_above_dist,
            alo,
            ahi,
            nearest_below_dist,
            blo,
            bhi,
        )
        if min_ts_utc is not None:
            params1 = params1 + (min_ts_utc,)
        row = conn.execute(
            get_snapshot_sql("tools/pin_neutral_eligibility_funnel_v1.py:169") + _recent,
            params1,
        ).fetchone()
    elif tier == 2:
        params2: tuple[Any, ...] = (
            t,
            timeframe,
            zone,
            vwap_side,
            nearest_above_dist,
            alo,
            ahi,
        )
        if min_ts_utc is not None:
            params2 = params2 + (min_ts_utc,)
        row = conn.execute(
            get_snapshot_sql("tools/pin_neutral_eligibility_funnel_v1.py:199") + _recent,
            params2,
        ).fetchone()
    else:
        raise ValueError("tier must be 1 or 2")
    return int(row["n"])


def load_default_anchors(repo_root: Path) -> list[dict[str, Any]]:
    from adaptive_shadow_v2_calibration import load_survivorship_anchors_v1

    return load_survivorship_anchors_v1()


def issue19_coverage_at_scale(
    conn: sqlite3.Connection,
    anchors: list[dict[str, Any]],
) -> dict[str, Any]:
    per: list[dict[str, Any]] = []
    for a in anchors:
        n1 = _count_tier_sql(
            conn,
            tier=1,
            ticker=a["ticker"],
            timeframe=a["timeframe"],
            zone=a["zone"],
            vwap_side=a["vwap_side"],
            nearest_above_dist=a.get("nearest_above_dist"),
            nearest_below_dist=a.get("nearest_below_dist"),
        )
        n2 = _count_tier_sql(
            conn,
            tier=2,
            ticker=a["ticker"],
            timeframe=a["timeframe"],
            zone=a["zone"],
            vwap_side=a["vwap_side"],
            nearest_above_dist=a.get("nearest_above_dist"),
            nearest_below_dist=a.get("nearest_below_dist"),
        )
        per.append(
            {
                "anchor_id": a.get("anchor_id"),
                "ticker": a["ticker"],
                "zone": a["zone"],
                "vwap_side": a["vwap_side"],
                "tier1_count": n1,
                "tier2_count": n2,
            }
        )

    n_anchor = len(per)
    t1_non = sum(1 for x in per if x["tier1_count"] > 0)
    t2_non = sum(1 for x in per if x["tier2_count"] > 0)
    t1_empty = [x for x in per if x["tier1_count"] == 0]
    rescued = sum(1 for x in t1_empty if x["tier2_count"] > 0)
    tier2_rescue_rate = (rescued / len(t1_empty)) if t1_empty else 0.0

    s1 = [x["tier1_count"] for x in per]
    s2 = [x["tier2_count"] for x in per]

    by_ticker: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "anchors": 0,
            "tier1_nonempty": 0,
            "tier2_nonempty": 0,
            "tier1_counts": [],
            "tier2_counts": [],
        }
    )
    by_zone: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "anchors": 0,
            "tier1_nonempty": 0,
            "tier2_nonempty": 0,
            "tier1_counts": [],
            "tier2_counts": [],
        }
    )
    by_vwap: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "anchors": 0,
            "tier1_nonempty": 0,
            "tier2_nonempty": 0,
            "tier1_counts": [],
            "tier2_counts": [],
        }
    )

    for x in per:
        tk = x["ticker"]
        z = str(x["zone"])
        vs = str(x["vwap_side"])
        for bucket, key in (
            (by_ticker, tk),
            (by_zone, z),
            (by_vwap, vs),
        ):
            b = bucket[key]
            b["anchors"] += 1
            b["tier1_counts"].append(x["tier1_count"])
            b["tier2_counts"].append(x["tier2_count"])
            if x["tier1_count"] > 0:
                b["tier1_nonempty"] += 1
            if x["tier2_count"] > 0:
                b["tier2_nonempty"] += 1

    def _finalize(group: dict[str, dict[str, Any]]) -> dict[str, Any]:
        out = {}
        for k, v in sorted(group.items()):
            c1, c2 = v["tier1_counts"], v["tier2_counts"]
            out[k] = {
                "anchors": v["anchors"],
                "tier1_nonempty": v["tier1_nonempty"],
                "tier1_nonempty_rate": round(v["tier1_nonempty"] / v["anchors"], 6) if v["anchors"] else 0.0,
                "tier2_nonempty": v["tier2_nonempty"],
                "tier2_nonempty_rate": round(v["tier2_nonempty"] / v["anchors"], 6) if v["anchors"] else 0.0,
                "mean_tier1_pool": round(statistics.mean(c1), 4) if c1 else 0.0,
                "median_tier1_pool": float(statistics.median(c1)) if c1 else 0.0,
                "mean_tier2_pool": round(statistics.mean(c2), 4) if c2 else 0.0,
                "median_tier2_pool": float(statistics.median(c2)) if c2 else 0.0,
            }
        return out

    return {
        "schema": "issue19_option_a_coverage_at_scale_v1",
        "anchors_total": n_anchor,
        "tier1_nonempty_count": t1_non,
        "tier1_nonempty_rate": round(t1_non / n_anchor, 6) if n_anchor else 0.0,
        "tier2_nonempty_count": t2_non,
        "tier2_nonempty_rate": round(t2_non / n_anchor, 6) if n_anchor else 0.0,
        "tier1_empty_count": len(t1_empty),
        "tier2_rescue_count_among_tier1_empty": rescued,
        "tier2_rescue_rate_among_tier1_empty": round(tier2_rescue_rate, 6),
        "mean_tier1_pool_size": round(statistics.mean(s1), 4) if s1 else 0.0,
        "median_tier1_pool_size": float(statistics.median(s1)) if s1 else 0.0,
        "mean_tier2_pool_size": round(statistics.mean(s2), 4) if s2 else 0.0,
        "median_tier2_pool_size": float(statistics.median(s2)) if s2 else 0.0,
        "per_anchor": per,
        "breakdown_by_ticker": _finalize(by_ticker),
        "breakdown_by_zone": _finalize(by_zone),
        "breakdown_by_vwap_side": _finalize(by_vwap),
    }


def snapshots_context_distribution(conn: sqlite3.Connection) -> dict[str, Any]:
    """Labeled rows only: how much history exists per session / regime / vix bucket."""
    out: dict[str, Any] = {
        "base_filter": f"timeframe={CANONICAL_TIMEFRAME!r} AND outcome_1c IS NOT NULL",
        "groups": {},
    }

    def _group(col: str) -> list[dict[str, Any]]:
        try:
            rows = conn.execute(
                sql_issue19_snapshots_context_group(col),
                (CANONICAL_TIMEFRAME,),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [{"key": r["k"], "count": int(r["n"])} for r in rows]

    for col in ("session_bucket", "regime_primary", "vix_bucket", "market_session"):
        g = _group(col)
        if g:
            out["groups"][col] = g
    return out


def compare_raw_vs_normalized_distance_ranges(conn: sqlite3.Connection) -> dict[str, Any]:
    """Cheap consistency hint: min/max of stored magnitudes (no row-level join)."""
    info: dict[str, Any] = {}

    def _mm(table: str) -> Optional[dict[str, Any]]:
        try:
            r = conn.execute(
                f"""
                SELECT
                  COUNT(*) AS n,
                  MIN(nearest_above_dist) AS nad_min,
                  MAX(nearest_above_dist) AS nad_max,
                  MIN(nearest_below_dist) AS nbd_min,
                  MAX(nearest_below_dist) AS nbd_max
                FROM {table}
                """
            ).fetchone()
        except sqlite3.OperationalError:
            return None
        return {k: r[k] for k in r.keys()}

    info["snapshots"] = _mm("snapshots")
    info["snapshots_1m_normalized"] = _mm("snapshots_1m_normalized")
    return info


def build_report(db_path: Path, *, repo_root: Path) -> dict[str, Any]:
    db_path = db_path.resolve()
    report: dict[str, Any] = {
        "schema": "option_a_post_backfill_validation_bundle_v1",
        "generated_ts_utc": time.time(),
        "db_path": str(db_path),
    }
    conn = _connect(db_path)
    try:
        tables = discover_distance_tables(conn)
        report["distance_tables_discovered"] = tables
        report["per_table_distance_stats"] = {t: table_distance_stats(conn, t) for t in tables}
        report["schema_flag_distance_magnitude_option_a_v1"] = schema_flag_status(conn)
        report["prior_backfill_audit_summary"] = load_prior_backfill_audit(repo_root)
        report["raw_vs_normalized_minmax"] = compare_raw_vs_normalized_distance_ranges(conn)
        report["snapshots_labeled_context_distribution"] = snapshots_context_distribution(conn)

        anchors = load_default_anchors(repo_root)
        report["issue19_coverage_at_scale"] = issue19_coverage_at_scale(conn, anchors)
    finally:
        conn.close()
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--json-out", type=Path, default=None)
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="tools.issue19_option_a_post_validate", write_capable=False)
    if not args.db.is_file():
        raise SystemExit(f"database not found: {args.db}")
    r = build_report(args.db, repo_root=ROOT)
    text = json.dumps(r, indent=2)
    print(text)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
