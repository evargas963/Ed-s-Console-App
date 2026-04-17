#!/usr/bin/env python3
"""
Phase 1 — Data integrity audit for calibration.

Usage:
  python -m calibration.audit_phase1
  python -m calibration.audit_phase1 --db path/to/ed_console.db

Writes JSON to models/calibration_runs/phase1_audit_<unix_ts>.json
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.paths import DEFAULT_DB, ensure_artifacts_dir
from calibration.schema import ensure_calibration_schema
from calibration.statistical_integrity import bucket_gate, verify_audit_phase1_no_numeric_leak
from db import get_snapshot_sql
from math_probabilities import MIN_SAMPLES_STATISTICAL
from instrument_identity import ticker_storage_key
from timeframe_config import CANONICAL_TIMEFRAME

# BAR_ANCHOR_V1: bar lookups use ticker_storage_key (same as db.fill_outcomes).


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        from db import configure_sqlite_connection

        configure_sqlite_connection(conn)
    except Exception:
        pass
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    r = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (name,)
    ).fetchone()
    return r is not None


def _gap_stats(gaps: list[float]) -> dict[str, Any]:
    """Gap distribution summaries withheld unless len(gaps) >= MIN_SAMPLES_STATISTICAL."""
    n = len(gaps)
    gate = bucket_gate(n, MIN_SAMPLES_STATISTICAL)
    if not gaps or not gate["sufficient_sample"]:
        return {
            "n": n,
            "median": None,
            "p95": None,
            "max": None,
            "distribution_sample_gate": gate,
        }
    s = sorted(gaps)
    p95_i = min(n - 1, max(0, int(math.ceil(0.95 * n) - 1)))
    return {
        "n": n,
        "median": float(statistics.median(s)),
        "p95": float(s[p95_i]),
        "max": float(s[-1]),
        "distribution_sample_gate": gate,
    }


def run_audit(db_path: Path) -> dict[str, Any]:
    out: dict[str, Any] = {
        "meta": {
            "db_path": str(db_path.resolve()),
            "run_ts_utc": time.time(),
            "canonical_timeframe_expected": CANONICAL_TIMEFRAME,
        },
        "tables_present": {},
        "timeframe_enforcement": {},
        "gap_continuity_snapshots_1m": {},
        "gap_continuity_price_bars_1m": {},
        "snapshot_bar_alignment": {},
        "outcome_label_integrity": {},
        "structural_field_completeness": {},
        "symbol_normalization": {},
        "notes": [],
    }

    if not db_path.is_file():
        out["fatal"] = "database file not found"
        return out

    conn = _connect(db_path)
    try:
        try:
            ensure_calibration_schema(conn)
        except Exception:
            pass
        out["tables_present"]["snapshots"] = _table_exists(conn, "snapshots")
        out["tables_present"]["price_bars_1m"] = _table_exists(conn, "price_bars_1m")
        out["tables_present"]["calibration_decision_log"] = _table_exists(
            conn, "calibration_decision_log"
        )

        # ── 1. Timeframe enforcement ─────────────────────────────────────
        if out["tables_present"]["snapshots"]:
            rows = conn.execute(
                get_snapshot_sql("calibration/audit_phase1.py:104")
            ).fetchall()
            tf_dist = {r["timeframe"]: int(r["n"]) for r in rows}
            out["timeframe_enforcement"]["snapshots_by_timeframe"] = tf_dist
            non_canon = {k: v for k, v in tf_dist.items() if k != CANONICAL_TIMEFRAME}
            out["timeframe_enforcement"]["non_canonical_timeframe_rows"] = non_canon
            out["timeframe_enforcement"]["violations_count"] = sum(non_canon.values())
        else:
            out["notes"].append("snapshots table missing — cannot audit timeframes")

        # ── 2. Gap / continuity (snapshots, 1m only) ───────────────────
        if out["tables_present"]["snapshots"]:
            tickers = [
                r[0]
                for r in conn.execute(
                    get_snapshot_sql("calibration/audit_phase1.py:119"),
                    (CANONICAL_TIMEFRAME,),
                ).fetchall()
            ]
            per_ticker: dict[str, Any] = {}
            for tk in tickers:
                ts_list = [
                    float(r[0])
                    for r in conn.execute(
                        get_snapshot_sql("calibration/audit_phase1.py:128"),
                        (tk, CANONICAL_TIMEFRAME),
                    ).fetchall()
                ]
                if len(ts_list) < 2:
                    per_ticker[tk] = {
                        "row_count": len(ts_list),
                        "gap_seconds": _gap_stats([]),
                        "gaps_gt_120s": 0,
                        "gaps_gt_120s_during_rth": 0,
                    }
                    continue
                gaps = [ts_list[i] - ts_list[i - 1] for i in range(1, len(ts_list))]
                # RTH gaps: both rows market_session = 'rth' when available
                rth_gaps = 0
                sess_rows = conn.execute(
                    get_snapshot_sql("calibration/audit_phase1.py:144"),
                    (tk, CANONICAL_TIMEFRAME),
                ).fetchall()
                if sess_rows:
                    by_ts = {float(r["ts_utc"]): (r["market_session"] or "") for r in sess_rows}
                    for i in range(1, len(ts_list)):
                        g = ts_list[i] - ts_list[i - 1]
                        if g <= 120:
                            continue
                        s0 = by_ts.get(ts_list[i - 1], "")
                        s1 = by_ts.get(ts_list[i], "")
                        if s0 == "rth" and s1 == "rth":
                            rth_gaps += 1

                gt120 = sum(1 for g in gaps if g > 120.0)
                per_ticker[tk] = {
                    "row_count": len(ts_list),
                    "gap_seconds": _gap_stats(gaps),
                    "gaps_gt_120s": gt120,
                    "gaps_gt_120s_during_rth": rth_gaps,
                }
            out["gap_continuity_snapshots_1m"]["per_ticker"] = per_ticker
            out["gap_continuity_snapshots_1m"]["ticker_count"] = len(tickers)

        # ── 2b. price_bars_1m gaps ─────────────────────────────────────
        if out["tables_present"]["price_bars_1m"]:
            bar_tickers = [
                r[0]
                for r in conn.execute(
                    "SELECT DISTINCT ticker FROM price_bars_1m ORDER BY ticker"
                ).fetchall()
            ]
            bar_per: dict[str, Any] = {}
            for tk in bar_tickers:
                starts = [
                    float(r[0])
                    for r in conn.execute(
                        "SELECT bar_start_ts_utc FROM price_bars_1m WHERE ticker=? ORDER BY bar_start_ts_utc",
                        (tk,),
                    ).fetchall()
                ]
                if len(starts) < 2:
                    bar_per[tk] = {"bar_rows": len(starts), "gap_seconds": _gap_stats([])}
                    continue
                bgaps = [starts[i] - starts[i - 1] for i in range(1, len(starts))]
                bar_per[tk] = {
                    "bar_rows": len(starts),
                    "gap_seconds": _gap_stats(bgaps),
                    "gaps_ne_60s": sum(1 for g in bgaps if abs(g - 60.0) > 1.0),
                }
            out["gap_continuity_price_bars_1m"]["per_ticker"] = bar_per

        # ── 3. Snapshot ↔ bar alignment ────────────────────────────────
        if out["tables_present"]["snapshots"] and out["tables_present"]["price_bars_1m"]:
            sample = conn.execute(
                get_snapshot_sql("calibration/audit_phase1.py:random_sample_ts"),
                (CANONICAL_TIMEFRAME,),
            ).fetchall()
            no_anchor = 0
            no_anchor_raw_ticker_only = 0
            checked = 0
            for r in sample:
                checked += 1
                tk = r["ticker"]
                ts = float(r["ts_utc"])
                t_key = ticker_storage_key(tk)
                a = conn.execute(
                    """
                    SELECT MAX(bar_end_ts_utc) AS mx FROM price_bars_1m
                    WHERE ticker=? AND bar_end_ts_utc <= ?
                    """,
                    (t_key, ts),
                ).fetchone()
                if a is None or a["mx"] is None:
                    no_anchor += 1
                a_raw = conn.execute(
                    """
                    SELECT MAX(bar_end_ts_utc) AS mx FROM price_bars_1m
                    WHERE ticker=? AND bar_end_ts_utc <= ?
                    """,
                    (tk, ts),
                ).fetchone()
                if (a_raw is None or a_raw["mx"] is None) and a is not None and a["mx"] is not None:
                    no_anchor_raw_ticker_only += 1
            align_gate = bucket_gate(checked, MIN_SAMPLES_STATISTICAL)
            frac_missing = (
                round(no_anchor / max(checked, 1), 6) if align_gate["sufficient_sample"] else None
            )
            out["snapshot_bar_alignment"] = {
                "anchor_rule": "BAR_ANCHOR_V1: MAX(bar_end_ts_utc) <= ts_utc from price_bars_1m WHERE ticker=ticker_storage_key(snapshots.ticker)",
                "random_sample_size": checked,
                "snapshots_missing_anchor_bar_end_lte_ts": no_anchor,
                "fraction_missing_anchor": frac_missing,
                "fraction_missing_anchor_gate": align_gate,
                "sample_rows_would_miss_using_raw_ticker_but_hit_with_storage_key": no_anchor_raw_ticker_only,
            }
        else:
            out["snapshot_bar_alignment"] = {"error": "need snapshots + price_bars_1m"}

        # ── 4. Outcome labels ───────────────────────────────────────────
        if out["tables_present"]["snapshots"]:
            oc = conn.execute(
                get_snapshot_sql("calibration/audit_phase1.py:245"),
                (CANONICAL_TIMEFRAME,),
            ).fetchone()
            n = int(oc["n"] or 0)
            nr_gate = bucket_gate(n, MIN_SAMPLES_STATISTICAL)
            out["outcome_label_integrity"]["row_count_1m"] = n
            if nr_gate["sufficient_sample"]:
                out["outcome_label_integrity"]["null_rates"] = {
                    "outcome_1c": float(oc["o1_null"] or 0) / max(n, 1),
                    "outcome_5c": float(oc["o5_null"] or 0) / max(n, 1),
                    "outcome_15c": float(oc["o15_null"] or 0) / max(n, 1),
                    "outcome_60c": float(oc["o60_null"] or 0) / max(n, 1),
                }
            else:
                out["outcome_label_integrity"]["null_rates"] = {
                    "outcome_1c": None,
                    "outcome_5c": None,
                    "outcome_15c": None,
                    "outcome_60c": None,
                }
            out["outcome_label_integrity"]["null_rates_sample_gate"] = nr_gate
            # Direction vs pts sign sanity (loose — spot moves can be tiny)
            weird = conn.execute(
                get_snapshot_sql("calibration/audit_phase1.py:266"),
                (CANONICAL_TIMEFRAME,),
            ).fetchone()
            out["outcome_label_integrity"]["suspect_up_negative_pts_gt_0_25"] = int(
                weird["c"] or 0
            )
            weird2 = conn.execute(
                get_snapshot_sql("calibration/audit_phase1.py:276"),
                (CANONICAL_TIMEFRAME,),
            ).fetchone()
            out["outcome_label_integrity"]["suspect_down_positive_pts_gt_0_25"] = int(
                weird2["c"] or 0
            )
            out["outcome_label_integrity"]["forward_leakage_note"] = (
                "Labels are filled by db.fill_outcomes / horizon_outcomes forward-bar contract; "
                "features in snapshot row must not include post-ts_utc bars — audit code cannot prove "
                "feature-time isolation without replay; see horizon_outcomes.OUTCOME_BAR_SPECS."
            )

        # ── 5. Structural completeness ──────────────────────────────────
        if out["tables_present"]["snapshots"]:
            st = conn.execute(
                get_snapshot_sql("calibration/audit_phase1.py:structural_completeness"),
                (CANONICAL_TIMEFRAME,),
            ).fetchone()
            nn = int(st["n"] or 0)
            st_gate = bucket_gate(nn, MIN_SAMPLES_STATISTICAL)
            if st_gate["sufficient_sample"] and nn > 0:
                zn = float(st["zone_null"] or 0) / nn
                vn = float(st["vwap_null"] or 0) / nn
            else:
                zn = vn = None
            out["structural_field_completeness"] = {
                "rows": nn,
                "zone_null_rate": zn,
                "vwap_side_null_rate": vn,
                "structural_null_rates_sample_gate": st_gate,
                "nearest_above_dist_negative_count": int(st["above_neg"] or 0),
                "nearest_below_dist_negative_count": int(st["below_neg"] or 0),
                "canonical_option_a_violation": (int(st["above_neg"] or 0) + int(st["below_neg"] or 0)) > 0,
            }

        # ── 6. Symbol normalization ────────────────────────────────────
        if out["tables_present"]["snapshots"]:
            raw = [
                r[0]
                for r in conn.execute(
                    get_snapshot_sql("calibration/audit_phase1.py:320"),
                    (CANONICAL_TIMEFRAME,),
                ).fetchall()
            ]
            key_to_variants: dict[str, list[str]] = defaultdict(list)
            for t in raw:
                key_to_variants[ticker_storage_key(t)].append(t)
            fragmented = {k: v for k, v in key_to_variants.items() if len(v) > 1}
            out["symbol_normalization"] = {
                "distinct_raw_tickers": len(raw),
                "distinct_storage_keys": len(key_to_variants),
                "fragmented_keys": fragmented,
                "fragmented_key_count": len(fragmented),
            }

    finally:
        conn.close()

    leak_ok = verify_audit_phase1_no_numeric_leak(out)
    out["statistical_integrity"] = {
        "binary_pass": leak_ok,
        "thresholds_reference": (
            "math_probabilities.MIN_SAMPLES_STATISTICAL (30) via calibration.statistical_integrity"
        ),
    }

    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 1 data integrity audit")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB, help="Path to ed_console.db")
    ap.add_argument("--json-out", type=Path, default=None, help="Override JSON output path")
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="calibration.audit_phase1", write_capable=False)

    data = run_audit(args.db)
    ensure_artifacts_dir()
    out_path = args.json_out
    if out_path is None:
        from calibration.paths import ARTIFACTS_DIR

        out_path = ARTIFACTS_DIR / f"phase1_audit_{int(time.time())}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(json.dumps({"wrote": str(out_path), "summary_keys": list(data.keys())}, indent=2))
    return 0 if "fatal" not in data else 1


if __name__ == "__main__":
    sys.exit(main())
