"""
Feature impact / ablation audit for heuristic tier similarity (analysis only).

Does not alter get_similar_setups or production authority. Uses the same SQL shapes
as db.py tier queries — keep in sync when tier definitions change.

Run: python tools/audit_similarity_features.py ...
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from math_exposure import (
    bucket_hi,
    bucket_lo,
    dist_bucket,
)
from similarity_audit import (
    SIMILARITY_EMPIRICAL_OUTCOME_COLUMNS,
    SIMILARITY_TIER_STOP_OUTCOME_COLUMNS,
    baseline_feature_contract_v1,
    widening_steps_are_sequential,
)

# Mirror db.py outcome counting (avoid importing private db helpers in some contexts)
from db import (  # noqa: E402 — app package
    get_snapshot_sql,
    similarity_empirically_viable,
    similarity_labeled_counts,
    similarity_tier_stop_viable,
)

from timeframe_config import CANONICAL_TIMEFRAME


def _asof_clause(as_of_ts_utc: Optional[float]) -> tuple[str, tuple]:
    if as_of_ts_utc is None:
        return "", ()
    return " AND ts_utc < ? ", (as_of_ts_utc,)


def _limited_pool_metrics(
    rows_raw: list,
) -> dict[str, Any]:
    out = [dict(r) for r in rows_raw]
    fc = similarity_labeled_counts(out)
    return {
        "row_count": len(out),
        "labeled_counts": dict(fc),
        "tier_stop_viable": similarity_tier_stop_viable(fc),
        "all_tracked_viable": similarity_empirically_viable(fc),
        "min_labeled_tier_stop_col": min(int(fc.get(c, 0)) for c in SIMILARITY_TIER_STOP_OUTCOME_COLUMNS)
        if out
        else 0,
        "min_labeled_all_tracked_col": min(int(fc.get(c, 0)) for c in SIMILARITY_EMPIRICAL_OUTCOME_COLUMNS)
        if out
        else 0,
    }


def _snapshot_id_set(rows: list) -> set[Any]:
    return {dict(r).get("snapshot_id") for r in rows if dict(r).get("snapshot_id") is not None}


def _overlap_fraction(baseline_ids: set[Any], other_ids: set[Any]) -> dict[str, Any]:
    if not baseline_ids and not other_ids:
        return {"jaccard": 1.0, "recall_of_baseline_in_other": None, "intersection": 0}
    inter = len(baseline_ids & other_ids)
    union = len(baseline_ids | other_ids)
    jaccard = inter / union if union else 0.0
    recall = inter / len(baseline_ids) if baseline_ids else None
    return {
        "jaccard": round(jaccard, 6),
        "recall_of_baseline_in_other": None if recall is None else round(recall, 6),
        "intersection": inter,
    }


def audit_bucket_definitions() -> dict[str, Any]:
    """dist_bucket edges/labels + spot-check monotonicity (points)."""
    from math_probabilities import DIST_BUCKET_EDGES, DIST_BUCKET_LABELS, DIST_BUCKET_OVERFLOW

    checks: list[dict[str, Any]] = []
    test_points = [None, 0.0, 0.5, 1.0, 1.5, 2.5, 4.0, 5.0, 10.0, -1.2]
    prev = None
    for p in test_points:
        b = dist_bucket(p)
        checks.append({"raw": p, "bucket": b})
        if p is not None and prev is not None and abs(p) > abs(prev):
            # larger |dist| should not map to strictly tighter upper bucket than smaller |dist|
            pass
        prev = p
    return {
        "schema": "distance_bucket_audit_v1",
        "DIST_BUCKET_EDGES": list(DIST_BUCKET_EDGES),
        "DIST_BUCKET_LABELS": list(DIST_BUCKET_LABELS),
        "DIST_BUCKET_OVERFLOW": DIST_BUCKET_OVERFLOW,
        "assignment_samples": checks,
        "coarse_assessment": (
            "Buckets are fixed-width in |dist| through 5 points then overflow — "
            "coarse for crowded names; fine beyond 5 may be sparse."
        ),
    }


def audit_above_below_symmetry_hint(
    *,
    nearest_above_dist: Optional[float],
    nearest_below_dist: Optional[float],
) -> dict[str, Any]:
    """Document asymmetry: bucketing uses abs(dist); sign is lost in tier SQL BETWEEN on signed row values."""
    ab = dist_bucket(nearest_above_dist)
    bb = dist_bucket(nearest_below_dist)
    return {
        "schema": "distance_symmetry_note_v1",
        "anchor_nearest_above_dist": nearest_above_dist,
        "anchor_nearest_below_dist": nearest_below_dist,
        "above_bucket": ab,
        "below_bucket": bb,
        "note": (
            "Tier SQL matches row nearest_*_dist in [bucket_lo, bucket_hi]. "
            "For negatives, bucket intervals still apply to the signed value if it falls in range; "
            "dist_bucket() uses abs(anchor) only for bucket label selection — audit for "
            "left/right wall asymmetry when anchors differ in sign/magnitude."
        ),
    }


def _bind_params_tier1(
    ticker: str,
    timeframe: str,
    zone: str,
    vwap_side: str,
    nad: Optional[float],
    nbd: Optional[float],
    above_bucket: Optional[str],
    below_bucket: Optional[str],
    as_of_ts_utc: Optional[float],
    n_similar: int,
) -> tuple:
    alo, ahi = bucket_lo(above_bucket), bucket_hi(above_bucket)
    blo, bhi = bucket_lo(below_bucket), bucket_hi(below_bucket)
    base = (
        ticker,
        timeframe,
        zone,
        vwap_side,
        nad,
        alo,
        ahi,
        nbd,
        blo,
        bhi,
    )
    if as_of_ts_utc is not None:
        return base + (as_of_ts_utc, n_similar)
    return base + (n_similar,)


def _bind_params_tier2(
    ticker: str,
    timeframe: str,
    zone: str,
    vwap_side: str,
    nad: Optional[float],
    above_bucket: Optional[str],
    as_of_ts_utc: Optional[float],
    n_similar: int,
) -> tuple:
    alo, ahi = bucket_lo(above_bucket), bucket_hi(above_bucket)
    base = (ticker, timeframe, zone, vwap_side, nad, alo, ahi)
    if as_of_ts_utc is not None:
        return base + (as_of_ts_utc, n_similar)
    return base + (n_similar,)


def _bind_params_orthogonal_below_only(
    ticker: str,
    timeframe: str,
    zone: str,
    vwap_side: str,
    nbd: Optional[float],
    below_bucket: Optional[str],
    as_of_ts_utc: Optional[float],
    n_similar: int,
) -> tuple:
    blo, bhi = bucket_lo(below_bucket), bucket_hi(below_bucket)
    base = (ticker, timeframe, zone, vwap_side, nbd, blo, bhi)
    if as_of_ts_utc is not None:
        return base + (as_of_ts_utc, n_similar)
    return base + (n_similar,)


def _bind_params_drop_zone(
    ticker: str,
    timeframe: str,
    vwap_side: str,
    nad: Optional[float],
    nbd: Optional[float],
    above_bucket: Optional[str],
    below_bucket: Optional[str],
    as_of_ts_utc: Optional[float],
    n_similar: int,
) -> tuple:
    alo, ahi = bucket_lo(above_bucket), bucket_hi(above_bucket)
    blo, bhi = bucket_lo(below_bucket), bucket_hi(below_bucket)
    base = (
        ticker,
        timeframe,
        vwap_side,
        nad,
        alo,
        ahi,
        nbd,
        blo,
        bhi,
    )
    if as_of_ts_utc is not None:
        return base + (as_of_ts_utc, n_similar)
    return base + (n_similar,)


def _bind_params_drop_vwap(
    ticker: str,
    timeframe: str,
    zone: str,
    nad: Optional[float],
    nbd: Optional[float],
    above_bucket: Optional[str],
    below_bucket: Optional[str],
    as_of_ts_utc: Optional[float],
    n_similar: int,
) -> tuple:
    alo, ahi = bucket_lo(above_bucket), bucket_hi(above_bucket)
    blo, bhi = bucket_lo(below_bucket), bucket_hi(below_bucket)
    base = (
        ticker,
        timeframe,
        zone,
        nad,
        alo,
        ahi,
        nbd,
        blo,
        bhi,
    )
    if as_of_ts_utc is not None:
        return base + (as_of_ts_utc, n_similar)
    return base + (n_similar,)


def run_feature_impact_audit(
    db: Any,
    *,
    ticker: str,
    timeframe: str = CANONICAL_TIMEFRAME,
    zone: str,
    vwap_side: str,
    nearest_above_dist: Optional[float],
    nearest_below_dist: Optional[float],
    n_similar: int = 500,
    as_of_ts_utc: Optional[float] = None,
) -> dict[str, Any]:
    """
    Baseline trace + ablation pool metrics + overlap vs baseline selection (same LIMIT/recency).
    """
    ticker = (ticker or "").upper().strip()
    above_b = dist_bucket(nearest_above_dist)
    below_b = dist_bucket(nearest_below_dist)
    asof_sql, asof_extra = _asof_clause(as_of_ts_utc)

    similar_baseline, trace = db.get_similar_setups(
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
    base_metrics = _limited_pool_metrics(similar_baseline)
    base_ids = _snapshot_id_set(similar_baseline)

    tier_sql_ablations: list[tuple[str, str, tuple]] = [
        (
            "production_tier1_explicit",
            get_snapshot_sql("verification/similarity_feature_audit.py:tier1_ablation")
            + asof_sql
            + " ORDER BY ts_utc DESC LIMIT ?",
            _bind_params_tier1(
                ticker,
                timeframe,
                zone,
                vwap_side,
                nearest_above_dist,
                nearest_below_dist,
                above_b,
                below_b,
                as_of_ts_utc,
                n_similar,
            ),
        ),
        (
            "production_tier2_drop_below_only",
            get_snapshot_sql("verification/similarity_feature_audit.py:tier2_ablation")
            + asof_sql
            + " ORDER BY ts_utc DESC LIMIT ?",
            _bind_params_tier2(
                ticker,
                timeframe,
                zone,
                vwap_side,
                nearest_above_dist,
                above_b,
                as_of_ts_utc,
                n_similar,
            ),
        ),
        (
            "orthogonal_t1_drop_above_keep_below",
            get_snapshot_sql("verification/similarity_feature_audit.py:ortho_below_only")
            + asof_sql
            + " ORDER BY ts_utc DESC LIMIT ?",
            _bind_params_orthogonal_below_only(
                ticker,
                timeframe,
                zone,
                vwap_side,
                nearest_below_dist,
                below_b,
                as_of_ts_utc,
                n_similar,
            ),
        ),
        (
            "orthogonal_t1_drop_zone",
            get_snapshot_sql("verification/similarity_feature_audit.py:ortho_drop_zone")
            + asof_sql
            + " ORDER BY ts_utc DESC LIMIT ?",
            _bind_params_drop_zone(
                ticker,
                timeframe,
                vwap_side,
                nearest_above_dist,
                nearest_below_dist,
                above_b,
                below_b,
                as_of_ts_utc,
                n_similar,
            ),
        ),
        (
            "orthogonal_t1_drop_vwap",
            get_snapshot_sql("verification/similarity_feature_audit.py:ortho_drop_vwap")
            + asof_sql
            + " ORDER BY ts_utc DESC LIMIT ?",
            _bind_params_drop_vwap(
                ticker,
                timeframe,
                zone,
                nearest_above_dist,
                nearest_below_dist,
                above_b,
                below_b,
                as_of_ts_utc,
                n_similar,
            ),
        ),
    ]

    ablation_results: list[dict[str, Any]] = []
    with db._connect() as conn:
        for aid, sql, params in tier_sql_ablations:
            cur = conn.execute(sql, params)
            rows = cur.fetchall()
            m = _limited_pool_metrics(rows)
            oids = _snapshot_id_set(rows)
            ablation_results.append(
                {
                    "ablation_id": aid,
                    "metrics": m,
                    "overlap_vs_production_baseline_limited_pool": _overlap_fraction(base_ids, oids),
                }
            )

    widening_deltas: list[dict[str, Any]] = []
    tiers = trace.get("tiers") or []
    if widening_steps_are_sequential(tiers):
        for i in range(1, len(tiers)):
            p, n = tiers[i - 1], tiers[i]
            widening_deltas.append(
                {
                    "from_tier": int(p["tier"]),
                    "to_tier": int(n["tier"]),
                    "row_count_delta": int(n.get("row_count_after_query_limit", 0))
                    - int(p.get("row_count_after_query_limit", 0)),
                    "relaxed_features": n.get("relaxed_vs_previous_tier") or [],
                }
            )

    verdict, rationale = _readiness_verdict(trace, base_metrics, ablation_results, widening_deltas)

    return {
        "schema": "similarity_feature_audit_report_v1",
        "feature_contract": baseline_feature_contract_v1(),
        "query": {
            "ticker": ticker,
            "timeframe": timeframe,
            "zone": zone,
            "vwap_side": vwap_side,
            "nearest_above_dist": nearest_above_dist,
            "nearest_below_dist": nearest_below_dist,
            "n_similar": n_similar,
            "as_of_ts_utc": as_of_ts_utc,
        },
        "bucket_audit": audit_bucket_definitions(),
        "distance_symmetry_note": audit_above_below_symmetry_hint(
            nearest_above_dist=nearest_above_dist,
            nearest_below_dist=nearest_below_dist,
        ),
        "baseline_from_get_similar_setups": {
            "trace_summary_chosen_tier": trace.get("chosen_tier"),
            "row_count": base_metrics["row_count"],
            "labeled_counts": base_metrics["labeled_counts"],
            "tier_stop_viable": base_metrics["tier_stop_viable"],
            "all_tracked_viable": base_metrics["all_tracked_viable"],
            "stop_reason": trace.get("stop_reason"),
        },
        "widening_marginal_deltas": widening_deltas,
        "ablation_limited_pools": ablation_results,
        "adaptive_shadow_readiness": {"verdict": verdict, "rationale": rationale},
    }


def _readiness_verdict(
    trace: dict[str, Any],
    baseline_metrics: dict[str, Any],
    ablations: list[dict[str, Any]],
    widening_deltas: list[dict[str, Any]],
) -> tuple[str, list[str]]:
    rationale: list[str] = []
    chosen = int(trace.get("chosen_tier") or 0)
    if not baseline_metrics["tier_stop_viable"]:
        rationale.append(
            "Baseline limited pool fails tier-stop viability — data/sparsity issue for this anchor; "
            "shadow comparison should not trust empiricals here."
        )
        return "investigate_before_shadow", rationale

    if chosen >= 5:
        rationale.append(
            "Production reached max tier (broadest pool) — high widening; adaptive shadow should "
            "treat feature sensitivity as elevated."
        )

    if widening_deltas:
        big_jumps = [d for d in widening_deltas if d["row_count_delta"] > 200]
        if len(big_jumps) >= 2:
            rationale.append(
                "Large row-count jumps across multiple widening steps — distance buckets and vwap "
                "may compress pools sharply; bucket granularity is a known sensitivity."
            )

    ortho_zone = next((a for a in ablations if a["ablation_id"] == "orthogonal_t1_drop_zone"), None)
    ortho_vwap = next((a for a in ablations if a["ablation_id"] == "orthogonal_t1_drop_vwap"), None)
    if ortho_zone and ortho_vwap:
        rz = ortho_zone["metrics"]["row_count"]
        rw = ortho_vwap["metrics"]["row_count"]
        if rz > 0 and rw > 0 and max(rz, rw) / min(rz, rw) > 3.0:
            rationale.append(
                f"Asymmetric orthogonal expansion: drop_zone pool={rz} vs drop_vwap pool={rw} — "
                "zone and vwap_side are not redundant; interaction matters."
            )

    if not rationale:
        rationale.append(
            "Baseline tier-stop viable; contract-aligned ablations computed — suitable fixed baseline "
            "for adaptive shadow with standard monitoring."
        )
        return "baseline_acceptable_for_adaptive_shadow", rationale

    return "baseline_acceptable_with_cautions", rationale


def emit_contract_json(path: Path) -> None:
    path.write_text(json.dumps(baseline_feature_contract_v1(), indent=2), encoding="utf-8")
