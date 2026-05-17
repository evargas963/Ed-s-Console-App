#!/usr/bin/env python3
"""
Phase 3 — Empirical threshold tuning & confidence calibration.

Requires either:
  - populated calibration_decision_log with outcomes (run backfill_outcomes), or
  - falls back to snapshots-only structural/outcome stats (no predicted confidence).

Outputs JSON (+ optional CSV) under models/calibration_runs/
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sqlite3
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from arch_competition.atomic_io import write_json_file_atomically
from calibration.anchor_audit import snapshot_has_bar_anchor
from calibration.canonical_enforcement import (
    CalibrationCanonicalViolationError,
    CANONICAL_TIMEFRAME,
    enforce_calibration_decision_log_only_1m,
    enforce_snapshots_fallback_is_1m_only,
    provenance_dict,
)
from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.paths import DEFAULT_DB, ensure_artifacts_dir
from calibration.schema import ensure_calibration_schema
from calibration.trust import TRUSTED_PREDICATE_SQL
from calibration.statistical_integrity import (
    MIN_N_BRIER_AGGREGATE,
    MIN_N_CONFIDENCE_BUCKET,
    MIN_N_MODEL_BY_REGIME_BUCKET,
    MIN_N_PROBABILITY_BUCKET,
    MIN_N_REGIME_BUCKET,
    MIN_N_SNAPSHOT_FALLBACK_CONVICTION,
    MIN_N_THRESHOLD_GRID_CELL,
    bucket_gate,
    gated_mean,
    thresholds_dict,
    verify_phase3_no_numeric_leak,
)
from calibration.v2_a1_calibration import axis_reliability_bucket_value

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

_CANONICAL_PROB_KEYS = ("probability_up", "probability_down", "probability_flat")


def _brier_triplet(p_up: float, p_dn: float, p_fl: float, y: str) -> float:
    y = (y or "flat").strip().lower()
    o_up, o_dn, o_fl = 0.0, 0.0, 0.0
    if y == "up":
        o_up = 1.0
    elif y == "down":
        o_dn = 1.0
    else:
        o_fl = 1.0
    return (p_up - o_up) ** 2 + (p_dn - o_dn) ** 2 + (p_fl - o_fl) ** 2


def _load_json_col(s: str | None) -> dict[str, Any]:
    if not s:
        return {}
    try:
        obj = json.loads(s)
    except (json.JSONDecodeError, ValueError) as e:
        log.warning("analyze_phase3: could not parse JSON column: %s", e)
        return {}
    if not isinstance(obj, dict):
        log.warning("analyze_phase3: JSON column root is not an object")
        return {}
    return obj


def _canonical_prob_triplet(canonical_json: str | None) -> tuple[float, float, float] | None:
    if not (canonical_json or "").strip():
        return None
    d = _load_json_col(canonical_json)
    if not d or not all(k in d for k in _CANONICAL_PROB_KEYS):
        return None
    try:
        vals = tuple(float(d[k]) for k in _CANONICAL_PROB_KEYS)
    except (TypeError, ValueError):
        return None
    if any(math.isnan(v) or math.isinf(v) for v in vals):
        return None
    return vals


def _confidence_bucket(label: str | None) -> str:
    x = (label or "low").strip().lower()
    if x in ("high", "medium", "low"):
        return x
    return "low"


def _snapshot_fallback(conn: sqlite3.Connection) -> dict[str, Any]:
    """When calibration_decision_log is empty: coarse stats from snapshots (1m, labeled)."""
    gate = enforce_snapshots_fallback_is_1m_only(conn)
    unlabeled = int(
        conn.execute(
            get_snapshot_sql("calibration/analyze_phase3.py:100"),
            (CANONICAL_TIMEFRAME,),
        ).fetchone()["n"]
    )
    rows = conn.execute(
        get_snapshot_sql("calibration/analyze_phase3.py:108"),
        (CANONICAL_TIMEFRAME,),
    ).fetchall()
    by_conv: dict[str, list[tuple[str, str, float | None]]] = defaultdict(list)
    for r in rows:
        sig = (r["combined_signal"] or "wait").strip().lower()
        conv = (r["combined_conviction"] or "low").strip().lower()
        oc = (r["outcome_5c"] or "").strip().lower()
        pts = r["outcome_5c_pts"]
        by_conv[conv].append((sig, oc, float(pts) if pts is not None else None))

    out: dict[str, Any] = {
        "snapshot_rows_labeled": len(rows),
        "by_combined_conviction": {},
        "provenance": provenance_dict(
            source_tables=["snapshots"],
            labeled_sample_count=len(rows),
            excluded_by_reason={
                "snapshots_1m_unlabeled_outcome_5c": unlabeled,
                "snapshots_non_1m_rows_ignored_by_contract": int(
                    gate.get("snapshots_rows_non_canonical_timeframe_in_db", 0)
                ),
            },
        ),
        "snapshots_1m_contract": gate,
    }
    for conv, lst in sorted(by_conv.items()):
        pnls: list[float] = []
        n_long = n_short = n_wait = 0
        for sig, oc, pts in lst:
            if sig == "long":
                n_long += 1
            elif sig == "short":
                n_short += 1
            else:
                n_wait += 1
            if pts is None:
                continue
            if sig == "long":
                if oc == "up":
                    pnls.append(abs(pts))
                elif oc == "down":
                    pnls.append(-abs(pts))
                else:
                    pnls.append(0.0)
            elif sig == "short":
                if oc == "down":
                    pnls.append(abs(pts))
                elif oc == "up":
                    pnls.append(-abs(pts))
                else:
                    pnls.append(0.0)
        mean_pnl, pnl_gate = gated_mean(pnls, MIN_N_SNAPSHOT_FALLBACK_CONVICTION)
        out["by_combined_conviction"][conv] = {
            "n_signals": len(lst),
            "n_long": n_long,
            "n_short": n_short,
            "n_wait": n_wait,
            "n_pnl_computed": len(pnls),
            "mean_pnl_proxy_5c": mean_pnl,
            "sample_gate": pnl_gate,
        }
    out["caveat"] = (
        "Fallback uses snapshots.combined_* — not identical to full fusion calibration row; "
        "use calibration log for primary institutional analysis once populated."
    )
    out["provenance"]["effective_dataset_note"] = (
        "snapshots 1m labeled rows only; combined_signal/conviction proxy — not calibration_decision_log."
    )
    return out


def _phase3_attach_statistical_integrity(out: dict[str, Any]) -> None:
    """Counts insufficient buckets, exposes provenance, defensive binary_pass."""
    prov = out.get("provenance") or {}
    insufficient: dict[str, int] = {
        "reliability_confidence_buckets": 0,
        "regime_buckets": 0,
        "model_by_regime_buckets": 0,
        "threshold_grid_cells": 0,
        "probability_buckets": 0,
        "brier_aggregate": 0,
    }

    def _inc(g: dict[str, Any] | None, key: str) -> None:
        if g and not g.get("sufficient_sample"):
            insufficient[key] = insufficient.get(key, 0) + 1

    for row in out.get("reliability_by_canonical_confidence", {}).values():
        _inc(row.get("sample_gate"), "reliability_confidence_buckets")
    for row in out.get("regime_buckets", {}).values():
        _inc(row.get("sample_gate"), "regime_buckets")
    for row in out.get("model_by_regime_buckets", {}).values():
        _inc(row.get("sample_gate"), "model_by_regime_buckets")
    for cell in (out.get("threshold_grid") or {}).get("thresholds_tried") or []:
        _inc(cell.get("sample_gate"), "threshold_grid_cells")
    for row in out.get("probability_bucket_expectancy_5c_pts", {}).values():
        _inc(row.get("sample_gate"), "probability_buckets")
    _inc(out.get("brier_sample_gate"), "brier_aggregate")

    sf = out.get("snapshots_fallback") or {}
    insufficient["snapshot_fallback_by_conviction"] = 0
    for row in sf.get("by_combined_conviction", {}).values():
        _inc(row.get("sample_gate"), "snapshot_fallback_by_conviction")

    leak_ok = verify_phase3_no_numeric_leak(out)
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
        out["notes"].append("statistical_integrity: defensive leak check failed — inspect sample_gate fields.")


def analyze(db_path: Path) -> dict[str, Any]:
    out: dict[str, Any] = {
        "meta": {"db": str(db_path), "ts": time.time()},
        "provenance": None,
        "calibration_rows": 0,
        "calibration_with_outcome": 0,
        "reliability_by_canonical_confidence": {},
        "brier_canonical_vs_outcome_5c": None,
        "brier_sample_gate": None,
        "regime_buckets": {},
        "model_by_regime_buckets": {},
        "threshold_grid": {},
        "probability_bucket_expectancy_5c_pts": {},
        "notes": [],
    }

    if not db_path.is_file():
        out["error"] = "db missing"
        out["statistical_integrity"] = {
            "binary_pass": False,
            "error": "db missing",
        }
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
        SELECT * FROM calibration_decision_log
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

    out["calibration_rows"] = len(rows)
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
        "labeled_sample_count = trusted calibration_decision_log rows with outcome_5c after BAR_ANCHOR_V1; "
        "canonical_timeframe 1m; calibration_trust='trusted' only."
    )
    if not rows:
        out["notes"].append(
            "No calibration_decision_log rows with outcome_5c — enable ED_CALIBRATION_LOG, "
            "run live/replay, then calibration.backfill_outcomes."
        )
        try:
            out["snapshots_fallback"] = _snapshot_fallback(conn)
        except Exception as e:
            out["snapshots_fallback_error"] = str(e)
        conn.close()
        _phase3_attach_statistical_integrity(out)
        return out

    # Reliability: map canonical confidence bucket -> list of (pred dominant correct?)
    bucket_hits: dict[str, list[int]] = defaultdict(list)
    bucket_pred: dict[str, list[float]] = defaultdict(list)
    brier_terms: list[float] = []

    for r in rows:
        trip = _canonical_prob_triplet(r["canonical_json"])
        if trip is None:
            continue
        p_up, p_dn, p_fl = trip
        dom = "up" if p_up >= p_dn and p_up >= p_fl else ("down" if p_dn >= p_fl else "flat")
        y5 = (r["outcome_5c"] or "").strip().lower()
        hit = 1 if dom == y5 else 0
        cj = _load_json_col(r["canonical_json"])
        bkt = _confidence_bucket(cj.get("confidence"))
        bucket_hits[bkt].append(hit)
        bucket_pred[bkt].append(max(p_up, p_dn, p_fl))
        brier_terms.append(_brier_triplet(p_up, p_dn, p_fl, y5))

    out["calibration_with_outcome"] = sum(len(v) for v in bucket_hits.values())

    rel: dict[str, Any] = {}
    for bkt, hits in sorted(bucket_hits.items()):
        preds = bucket_pred[bkt]
        gate = bucket_gate(len(hits), MIN_N_CONFIDENCE_BUCKET)
        if gate["sufficient_sample"] and hits:
            rate: float | None = round(sum(hits) / len(hits), 6)
            mean_pred: float | None = round(statistics.mean([float(x) for x in preds]), 6)
        else:
            rate, mean_pred = None, None
        rel[bkt] = {
            "n": len(hits),
            "sample_gate": gate,
            "empirical_hit_rate": rate,
            "mean_max_class_probability": mean_pred,
        }
    out["reliability_by_canonical_confidence"] = rel

    brier_gate = bucket_gate(len(brier_terms), MIN_N_BRIER_AGGREGATE)
    out["brier_sample_gate"] = brier_gate
    if brier_gate["sufficient_sample"] and brier_terms:
        out["brier_canonical_vs_outcome_5c"] = round(sum(brier_terms) / len(brier_terms), 6)
        out["brier_n"] = len(brier_terms)
    else:
        out["brier_canonical_vs_outcome_5c"] = None
        out["brier_n"] = len(brier_terms)

    # Regime × outcome pts
    reg_pts: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        rp = r["regime_primary"]
        pts = r["outcome_5c_pts"]
        if rp and pts is not None:
            reg_pts[rp].append(float(pts))
    regime_out: dict[str, Any] = {}
    for k, v in sorted(reg_pts.items(), key=lambda x: -len(x[1])):
        m, g = gated_mean(v, MIN_N_REGIME_BUCKET)
        regime_out[k] = {
            "n": len(v),
            "sample_gate": g,
            "mean_5c_pts": m,
            "win_rate_up_or_down_aligned": None,
        }
    out["regime_buckets"] = regime_out

    # Regime × vol_regime (model stack context buckets; fail-closed per cell)
    mbr_pts: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        rp = axis_reliability_bucket_value(r["regime_primary"])
        vr = axis_reliability_bucket_value(r["vol_regime"])
        pts = r["outcome_5c_pts"]
        if pts is not None:
            key = f"{rp}|{vr}"
            mbr_pts[key].append(float(pts))
    mbr_out: dict[str, Any] = {}
    for k, v in sorted(mbr_pts.items(), key=lambda x: -len(x[1])):
        m, g = gated_mean(v, MIN_N_MODEL_BY_REGIME_BUCKET)
        mbr_out[k] = {
            "n": len(v),
            "regime_primary": k.split("|", 1)[0],
            "vol_regime": k.split("|", 1)[1] if "|" in k else "unknown",
            "sample_gate": g,
            "mean_5c_pts": m,
        }
    out["model_by_regime_buckets"] = mbr_out

    # Threshold grid on fusion confidence score (if present) — no "best" pick; descriptive only when n OK
    grid: dict[str, Any] = {"thresholds_tried": [], "samples": 0, "note": "Cells are gated; do not optimize on insufficient n."}
    thresh_samples: list[tuple[float, float]] = []  # (fusion_score, outcome_pts)
    for r in rows:
        fj = _load_json_col(r["fusion_json"])
        score = fj.get("fusion_confidence_score")
        pts = r["outcome_5c_pts"]
        if score is not None and pts is not None:
            try:
                thresh_samples.append((float(score), float(pts)))
            except (TypeError, ValueError):
                pass
    grid["samples"] = len(thresh_samples)
    if thresh_samples:
        for t in [0.35, 0.45, 0.55, 0.65]:
            sub = [p for s, p in thresh_samples if s >= t]
            m, g = gated_mean(sub, MIN_N_THRESHOLD_GRID_CELL)
            grid["thresholds_tried"].append(
                {
                    "min_fusion_confidence_score": t,
                    "n": len(sub),
                    "sample_gate": g,
                    "mean_5c_pts": m,
                }
            )
    out["threshold_grid"] = grid

    # Probability bucket → expectancy (canonical max prob)
    pbuckets: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        trip = _canonical_prob_triplet(r["canonical_json"])
        pts = r["outcome_5c_pts"]
        if trip is None or pts is None:
            continue
        mx = max(trip)
        slot = f"{int(mx * 10) / 10:.1f}-{int(mx * 10) / 10 + 0.1:.1f}"
        pbuckets[slot].append(float(pts))
    prob_out: dict[str, Any] = {}
    for k, v in sorted(pbuckets.items()):
        m, g = gated_mean(v, MIN_N_PROBABILITY_BUCKET)
        prob_out[k] = {"n": len(v), "sample_gate": g, "mean_pts": m}
    out["probability_bucket_expectancy_5c_pts"] = prob_out

    conn.close()
    _phase3_attach_statistical_integrity(out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="calibration.analyze_phase3", write_capable=False)
    ensure_artifacts_dir()
    try:
        data = analyze(args.db)
    except CalibrationCanonicalViolationError as e:
        print(json.dumps({"error": str(e), "binary_pass": False}))
        return 2
    outp = Path(__file__).resolve().parent.parent / "models" / "calibration_runs" / f"phase3_analysis_{int(time.time())}.json"
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
