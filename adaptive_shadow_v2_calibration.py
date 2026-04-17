"""
Adaptive Shadow v2 — multi-anchor calibration and reporting (shadow only).

Uses Issue 19 tier-1 structural pool + Tier 3 context scoring from adaptive_similarity_engine.
Does not call into production widening logic for the adaptive cohort (heuristic baseline still widens).
"""
from __future__ import annotations

import json
import logging
import statistics
from pathlib import Path
from typing import Any, Optional

from adaptive_similarity_engine import (
    ADAPTIVE_SHADOW_V2_TIER3_COLUMNS,
    TIER3_WEIGHT_RANGES_V1,
    calibration_weight_profiles_v1,
    compare_heuristic_to_shadow,
    default_tier3_mid_weights_v1,
    run_adaptive_shadow_v2,
    run_baseline_control,
    _overlap_metrics,
)
from similarity_audit import normalize_anchor_distances_for_issue19_sql
from similarity_feature_search import resolve_overlay_for_anchor

from instrument_identity import ticker_storage_key
from timeframe_config import CANONICAL_TIMEFRAME

SCHEMA_CALIBRATION_V1 = "adaptive_shadow_v2_calibration_v1"
_log_anc = logging.getLogger(__name__)
DEFAULT_ANCHORS_JSON = Path(__file__).resolve().parent / "data" / "survivorship_multi_anchor_20.json"


def _optional_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    return float(x)


def load_survivorship_anchors_v1(path: Optional[Path] = None) -> list[dict[str, Any]]:
    p = path or DEFAULT_ANCHORS_JSON
    data = json.loads(Path(p).read_text(encoding="utf-8"))
    raw = data.get("anchors_used") or data.get("anchors") or []
    out: list[dict[str, Any]] = []
    for a in raw:
        tid = ticker_storage_key(a.get("ticker"))
        nad, nbd = normalize_anchor_distances_for_issue19_sql(
            _optional_float(a.get("nearest_above_dist")),
            _optional_float(a.get("nearest_below_dist")),
        )
        raw_tf = (a.get("timeframe") or "").strip() or None
        if raw_tf and raw_tf != CANONICAL_TIMEFRAME:
            _log_anc.warning(
                "load_survivorship_anchors_v1: anchor %s had timeframe=%r — overriding to canonical %r "
                "(Issue 19 tier SQL is 1m-only)",
                a.get("anchor_id") or tid,
                raw_tf,
                CANONICAL_TIMEFRAME,
            )
        out.append(
            {
                "anchor_id": a.get("anchor_id") or f"{tid}__{a.get('zone')}__{a.get('vwap_side')}",
                "ticker": tid.upper(),
                "timeframe": CANONICAL_TIMEFRAME,
                "zone": a.get("zone"),
                "vwap_side": a.get("vwap_side"),
                "nearest_above_dist": nad,
                "nearest_below_dist": nbd,
            }
        )
    return out


def _tier3_overlay_status(db: Any, anchor: dict[str, Any]) -> dict[str, Any]:
    r = resolve_overlay_for_anchor(
        db,
        ticker=anchor["ticker"],
        timeframe=anchor["timeframe"],
        zone=anchor["zone"],
        vwap_side=anchor["vwap_side"],
        nearest_above_dist=anchor.get("nearest_above_dist"),
        nearest_below_dist=anchor.get("nearest_below_dist"),
    )
    ov = r.get("overlay") or {}
    keys_ok = [c for c in ADAPTIVE_SHADOW_V2_TIER3_COLUMNS if c in ov and ov[c] is not None and str(ov[c]).strip() != ""]
    tries = r.get("resolution", {}).get("tries") or []
    overlay_found = any(bool(t.get("matched")) for t in tries)
    return {
        "overlay_found": overlay_found,
        "tier3_keys_present": keys_ok,
        "tier3_complete": len(keys_ok) == len(ADAPTIVE_SHADOW_V2_TIER3_COLUMNS),
        "resolution": r.get("resolution"),
    }


def report_tier1_pool_coverage_v1(
    db: Any,
    anchors: list[dict[str, Any]],
    *,
    structural_pool_cap: int = 8000,
    as_of_ts_utc: Optional[float] = None,
) -> dict[str, Any]:
    """Issue 19 tier-1 pool size per anchor (same SQL as adaptive v2 structural fetch)."""
    from adaptive_similarity_engine import _fetch_issue19_tier1_candidate_rows

    per: list[dict[str, Any]] = []
    for a in anchors:
        n = len(
            _fetch_issue19_tier1_candidate_rows(
                db,
                ticker=a["ticker"],
                timeframe=a["timeframe"],
                zone=a["zone"],
                vwap_side=a["vwap_side"],
                nearest_above_dist=a.get("nearest_above_dist"),
                nearest_below_dist=a.get("nearest_below_dist"),
                as_of_ts_utc=as_of_ts_utc,
                structural_pool_cap=structural_pool_cap,
            )
        )
        per.append({"anchor_id": a.get("anchor_id"), "tier1_pool_size": n})
    nonempty = sum(1 for x in per if x["tier1_pool_size"] > 0)
    sizes = [x["tier1_pool_size"] for x in per]
    return {
        "schema": "tier1_pool_coverage_report_v1",
        "anchors_total": len(anchors),
        "nonempty_tier1_pool_count": nonempty,
        "empty_tier1_pool_count": len(anchors) - nonempty,
        "mean_pool_size": round(statistics.mean(sizes), 6) if sizes else 0.0,
        "anchors_with_zero_matches": [x["anchor_id"] for x in per if x["tier1_pool_size"] == 0],
        "per_anchor": per,
    }


def run_calibration_v1(
    db: Any,
    *,
    anchors: list[dict[str, Any]],
    n_similar: int = 500,
    structural_pool_cap: int = 8000,
    weight_profiles: Optional[list[dict[str, Any]]] = None,
    include_feature_ablation: bool = True,
) -> dict[str, Any]:
    """
    For each weight profile × anchor: adaptive v2 vs heuristic baseline.
    Aggregates Jaccard, viability, pool sizes, score stats.
    """
    profiles = weight_profiles or calibration_weight_profiles_v1()
    tier1_cov = report_tier1_pool_coverage_v1(db, anchors, structural_pool_cap=structural_pool_cap)
    per_anchor_baseline: list[dict[str, Any]] = []
    for anchor in anchors:
        h = run_baseline_control(
            db,
            ticker=anchor["ticker"],
            timeframe=anchor["timeframe"],
            zone=anchor["zone"],
            vwap_side=anchor["vwap_side"],
            nearest_above_dist=anchor.get("nearest_above_dist"),
            nearest_below_dist=anchor.get("nearest_below_dist"),
            n_similar=n_similar,
        )
        ovs = _tier3_overlay_status(db, anchor)
        per_anchor_baseline.append(
            {
                "anchor_id": anchor["anchor_id"],
                "heuristic_row_count": len(h.selected_row_ids),
                "heuristic_tier_stop_viable": h.tier_stop_viable,
                "heuristic_labeled_counts": dict(h.labeled_counts),
                "heuristic_ids": h.selected_row_ids,
                "tier3_overlay": ovs,
            }
        )

    per_config: list[dict[str, Any]] = []
    for prof in profiles:
        cfg_id = prof["config_id"]
        tw = prof["tier3_weights"]
        jacs: list[float] = []
        viab: list[int] = []
        pool_sizes: list[int] = []
        final_score_means: list[float] = []
        final_score_stds: list[float] = []
        comparisons: list[dict[str, Any]] = []

        for anchor, bline in zip(anchors, per_anchor_baseline):
            adapt = run_adaptive_shadow_v2(
                db,
                ticker=anchor["ticker"],
                timeframe=anchor["timeframe"],
                zone=anchor["zone"],
                vwap_side=anchor["vwap_side"],
                nearest_above_dist=anchor.get("nearest_above_dist"),
                nearest_below_dist=anchor.get("nearest_below_dist"),
                n_similar=n_similar,
                structural_pool_cap=structural_pool_cap,
                tier3_weights=tw,
            )
            hb = set(bline["heuristic_ids"])
            sb = set(adapt.selected_row_ids)
            om = _overlap_metrics(hb, sb)
            jacs.append(float(om["jaccard"]))
            viab.append(1 if adapt.tier_stop_viable else 0)
            pool_sizes.append(adapt.candidate_pool_size)
            dist = adapt.score_distribution
            if dist.get("mean") is not None:
                final_score_means.append(float(dist["mean"]))
            if dist.get("std") is not None:
                final_score_stds.append(float(dist["std"]))
            comparisons.append(
                {
                    "anchor_id": anchor["anchor_id"],
                    "overlap": om,
                    "adaptive_row_count": len(adapt.selected_row_ids),
                    "structural_pool_size": adapt.candidate_pool_size,
                    "adaptive_tier_stop_viable": adapt.tier_stop_viable,
                    "compare": compare_heuristic_to_shadow(
                        bline["heuristic_ids"],
                        adapt,
                        heuristic_tier_stop_viable=bline["heuristic_tier_stop_viable"],
                        heuristic_labeled_counts=bline["heuristic_labeled_counts"],
                    ),
                }
            )

        def _mean(xs: list[float]) -> Optional[float]:
            return round(statistics.mean(xs), 6) if xs else None

        def _pstdev(xs: list[float]) -> Optional[float]:
            return round(statistics.pstdev(xs), 6) if len(xs) > 1 else (0.0 if xs else None)

        per_config.append(
            {
                "config_id": cfg_id,
                "tier3_weights": tw,
                "aggregate": {
                    "mean_jaccard_vs_heuristic": _mean(jacs),
                    "stdev_jaccard_across_anchors": _pstdev(jacs),
                    "fraction_tier_stop_viable": round(sum(viab) / len(viab), 6) if viab else None,
                    "mean_structural_pool_size": _mean([float(x) for x in pool_sizes]),
                    "mean_final_score_mean_top_n": _mean(final_score_means),
                    "mean_final_score_std_top_n": _mean(final_score_stds),
                },
                "per_anchor": comparisons,
            }
        )

    ranked = sorted(
        per_config,
        key=lambda x: (
            -(x["aggregate"].get("mean_jaccard_vs_heuristic") or 0.0),
            -(x["aggregate"].get("fraction_tier_stop_viable") or 0.0),
            x["aggregate"].get("stdev_jaccard_across_anchors") or 0.0,
        ),
    )

    ablation: list[dict[str, Any]] = []
    if include_feature_ablation and anchors:
        mid = default_tier3_mid_weights_v1()
        base_prof = next((p for p in per_config if p["config_id"] == "mid_baseline"), None)
        if base_prof is None:
            base_j = [0.0]
        else:
            base_j = [
                float(x["overlap"]["jaccard"])
                for x in base_prof["per_anchor"]
            ]
        base_mean_j = statistics.mean(base_j) if base_j else 0.0
        for col in ADAPTIVE_SHADOW_V2_TIER3_COLUMNS:
            w_zero = dict(mid)
            w_zero[col] = 0.0
            deltas: list[float] = []
            for anchor, bline in zip(anchors, per_anchor_baseline):
                adapt = run_adaptive_shadow_v2(
                    db,
                    ticker=anchor["ticker"],
                    timeframe=anchor["timeframe"],
                    zone=anchor["zone"],
                    vwap_side=anchor["vwap_side"],
                    nearest_above_dist=anchor.get("nearest_above_dist"),
                    nearest_below_dist=anchor.get("nearest_below_dist"),
                    n_similar=n_similar,
                    structural_pool_cap=structural_pool_cap,
                    tier3_weights=w_zero,
                )
                om = _overlap_metrics(set(bline["heuristic_ids"]), set(adapt.selected_row_ids))
                deltas.append(float(om["jaccard"]))
            ablation.append(
                {
                    "zeroed_feature": col,
                    "mean_jaccard_vs_heuristic": round(statistics.mean(deltas), 6) if deltas else None,
                    "mean_delta_jaccard_vs_mid_baseline": round(statistics.mean(deltas) - base_mean_j, 6) if deltas else None,
                }
            )

    best = ranked[0] if ranked else None
    stable_window = _recommend_weight_ranges_from_results(ranked)

    pool_diag: dict[str, Any] = {"empty_tier1_pool_count": 0, "nonempty_tier1_pool_count": 0, "note": ""}
    if ranked and ranked[0].get("per_anchor"):
        pa0 = ranked[0]["per_anchor"]
        empties = [x for x in pa0 if int(x.get("structural_pool_size") or 0) == 0]
        pool_diag["empty_tier1_pool_count"] = len(empties)
        pool_diag["nonempty_tier1_pool_count"] = len(pa0) - len(empties)
        pool_diag["note"] = (
            "Issue 19 tier-1 SQL uses BETWEEN(bucket_lo,bucket_hi) on the **raw** snapshot columns. "
            "Anchors are normalized to non-negative magnitudes (abs) so anchor-side buckets match SQL intervals. "
            "If the DB still stores nearest_below_dist as negative (common), many rows fall **outside** the "
            "non-negative BETWEEN range and tier-1 pools stay empty until row storage or SQL is aligned. "
            "Also verify anchor zones exist in the DB (e.g. pin_neutral may have zero rows for some tickers)."
        )

    ranking_valid = bool(
        anchors
        and pool_diag["nonempty_tier1_pool_count"] >= max(1, int(0.5 * len(anchors)))
    )

    return {
        "schema": SCHEMA_CALIBRATION_V1,
        "weight_ranges_reference": {k: list(v) for k, v in TIER3_WEIGHT_RANGES_V1.items()},
        "n_anchors": len(anchors),
        "n_configs": len(profiles),
        "tier1_structural_pool_diagnostics": pool_diag,
        "tier1_pool_coverage": tier1_cov,
        "weight_ranking_valid": ranking_valid,
        "weight_ranking_invalid_note": (
            None
            if ranking_valid
            else "Mean Jaccard can be inflated when both heuristic and adaptive return empty sets for the same anchor (Jaccard=1 by convention). Fix anchor distances vs DB column sign/range before trusting weight ranks."
        ),
        "per_weight_configuration": ranked,
        "ranking_note": "Primary sort: mean Jaccard vs heuristic DESC, then viable fraction DESC, then stdev Jaccard ASC",
        "best_configuration": best,
        "recommended_weight_ranges_observed_stable": stable_window,
        "feature_ablation_vs_mid_baseline_jaccard": ablation,
        "confidence_note": (
            "MEDIUM if all anchors have tier1 pool > 0 and mean_jaccard interpretable; LOW if many empty tier1 pools."
        ),
    }


def _recommend_weight_ranges_from_results(
    ranked: list[dict[str, Any]],
    top_k: int = 5,
) -> dict[str, Any]:
    """Union of tier3_weights from top_k configurations — conservative stable band report."""
    if not ranked:
        return {"bands": {}, "note": "no results"}
    tops = ranked[: min(top_k, len(ranked))]
    cols = list(ADAPTIVE_SHADOW_V2_TIER3_COLUMNS)
    bands: dict[str, dict[str, float]] = {}
    for c in cols:
        vals = [float(p["tier3_weights"][c]) for p in tops]
        bands[c] = {"lo": min(vals), "hi": max(vals), "span": max(vals) - min(vals)}
    return {"top_k": len(tops), "bands": bands, "method": "min_max_union_of_top_ranked_configs"}


def emit_calibration_json(
    db: Any,
    out_path: Path,
    *,
    anchors_path: Optional[Path] = None,
    **kwargs: Any,
) -> dict[str, Any]:
    anchors = load_survivorship_anchors_v1(anchors_path)
    report = run_calibration_v1(db, anchors=anchors, **kwargs)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report
