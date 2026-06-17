#!/usr/bin/env python3
"""
Phase 4 — Decision engine validation (edge vs baselines, MHAP, false confidence).

Uses calibration_decision_log when present; supplements with snapshots for naive baselines.
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from arch_competition.atomic_io import write_json_file_atomically
from calibration.analyze_phase3 import _load_json_col as _load_json
from calibration.anchor_audit import snapshot_has_bar_anchor
from calibration.canonical_enforcement import (
    CalibrationCanonicalViolationError,
    CANONICAL_TIMEFRAME,
    enforce_calibration_decision_log_only_1m,
    provenance_dict,
    snapshots_1m_labeled_counts,
)
from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.paths import DEFAULT_DB, ensure_artifacts_dir
from calibration.schema import ensure_calibration_schema
from calibration.trust import TRUSTED_PREDICATE_SQL
from calibration.statistical_integrity import (
    MIN_N_BASELINE_COMPARISON,
    MIN_N_DECISION_SIGNAL,
    MIN_N_MHAP_BUCKET,
    MIN_SAMPLES_STATISTICAL,
    bucket_gate,
    gated_mean,
    thresholds_dict,
    verify_phase4_no_numeric_leak,
)

log = logging.getLogger(__name__)

try:
    from db import configure_sqlite_connection
except ImportError as e:
    log.warning(
        "db.configure_sqlite_connection not available — using no-op stub: %s",
        e,
    )

    def configure_sqlite_connection(conn, **kwargs):
        pass

from db import get_snapshot_sql

# multi_horizon_decision._alignment_state producer vocabulary (uppercased at parse time).
_MHAP_ALIGNED_STATES = frozenset({"FULLY_ALIGNED", "MOSTLY_ALIGNED"})
_MHAP_MISALIGNED_STATES = frozenset({"CONTRADICTORY", "WEAK", "MIXED"})


def _directional_pnl(call_signal: str, outcome: str, pts: float | None) -> float | None:
    if pts is None:
        return None
    sig = (call_signal or "").strip().lower()
    oc = (outcome or "").strip().lower()
    if sig == "long":
        if oc == "up":
            return abs(pts)
        if oc == "down":
            return -abs(pts)
        return 0.0
    if sig == "short":
        if oc == "down":
            return abs(pts)
        if oc == "up":
            return -abs(pts)
        return 0.0
    return None


def _phase4_attach_statistical_integrity(out: dict[str, Any]) -> None:
    prov = out.get("provenance") or {}
    insufficient: dict[str, int] = {
        "decision_signal_buckets": 0,
        "mhap_aligned": 0,
        "mhap_misaligned": 0,
        "baseline_always_up": 0,
        "baseline_always_down": 0,
        "baseline_vwap_mr_proxy": 0,
        "baseline_log_vs_snapshot_comparison": 0,
    }

    def _inc(g: dict[str, Any] | None, key: str) -> None:
        if g and not g.get("sufficient_sample"):
            insufficient[key] = insufficient.get(key, 0) + 1

    for row in out.get("decision_performance_from_log", {}).values():
        _inc(row.get("sample_gate"), "decision_signal_buckets")
    mh = out.get("mhap_alignment") or {}
    _inc(mh.get("aligned_mean_gate"), "mhap_aligned")
    _inc(mh.get("misaligned_mean_gate"), "mhap_misaligned")
    bl = out.get("baselines_from_snapshots") or {}
    _inc(bl.get("always_up_mean_gate"), "baseline_always_up")
    _inc(bl.get("always_down_mean_gate"), "baseline_always_down")
    _inc(bl.get("vwap_mr_proxy_gate"), "baseline_vwap_mr_proxy")

    comp = bl.get("decision_log_vs_baseline_comparison") or {}
    if comp.get("status") == "insufficient_sample":
        insufficient["baseline_log_vs_snapshot_comparison"] += 1

    leak_ok = verify_phase4_no_numeric_leak(out)
    out["statistical_integrity"] = {
        "thresholds": thresholds_dict(),
        "thresholds_reference": "math_probabilities.MIN_SAMPLES_STATISTICAL (30) via calibration.statistical_integrity",
        "insufficient_bucket_counts": insufficient,
        "labeled_sample_count": prov.get("labeled_sample_count"),
        "excluded_by_reason": prov.get("excluded_by_reason"),
        "effective_dataset_provenance": prov,
        "binary_pass": bool(leak_ok),
    }
    if not leak_ok:
        out.setdefault("notes", []).append(
            "statistical_integrity: defensive leak check failed — inspect sample_gate fields."
        )


def analyze(db_path: Path) -> dict[str, Any]:
    out: dict[str, Any] = {
        "meta": {"db": str(db_path), "ts": time.time()},
        "provenance": None,
        "decision_performance_from_log": {},
        "mhap_alignment": {},
        "baselines_from_snapshots": {},
        "high_confidence_losses": {},
        "notes": [],
    }
    if not db_path.is_file():
        out["error"] = "db missing"
        out["statistical_integrity"] = {"binary_pass": False, "error": "db missing"}
        return out

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)
    enforce_calibration_decision_log_only_1m(conn)

    n_legacy = int(
        conn.execute(
            f"""
            SELECT COUNT(*) FROM calibration_decision_log
            WHERE canonical_timeframe=? AND NOT ({TRUSTED_PREDICATE_SQL})
            """,
            (CANONICAL_TIMEFRAME,),
        ).fetchone()[0]
    )
    n_pending = int(
        conn.execute(
            f"""
            SELECT COUNT(*) FROM calibration_decision_log
            WHERE canonical_timeframe=? AND outcome_5c IS NULL AND ({TRUSTED_PREDICATE_SQL})
            """,
            (CANONICAL_TIMEFRAME,),
        ).fetchone()[0]
    )
    rows_raw = conn.execute(
        f"""
        SELECT final_signal, call_conviction, outcome_5c, outcome_5c_pts, multi_horizon_json, canonical_json,
               ticker, decision_ts_utc
        FROM calibration_decision_log
        WHERE outcome_5c IS NOT NULL AND canonical_timeframe=? AND ({TRUSTED_PREDICATE_SQL})
        """,
        (CANONICAL_TIMEFRAME,),
    ).fetchall()
    n_excl_anchor = 0
    rows: list[Any] = []
    for r in rows_raw:
        if snapshot_has_bar_anchor(conn, r["ticker"], float(r["decision_ts_utc"])):
            rows.append(r)
        else:
            n_excl_anchor += 1
    out["provenance"] = provenance_dict(
        source_tables=["calibration_decision_log"],
        labeled_sample_count=len(rows),
        excluded_by_reason={
            "rows_without_outcome_5c": n_pending,
            "rows_without_bar_anchor_BAR_ANCHOR_V1": n_excl_anchor,
            "legacy_rows_excluded_from_study_dataset": n_legacy,
        },
    )
    out["provenance"]["effective_dataset_note"] = (
        "calibration_decision_log with outcome_5c, BAR_ANCHOR_V1 filtered; canonical_timeframe 1m; "
        "calibration_trust='trusted' only."
    )

    # Decision performance
    by_sig: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        sig = r["final_signal"] or "wait"
        oc = r["outcome_5c"]
        pts = r["outcome_5c_pts"]
        pnl = _directional_pnl(sig, oc, float(pts) if pts is not None else None)
        by_sig[sig].append({"outcome": oc, "pts": pts, "pnl_proxy": pnl})
        cj = _load_json(r["canonical_json"])
        by_sig[sig][-1]["canonical_confidence"] = cj.get("confidence")

    perf: dict[str, Any] = {}
    for sig, lst in by_sig.items():
        pnls = [x["pnl_proxy"] for x in lst if x["pnl_proxy"] is not None]
        mean_pnl, gate = gated_mean([float(x) for x in pnls], MIN_N_DECISION_SIGNAL)
        perf[sig] = {
            "n": len(lst),
            "n_directional_pnl_computed": len(pnls),
            "sample_gate": gate,
            "mean_pnl_proxy": mean_pnl,
        }
    out["decision_performance_from_log"] = perf

    # MHAP
    aligned_pts: list[float] = []
    misaligned_pts: list[float] = []
    for r in rows:
        mh = _load_json(r["multi_horizon_json"])
        st = (mh.get("alignment_state") or "").strip().upper()
        pts = r["outcome_5c_pts"]
        if pts is None:
            continue
        p = float(pts)
        if st in _MHAP_ALIGNED_STATES:
            aligned_pts.append(p)
        elif st in _MHAP_MISALIGNED_STATES:
            misaligned_pts.append(p)
    al_m, al_g = gated_mean(aligned_pts, MIN_N_MHAP_BUCKET)
    mis_m, mis_g = gated_mean(misaligned_pts, MIN_N_MHAP_BUCKET)
    out["mhap_alignment"] = {
        "aligned_n": len(aligned_pts),
        "misaligned_n": len(misaligned_pts),
        "aligned_mean_gate": al_g,
        "misaligned_mean_gate": mis_g,
        "aligned_mean_5c_pts": al_m,
        "misaligned_mean_5c_pts": mis_m,
        "note": "alignment_state parsed from multi_horizon_json; verify enum strings in your build.",
    }

    # High-confidence losses (long/short + medium/high conviction + negative pnl proxy)
    losses: list[dict[str, Any]] = []
    for r in rows:
        sig = (r["final_signal"] or "").lower()
        conv = (r["call_conviction"] or "").lower()
        pts = r["outcome_5c_pts"]
        if pts is None or sig not in ("long", "short"):
            continue
        pnl = _directional_pnl(sig, r["outcome_5c"], float(pts))
        if pnl is not None and pnl < 0 and conv in ("medium", "high"):
            losses.append(
                {
                    "final_signal": sig,
                    "conviction": conv,
                    "outcome_5c": r["outcome_5c"],
                    "pnl_proxy": pnl,
                }
            )
    hcl_gate = bucket_gate(len(losses), MIN_SAMPLES_STATISTICAL)
    out["high_confidence_losses"] = {
        "count": len(losses),
        "sample": losses[:50],
        "sample_gate": hcl_gate,
        "descriptive_only": not hcl_gate["sufficient_sample"],
        "note": "List is descriptive; do not infer rates or thresholds when descriptive_only is true.",
    }

    # Snapshots baselines (1m only — same contract as outcome join)
    snap_counts = snapshots_1m_labeled_counts(conn)
    snap = conn.execute(
        get_snapshot_sql("calibration/analyze_phase4.py:259"),
        (CANONICAL_TIMEFRAME,),
    ).fetchall()
    conn.close()

    # outcome_5c_pts is signed (forward_close - anchor_close); see horizon_outcomes producer.
    always_up: list[float] = []
    always_down: list[float] = []
    mr_pts: list[float] = []
    for r in snap:
        pts = r["outcome_5c_pts"]
        if pts is None:
            continue
        p = float(pts)
        oc = r["outcome_5c"]
        up_pnl = _directional_pnl("long", oc, p)
        dn_pnl = _directional_pnl("short", oc, p)
        if up_pnl is not None:
            always_up.append(up_pnl)
        if dn_pnl is not None:
            always_down.append(dn_pnl)
        vs = (r["vwap_side"] or "").strip().lower()
        if vs == "below":
            mr = _directional_pnl("long", oc, p)
        elif vs == "above":
            mr = _directional_pnl("short", oc, p)
        else:
            mr = None
        if mr is not None:
            mr_pts.append(mr)

    up_m, up_g = gated_mean(always_up, MIN_N_BASELINE_COMPARISON)
    dn_m, dn_g = gated_mean(always_down, MIN_N_BASELINE_COMPARISON)
    mr_m, mr_g = gated_mean(mr_pts, MIN_N_BASELINE_COMPARISON)

    log_pnls: list[float] = []
    for r in rows:
        pnl = _directional_pnl(r["final_signal"], r["outcome_5c"], float(r["outcome_5c_pts"]) if r["outcome_5c_pts"] is not None else None)
        if pnl is not None:
            log_pnls.append(float(pnl))
    log_m, log_g = gated_mean(log_pnls, MIN_N_BASELINE_COMPARISON)

    comp_status = "insufficient_sample"
    delta = None
    if (
        log_m is not None
        and up_m is not None
        and log_g.get("sufficient_sample")
        and up_g.get("sufficient_sample")
    ):
        comp_status = "ok"
        delta = round(log_m - up_m, 6)
    comparison = {
        "status": comp_status,
        "decision_log_mean_pnl_proxy": log_m,
        "decision_log_sample_gate": log_g,
        "baseline_always_up_mean_5c_pts": up_m,
        "baseline_always_up_gate": up_g,
        "delta_log_mean_minus_always_up_mean": delta,
        "note": "Cross-dataset comparison (log vs snapshots); use only when both gates are ok.",
    }

    out["baselines_from_snapshots"] = {
        "n_snapshots_used": len(snap),
        "always_up_mean_gate": up_g,
        "always_down_mean_gate": dn_g,
        "vwap_mr_proxy_gate": mr_g,
        "always_up_mean_5c_pts": up_m,
        "always_down_mean_5c_pts": dn_m,
        "vwap_side_mean_reversion_proxy_n": len(mr_pts),
        "vwap_side_mean_reversion_proxy_mean": mr_m,
        "decision_log_vs_baseline_comparison": comparison,
        "caveat": "Baselines are intentionally crude; compare to decision log on same sample when log is dense.",
        "provenance": provenance_dict(
            source_tables=["snapshots"],
            labeled_sample_count=len(snap),
            excluded_by_reason={
                "snapshots_1m_unlabeled_outcome_5c": snap_counts.get(
                    "snapshots_rows_excluded_unlabeled_1m", 0
                ),
                "snapshots_rows_non_1m_in_db_ignored": snap_counts.get(
                    "snapshots_rows_non_canonical_timeframe_in_db", 0
                ),
                "cap_excluded_over_200k_labeled": max(
                    0,
                    snap_counts.get("snapshots_rows_1m_labeled_outcome_5c", 0) - len(snap),
                ),
            },
        ),
        "snapshots_1m_contract": {
            "effective_timeframe": CANONICAL_TIMEFRAME,
            "fallback_guarantee": "snapshots WHERE timeframe='1m' only",
            **snap_counts,
        },
    }

    bl = out["baselines_from_snapshots"]
    bl["provenance"]["effective_dataset_note"] = (
        "snapshots 1m labeled (capped 200k); baselines are not matched to calibration_decision_log rows."
    )

    _phase4_attach_statistical_integrity(out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="calibration.analyze_phase4", write_capable=False)
    ensure_artifacts_dir()
    try:
        data = analyze(args.db)
    except CalibrationCanonicalViolationError as e:
        print(json.dumps({"error": str(e), "binary_pass": False}))
        return 2
    outp = Path(__file__).resolve().parent.parent / "models" / "calibration_runs" / f"phase4_analysis_{int(time.time())}.json"
    write_json_file_atomically(outp, data, indent=2)
    print(
        json.dumps(
            {
                "wrote": str(outp),
                "binary_pass": data.get("statistical_integrity", {}).get("binary_pass"),
            },
            indent=2,
        )
    )
    return 0 if data.get("statistical_integrity", {}).get("binary_pass") else 3


if __name__ == "__main__":
    sys.exit(main())
