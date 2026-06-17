"""Duplicate/payload/timestamp stats for calibration_decision_log (JSON to stdout)."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from calibration.canonical_enforcement import (
    CalibrationCanonicalViolationError,
    CANONICAL_TIMEFRAME,
    enforce_calibration_decision_log_only_1m,
)
from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.json_utils import parse_json_mapping
from calibration.paths import DEFAULT_DB
from calibration.schema import ensure_calibration_schema
from calibration.statistical_integrity import (
    bucket_gate,
    verify_payload_audit_no_numeric_leak,
)
from calibration.trust import TRUSTED_PREDICATE_SQL
from db import configure_sqlite_connection, get_snapshot_sql
from math_probabilities import MIN_SAMPLES_STATISTICAL


def run_payload_audit(db_path: Path) -> dict[str, Any]:
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    configure_sqlite_connection(conn)
    conn.row_factory = sqlite3.Row
    try:
        ensure_calibration_schema(conn)
        enforce_calibration_decision_log_only_1m(conn)
    except CalibrationCanonicalViolationError:
        conn.close()
        raise

    dups = conn.execute(
        f"""
        SELECT ticker, decision_ts_utc, COUNT(*) AS c FROM calibration_decision_log
        WHERE {TRUSTED_PREDICATE_SQL}
        GROUP BY ticker, decision_ts_utc HAVING c > 1
        """
    ).fetchall()
    dup_extra = sum(int(r["c"]) - 1 for r in dups)

    n_all = int(conn.execute("SELECT COUNT(*) FROM calibration_decision_log").fetchone()[0])
    n_trusted = int(
        conn.execute(
            f"SELECT COUNT(*) FROM calibration_decision_log WHERE {TRUSTED_PREDICATE_SQL}"
        ).fetchone()[0]
    )
    n_legacy = n_all - n_trusted

    rows = conn.execute(
        f"""
        SELECT id, decision_ts_utc, ticker, final_signal, zone, vwap_side, nearest_above_dist,
               nearest_below_dist, regime_primary, regime_confidence, vol_regime,
               fusion_json, canonical_json, model_outputs_json, monte_carlo_json, multi_horizon_json
        FROM calibration_decision_log WHERE {TRUSTED_PREDICATE_SQL}
        ORDER BY RANDOM() LIMIT 30
        """
    ).fetchall()

    issues = []
    prob_issues = 0
    for r in rows:
        row_id = r["id"]
        fus = parse_json_mapping(
            r["fusion_json"], context=f"payload_audit:row_{row_id}:fusion_json"
        )
        can = parse_json_mapping(
            r["canonical_json"], context=f"payload_audit:row_{row_id}:canonical_json"
        )
        mo = parse_json_mapping(
            r["model_outputs_json"], context=f"payload_audit:row_{row_id}:model_outputs_json"
        )
        missing = []
        if r["final_signal"] is None:
            missing.append("final_signal")
        if not fus:
            missing.append("fusion_json_empty")
        if not can:
            missing.append("canonical_json_empty")
        if not mo:
            missing.append("model_outputs_json_empty")
        for k in ("xgb", "lstm", "transformer"):
            if k not in mo:
                missing.append(f"mo_missing_{k}")
        if not all(k in fus for k in ("prob_up", "prob_down", "prob_flat")):
            prob_issues += 1
        if missing:
            issues.append({"id": row_id, "missing": missing})

    snap_deltas = []
    for r in conn.execute(
        f"SELECT decision_ts_utc, ticker FROM calibration_decision_log WHERE {TRUSTED_PREDICATE_SQL}"
    ).fetchall():
        ts = float(r["decision_ts_utc"])
        tk = r["ticker"]
        s = conn.execute(
            get_snapshot_sql("calibration/payload_audit.py:89"),
            (tk, ts),
        ).fetchone()
        if s is not None and s["ts_utc"] is not None:
            snap_deltas.append(abs(float(s["ts_utc"]) - ts))

    exact_match = int(
        conn.execute(
            get_snapshot_sql("calibration/payload_audit.py:101")
        ).fetchone()[0]
    )

    conn.close()

    ts_gate = bucket_gate(n_trusted, MIN_SAMPLES_STATISTICAL)
    match_rate = (
        round(exact_match / max(n_trusted, 1), 6) if ts_gate["sufficient_sample"] else None
    )
    n_cmp = len(snap_deltas)
    dist_gate = bucket_gate(n_cmp, MIN_SAMPLES_STATISTICAL)
    if dist_gate["sufficient_sample"] and snap_deltas:
        dmin = min(snap_deltas)
        dmed = statistics.median(snap_deltas)
        dmax = max(snap_deltas)
    else:
        dmin = dmed = dmax = None

    out: dict[str, Any] = {
        "effective_timeframe": CANONICAL_TIMEFRAME,
        "source_tables": ["calibration_decision_log", "snapshots"],
        "binary_pass": True,
        "output_contract": (
            "data_quality_reporting; inferential rates/distributional summaries withheld "
            "unless MIN_SAMPLES_STATISTICAL gate passes"
        ),
        "total_rows": n_all,
        "trusted_rows": n_trusted,
        "legacy_rows_quarantined": n_legacy,
        "study_payload_metrics_use_trusted_only": True,
        "duplicate_key_groups": len(dups),
        "duplicate_extra_rows": dup_extra,
        "sample_size": len(rows),
        "fusion_prob_keys_missing_in_sample": prob_issues,
        "payload_rows_with_listed_issues": len(issues),
        "issues_detail": issues[:10],
        "snapshot_exact_ts_match_count": exact_match,
        "snapshot_exact_ts_match_rate": match_rate,
        "snapshot_exact_ts_match_rate_gate": ts_gate,
        "snapshot_nearest_abs_delta_sec": {
            "min": dmin,
            "median": dmed,
            "max": dmax,
            "n_compared": n_cmp,
            "distribution_sample_gate": dist_gate,
            "nearest_snapshot_query_timeframe": CANONICAL_TIMEFRAME,
        },
    }
    leak_ok = verify_payload_audit_no_numeric_leak(out)
    out["statistical_integrity"] = {
        "binary_pass": leak_ok,
        "thresholds_reference": (
            "math_probabilities.MIN_SAMPLES_STATISTICAL (30) via calibration.statistical_integrity"
        ),
    }
    out["binary_pass"] = leak_ok
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Calibration payload / join quality audit (JSON stdout)")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    if not args.db.is_file():
        print(json.dumps({"error": f"DB not found: {args.db}", "binary_pass": False}, indent=2))
        return 2
    require_canonical_db_target(
        args, tool_name="calibration.payload_audit", write_capable=False
    )
    try:
        out = run_payload_audit(args.db)
    except CalibrationCanonicalViolationError as e:
        print(json.dumps({"error": str(e), "binary_pass": False}, indent=2))
        return 2
    print(json.dumps(out, indent=2))
    return 0 if out.get("binary_pass") else 3


if __name__ == "__main__":
    sys.exit(main())
