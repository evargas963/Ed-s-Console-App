#!/usr/bin/env python3
"""
Adaptive shadow report — heuristic vs scored similarity (analysis only).

Does not change production decisions. Outputs adaptive_shadow_report_v1 JSON.

Example:
  python tools/adaptive_shadow_report.py --db data/ed_console.db --ticker SPY \\
    --zone pin_neutral --vwap-side above --nad 1.0 --nbd -1.0
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adaptive_similarity_engine import (  # noqa: E402
    ORDERING_PRESETS,
    compare_heuristic_to_shadow,
    run_baseline_control,
    run_feature_ablations,
    run_order_variant,
    run_weighted_selection,
    shadow_run_to_dict,
)
from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from db import DB_PATH, EdDB  # noqa: E402
from similarity_audit import merge_trace_with_shadow_extension  # noqa: E402
from timeframe_config import CANONICAL_TIMEFRAME  # noqa: E402


def _selected_ids(rows: list[dict]) -> list[Any]:
    return [r["snapshot_id"] for r in rows if r.get("snapshot_id") is not None]


def _feature_importance_rank(ablations: list[dict]) -> list[dict[str, Any]]:
    ranked = []
    for a in ablations:
        j = float(a["overlap_vs_full_weighted"].get("jaccard") or 0.0)
        ranked.append(
            {
                "feature": a["feature_removed"],
                "selection_divergence_1_minus_jaccard": round(1.0 - j, 6),
            }
        )
    ranked.sort(key=lambda x: -x["selection_divergence_1_minus_jaccard"])
    return ranked


def _recommendation_flags(
    weighted_viable: bool,
    ablations: list[dict],
    comp_hw: dict[str, Any],
) -> dict[str, Any]:
    redundant: list[str] = []
    core: list[str] = []
    for a in ablations:
        j = float(a["overlap_vs_full_weighted"].get("jaccard") or 0.0)
        if j >= 0.93:
            redundant.append(a["feature_removed"])
        if weighted_viable and not a["tier_stop_viable"]:
            core.append(a["feature_removed"])
    rec = comp_hw.get("overlap", {}).get("recall_vs_a")
    suboptimal = rec is not None and float(rec) < 0.25
    return {
        "feature_likely_redundant_high_jaccard_when_removed": sorted(set(redundant)),
        "feature_likely_core_tier_stop_lost_when_removed": sorted(set(core)),
        "ordering_likely_suboptimal_heuristic_vs_weighted_recall_low": suboptimal,
        "notes": (
            "Flags are heuristic cues for research — not production gates. "
            "Review overlap and labeled_counts in full JSON."
        ),
    }


def build_adaptive_shadow_report(
    db: EdDB,
    *,
    ticker: str,
    timeframe: str = CANONICAL_TIMEFRAME,
    zone: str,
    vwap_side: str,
    nearest_above_dist: float | None,
    nearest_below_dist: float | None,
    n_similar: int = 500,
    as_of_ts_utc: float | None = None,
    candidate_pool_cap: int = 5000,
) -> dict[str, Any]:
    ticker = (ticker or "").upper().strip()

    similar_h, trace = db.get_similar_setups(
        ticker=ticker,
        timeframe=timeframe,
        zone=zone,
        vwap_side=vwap_side,
        nearest_above_dist=nearest_above_dist,
        nearest_below_dist=nearest_below_dist,
        n_similar=n_similar,
        return_trace=True,
        as_of_ts_utc=as_of_ts_utc,
    )
    h_ids = _selected_ids(similar_h)
    h_fc = dict(trace.get("final_selected_labeled_counts") or trace.get("final_labeled_counts") or {})
    h_tv = bool(trace.get("final_tier_stop_viable", trace.get("final_empirically_viable")))

    shadow_baseline = run_baseline_control(
        db,
        ticker=ticker,
        timeframe=timeframe,
        zone=zone,
        vwap_side=vwap_side,
        nearest_above_dist=nearest_above_dist,
        nearest_below_dist=nearest_below_dist,
        n_similar=n_similar,
        as_of_ts_utc=as_of_ts_utc,
    )
    weighted = run_weighted_selection(
        db,
        ticker=ticker,
        timeframe=timeframe,
        zone=zone,
        vwap_side=vwap_side,
        nearest_above_dist=nearest_above_dist,
        nearest_below_dist=nearest_below_dist,
        n_similar=n_similar,
        as_of_ts_utc=as_of_ts_utc,
        variant="weighted_equal",
        candidate_pool_cap=candidate_pool_cap,
    )
    ablations = run_feature_ablations(
        db,
        ticker=ticker,
        timeframe=timeframe,
        zone=zone,
        vwap_side=vwap_side,
        nearest_above_dist=nearest_above_dist,
        nearest_below_dist=nearest_below_dist,
        n_similar=n_similar,
        as_of_ts_utc=as_of_ts_utc,
        baseline_run=weighted,
        candidate_pool_cap=candidate_pool_cap,
    )

    ordering_results: list[dict[str, Any]] = []
    for preset in sorted(ORDERING_PRESETS.keys()):
        run = run_order_variant(
            db,
            preset,
            ticker=ticker,
            timeframe=timeframe,
            zone=zone,
            vwap_side=vwap_side,
            nearest_above_dist=nearest_above_dist,
            nearest_below_dist=nearest_below_dist,
            n_similar=n_similar,
            as_of_ts_utc=as_of_ts_utc,
            candidate_pool_cap=candidate_pool_cap,
        )
        ordering_results.append(
            {
                "preset": preset,
                "relaxed_features": sorted(ORDERING_PRESETS[preset]),
                "summary": shadow_run_to_dict(run),
                "overlap_vs_heuristic": compare_heuristic_to_shadow(
                    h_ids,
                    run,
                    heuristic_tier_stop_viable=h_tv,
                    heuristic_labeled_counts=h_fc,
                )["overlap"],
            }
        )

    comp_heuristic_weighted = compare_heuristic_to_shadow(
        h_ids,
        weighted,
        heuristic_tier_stop_viable=h_tv,
        heuristic_labeled_counts=h_fc,
    )
    comp_heuristic_baseline_shadow = compare_heuristic_to_shadow(
        h_ids,
        shadow_baseline,
        heuristic_tier_stop_viable=h_tv,
        heuristic_labeled_counts=h_fc,
    )

    flags = _recommendation_flags(weighted.tier_stop_viable, ablations, comp_heuristic_weighted)

    shadow_ext_body = {
        "analysis_only": True,
        "heuristic_authority_unchanged": True,
        "comparisons": {
            "heuristic_vs_weighted_equal": comp_heuristic_weighted,
            "heuristic_vs_baseline_shadow_control": comp_heuristic_baseline_shadow,
        },
        "weighted_equal_summary": shadow_run_to_dict(weighted),
        "baseline_control_shadow_summary": shadow_run_to_dict(shadow_baseline),
        "feature_ablations": ablations,
        "feature_importance_rank": _feature_importance_rank(ablations),
        "ordering_experiments": ordering_results,
        "recommendation_flags": flags,
        "ordering_presets_available": sorted(ORDERING_PRESETS.keys()),
    }

    trace_augmented = merge_trace_with_shadow_extension(trace, shadow_ext_body)

    return {
        "schema": "adaptive_shadow_report_v1",
        "analysis_only": True,
        "query": {
            "ticker": ticker,
            "timeframe": timeframe,
            "zone": zone,
            "vwap_side": vwap_side,
            "nearest_above_dist": nearest_above_dist,
            "nearest_below_dist": nearest_below_dist,
            "n_similar": n_similar,
            "as_of_ts_utc": as_of_ts_utc,
            "candidate_pool_cap": candidate_pool_cap,
        },
        "heuristic_trace": trace,
        "heuristic_trace_with_shadow_extension": trace_augmented,
        "baseline_vs_adaptive": {
            "comparisons": shadow_ext_body["comparisons"],
            "feature_importance_rank": shadow_ext_body["feature_importance_rank"],
            "ordering_experiments": ordering_results,
            "score_distribution_weighted": weighted.score_distribution,
        },
        "recommendation_flags": flags,
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Adaptive shadow JSON report (non-authoritative)")
    p.add_argument("--db", type=Path, default=DB_PATH)
    p.add_argument("--ticker", required=True)
    p.add_argument("--timeframe", default=CANONICAL_TIMEFRAME)
    p.add_argument("--zone", default="pin_neutral")
    p.add_argument("--vwap-side", default="above", dest="vwap_side")
    p.add_argument("--nad", type=float, default=None)
    p.add_argument("--nbd", type=float, default=None)
    p.add_argument("--n-similar", type=int, default=500)
    p.add_argument("--as-of-ts-utc", type=float, default=None)
    p.add_argument("--candidate-pool-cap", type=int, default=5000)
    register_allow_noncanonical_flag(p)
    args = p.parse_args()
    require_canonical_db_target(args, tool_name="tools.adaptive_shadow_report", write_capable=False)

    db = EdDB(
        args.db,
        allow_noncanonical=bool(getattr(args, "allow_noncanonical_db", False)),
    )
    report = build_adaptive_shadow_report(
        db,
        ticker=args.ticker.upper(),
        timeframe=args.timeframe,
        zone=args.zone,
        vwap_side=args.vwap_side,
        nearest_above_dist=args.nad,
        nearest_below_dist=args.nbd,
        n_similar=args.n_similar,
        as_of_ts_utc=args.as_of_ts_utc,
        candidate_pool_cap=args.candidate_pool_cap,
    )
    json.dump(report, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
