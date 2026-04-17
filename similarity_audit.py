"""
Issue 21 — structured audit, validation, and export helpers for tier-driven similarity.

Read-only / deterministic utilities. Does not change selection policy (Issue 19).

Column tuples mirror db.py (SIMILARITY_*_OUTCOME_COLUMNS) — keep in sync.

Feature contract (adaptive shadow baseline audit): baseline_feature_contract_v1().
"""
from __future__ import annotations

from typing import Any, Optional

from math_exposure import MIN_SAMPLES_STATISTICAL, bucket_hi, bucket_lo, dist_bucket

# ── Mirror db.py Issue 19 (avoid circular import) ─────────────────────────────
SIMILARITY_EMPIRICAL_OUTCOME_COLUMNS: tuple[str, ...] = (
    "outcome_1c",
    "outcome_3c",
    "outcome_5c",
    "outcome_8c",
    "outcome_13c",
    "outcome_15c",
    "outcome_60c",
)
SIMILARITY_TIER_STOP_OUTCOME_COLUMNS: tuple[str, ...] = (
    "outcome_1c",
    "outcome_5c",
    "outcome_15c",
)


def baseline_feature_contract_v1() -> dict[str, Any]:
    """
    Machine-readable baseline for current heuristic similarity (Issue 19 tiers, Issue 21 trace).

    Authoritative runtime remains db.get_similar_setups; this document must stay aligned
    with structured_constraints_for_tier + relaxed_constraints_vs_previous_tier.
    """
    return {
        "schema": "similarity_feature_contract_v1",
        "production_authority": "db.EdDB.get_similar_setups",
        "issue_policy_ref": "Issue 19 tier-stop (SIMILARITY_TIER_STOP_OUTCOME_COLUMNS); Issue 21 trace",
        "pool_membership": {
            "ticker": {"constraint": "equals", "role": "core_identity"},
            "timeframe": {"constraint": "equals", "role": "core_identity"},
            "outcome_1c": {"constraint": "IS NOT NULL", "role": "pool_gate_for_similar_rows"},
        },
        "distance_bucketing": {
            "function": "math_exposure.dist_bucket",
            "anchor_fields_raw": ["nearest_above_dist", "nearest_below_dist"],
            "null_alignment": "anchor NULL iff row column NULL; else BETWEEN bucket_lo/hi inclusive",
            "note": "Absolute distance before bucket; signed raw preserved on rows",
        },
        "tier_progression": {
            "1": {
                "active_structural_features": [
                    "zone",
                    "vwap_side",
                    "nearest_above_dist_bucket",
                    "nearest_below_dist_bucket",
                ],
                "description": "zone + vwap_side + both distance bucket matches",
            },
            "2": {
                "active_structural_features": ["zone", "vwap_side", "nearest_above_dist_bucket"],
                "relaxed_vs_tier_1": relaxed_constraints_vs_previous_tier(2),
            },
            "3": {
                "active_structural_features": ["zone", "vwap_side"],
                "relaxed_vs_tier_2": relaxed_constraints_vs_previous_tier(3),
            },
            "4": {
                "active_structural_features": ["zone"],
                "relaxed_vs_tier_3": relaxed_constraints_vs_previous_tier(4),
            },
            "5": {
                "active_structural_features": [],
                "relaxed_vs_tier_4": relaxed_constraints_vs_previous_tier(5),
                "description": "ticker + timeframe + outcome_1c only (broadest)",
            },
        },
        "tier_stop": {
            "outcome_columns": list(SIMILARITY_TIER_STOP_OUTCOME_COLUMNS),
            "min_labeled_per_column": MIN_SAMPLES_STATISTICAL,
            "selects_narrowest_tier_where_stop_satisfied": True,
        },
        "auxiliary_empirical_horizons": [
            c
            for c in SIMILARITY_EMPIRICAL_OUTCOME_COLUMNS
            if c not in SIMILARITY_TIER_STOP_OUTCOME_COLUMNS
        ],
        "core_vs_auxiliary_runtime": {
            "core_tier_driving": [
                "zone",
                "vwap_side",
                "nearest_above_dist (bucketed)",
                "nearest_below_dist (bucketed)",
                "ticker",
                "timeframe",
            ],
            "auxiliary_sql": "Session/regime are not SQL filters (explicit in trace notes).",
        },
    }


def contract_expected_structural_filter_keys(tier_num: int) -> set[str]:
    """Keys expected under structured_constraints_for_tier(..., ctx)[structural_filters]."""
    m = baseline_feature_contract_v1()["tier_progression"]
    key = str(tier_num)
    if key not in m:
        return set()
    feats = m[key].get("active_structural_features") or []
    out: set[str] = set()
    for f in feats:
        if f == "nearest_above_dist_bucket":
            out.add("nearest_above_dist")
        elif f == "nearest_below_dist_bucket":
            out.add("nearest_below_dist")
        else:
            out.add(f)
    return out


def _bucket_interval(bucket: str | None) -> dict[str, Any]:
    return {
        "bucket_label": bucket,
        "interval_lo_inclusive": bucket_lo(bucket),
        "interval_hi_inclusive": bucket_hi(bucket),
    }


def normalize_anchor_distances_for_issue19_sql(
    nearest_above_dist: Optional[float],
    nearest_below_dist: Optional[float],
) -> tuple[Optional[float], Optional[float]]:
    """
    Align anchor distances with Issue 19 tier-1/tier-2 SQL + dist_bucket.

    Bucketing uses ``dist_bucket``, which takes ``abs(dist)``. Tier SQL places the **raw**
    column value in ``BETWEEN bucket_lo AND bucket_hi`` (non-negative interval from the
    bucket label). Anchor inputs must use the same **non-negative magnitude** convention
    expected for values inside that interval (never ``-1.0`` when the matching interval
    is ``[0, 1]``).

    Does not modify snapshot rows or Issue 19 queries — caller-only normalization.
    """
    from canonical_distances import canonicalize_distance_read

    return canonicalize_distance_read(nearest_above_dist, nearest_below_dist)


def query_context_for_similarity(
    *,
    ticker: str,
    timeframe: str,
    zone: str,
    vwap_side: str,
    nearest_above_dist: Optional[float],
    nearest_below_dist: Optional[float],
    n_similar: int,
    as_of_ts_utc: Optional[float],
) -> dict[str, Any]:
    """Inputs mirrored in get_similar_setups; used for trace + validation."""
    ab = dist_bucket(nearest_above_dist)
    bb = dist_bucket(nearest_below_dist)
    return {
        "ticker": ticker,
        "timeframe": timeframe,
        "zone": zone,
        "vwap_side": vwap_side,
        "nearest_above_dist_raw": nearest_above_dist,
        "nearest_below_dist_raw": nearest_below_dist,
        "nearest_above_dist_bucket": ab,
        "nearest_below_dist_bucket": bb,
        "nearest_above_bucket_interval": _bucket_interval(ab),
        "nearest_below_bucket_interval": _bucket_interval(bb),
        "n_similar_limit": n_similar,
        "as_of_ts_utc": as_of_ts_utc,
    }


def structured_constraints_for_tier(tier_num: int, ctx: dict[str, Any]) -> dict[str, Any]:
    """Plain structured definition of SQL filters for tier N (matches db.get_similar_setups)."""
    t = (ctx.get("ticker") or "").strip()
    tf = ctx.get("timeframe")
    z = ctx.get("zone")
    vs = ctx.get("vwap_side")
    nad = ctx.get("nearest_above_dist_raw")
    nbd = ctx.get("nearest_below_dist_raw")
    ab = ctx.get("nearest_above_dist_bucket")
    bb = ctx.get("nearest_below_dist_bucket")
    alo, ahi = bucket_lo(ab), bucket_hi(ab)
    blo, bhi = bucket_lo(bb), bucket_hi(bb)
    as_of = ctx.get("as_of_ts_utc")

    base: dict[str, Any] = {
        "tier": tier_num,
        "pool_membership": {
            "ticker": {"constraint": "equals", "value": t},
            "timeframe": {"constraint": "equals", "value": tf},
            "outcome_1c": {"constraint": "is_not_null"},
        },
        "replay_cutoff": (
            {"constraint": "ts_utc_strictly_before", "as_of_ts_utc": as_of}
            if as_of is not None
            else {"constraint": "none"}
        ),
        "order_by_recency_desc_limit": ctx.get("n_similar_limit", 500),
    }

    if tier_num == 1:
        base["structural_filters"] = {
            "zone": {"constraint": "equals", "value": z},
            "vwap_side": {"constraint": "equals", "value": vs},
            "nearest_above_dist": {
                "constraint": "null_aligned_or_between",
                "anchor_value": nad,
                "bucket": ab,
                "between_lo_inclusive": alo,
                "between_hi_inclusive": ahi,
            },
            "nearest_below_dist": {
                "constraint": "null_aligned_or_between",
                "anchor_value": nbd,
                "bucket": bb,
                "between_lo_inclusive": blo,
                "between_hi_inclusive": bhi,
            },
        }
    elif tier_num == 2:
        base["structural_filters"] = {
            "zone": {"constraint": "equals", "value": z},
            "vwap_side": {"constraint": "equals", "value": vs},
            "nearest_above_dist": {
                "constraint": "null_aligned_or_between",
                "anchor_value": nad,
                "bucket": ab,
                "between_lo_inclusive": alo,
                "between_hi_inclusive": ahi,
            },
        }
    elif tier_num == 3:
        base["structural_filters"] = {
            "zone": {"constraint": "equals", "value": z},
            "vwap_side": {"constraint": "equals", "value": vs},
        }
    elif tier_num == 4:
        base["structural_filters"] = {
            "zone": {"constraint": "equals", "value": z},
        }
    elif tier_num == 5:
        base["structural_filters"] = {}
    else:
        base["structural_filters"] = {"error": f"unknown_tier_{tier_num}"}

    return base


def relaxed_constraints_vs_previous_tier(tier_num: int) -> list[str]:
    """What loosened vs tier N-1 (tier 1 has none)."""
    if tier_num <= 1:
        return []
    mapping = {
        2: ["nearest_below_dist_bucket_match_removed"],
        3: ["nearest_above_dist_bucket_match_removed"],
        4: ["vwap_side_match_removed"],
        5: ["zone_match_removed"],
    }
    return mapping.get(tier_num, ["unknown_relaxation_step"])


def widening_summary_from_tiers(trace_tiers: list[dict], chosen_tier: int) -> dict[str, Any]:
    """Structured narrative of tier progression outcome."""
    per: list[dict[str, Any]] = []
    for entry in trace_tiers:
        tier = int(entry["tier"])
        if tier == chosen_tier and entry.get("selected"):
            per.append(
                {
                    "tier": tier,
                    "resolution": "selected",
                    "stop_reason": entry.get("stop_reason") or "tier_stop_viable",
                }
            )
        else:
            nrows = int(entry.get("row_count_after_query_limit") or 0)
            tsv = entry.get("tier_stop_viable", entry.get("empirically_viable"))
            per.append(
                {
                    "tier": tier,
                    "resolution": "skipped",
                    "skip_reason": "tier_stop_not_viable"
                    if nrows > 0
                    else "zero_rows_in_limited_pool",
                    "row_count_after_limit": nrows,
                    "tier_stop_viable": tsv,
                }
            )
    return {
        "widening_occurred": chosen_tier > 1,
        "chosen_tier": chosen_tier,
        "per_tier_resolution": per,
    }


def withheld_horizons_report(labeled_counts: dict[str, int]) -> list[dict[str, Any]]:
    """Horizons below MIN_SAMPLES_STATISTICAL (honest withhold)."""
    out: list[dict[str, Any]] = []
    for col in SIMILARITY_EMPIRICAL_OUTCOME_COLUMNS:
        n = int(labeled_counts.get(col, 0))
        if n < MIN_SAMPLES_STATISTICAL:
            out.append(
                {
                    "outcome_column": col,
                    "labeled_count": n,
                    "min_required": MIN_SAMPLES_STATISTICAL,
                    "withheld": True,
                    "reason": "insufficient_labeled_for_empirical_histogram",
                }
            )
    return out


def tier_stop_weak_horizons(labeled_counts: dict[str, int]) -> list[dict[str, Any]]:
    rows = []
    for col in SIMILARITY_TIER_STOP_OUTCOME_COLUMNS:
        n = int(labeled_counts.get(col, 0))
        rows.append(
            {
                "outcome_column": col,
                "labeled_count": n,
                "min_required": MIN_SAMPLES_STATISTICAL,
                "meets_tier_stop": n >= MIN_SAMPLES_STATISTICAL,
            }
        )
    rows.sort(key=lambda x: x["labeled_count"])
    return rows


def weakest_tracked_horizons(labeled_counts: dict[str, int]) -> list[dict[str, Any]]:
    rows = []
    for col in SIMILARITY_EMPIRICAL_OUTCOME_COLUMNS:
        n = int(labeled_counts.get(col, 0))
        rows.append(
            {
                "outcome_column": col,
                "labeled_count": n,
                "min_required": MIN_SAMPLES_STATISTICAL,
                "meets_full_histogram": n >= MIN_SAMPLES_STATISTICAL,
            }
        )
    rows.sort(key=lambda x: x["labeled_count"])
    return rows


def _dist_matches_null_or_between(
    row_val: Any,
    anchor: Optional[float],
    lo: float,
    hi: float,
) -> bool:
    if anchor is None:
        return row_val is None
    try:
        rv = abs(float(row_val))
    except (TypeError, ValueError):
        return False
    return lo <= rv <= hi


def validate_row_matches_tier_constraints(
    row: dict,
    tier_num: int,
    ctx: dict[str, Any],
) -> list[str]:
    violations: list[str] = []
    t = (ctx.get("ticker") or "").strip()
    tf = ctx.get("timeframe")
    z = ctx.get("zone")
    vs = ctx.get("vwap_side")
    nad = ctx.get("nearest_above_dist_raw")
    nbd = ctx.get("nearest_below_dist_raw")
    ab = ctx.get("nearest_above_dist_bucket")
    bb = ctx.get("nearest_below_dist_bucket")
    alo, ahi = bucket_lo(ab), bucket_hi(ab)
    blo, bhi = bucket_lo(bb), bucket_hi(bb)
    as_of = ctx.get("as_of_ts_utc")

    if (row.get("ticker") or "").strip() != t:
        violations.append("ticker_mismatch")
    if row.get("timeframe") != tf:
        violations.append("timeframe_mismatch")
    if row.get("outcome_1c") is None:
        violations.append("outcome_1c_null")
    if as_of is not None:
        rts = row.get("ts_utc")
        if rts is not None and float(rts) >= float(as_of):
            violations.append("ts_utc_not_strictly_before_as_of")

    if tier_num <= 4 and row.get("zone") != z:
        violations.append("zone_mismatch")
    if tier_num <= 3 and row.get("vwap_side") != vs:
        violations.append("vwap_side_mismatch")

    rad, rbd = row.get("nearest_above_dist"), row.get("nearest_below_dist")
    if tier_num <= 1:
        if not _dist_matches_null_or_between(rad, nad, alo, ahi):
            violations.append("nearest_above_dist_outside_tier1_bucket")
        if not _dist_matches_null_or_between(rbd, nbd, blo, bhi):
            violations.append("nearest_below_dist_outside_tier1_bucket")
    elif tier_num == 2:
        if not _dist_matches_null_or_between(rad, nad, alo, ahi):
            violations.append("nearest_above_dist_outside_tier2_bucket")

    return violations


def validate_selected_rows_match_tier(
    rows: list[dict],
    tier_num: int,
    ctx: dict[str, Any],
) -> dict[str, Any]:
    if not rows:
        return {"tier": tier_num, "rows_checked": 0, "violations_total": 0, "sample_violations": []}
    sample = rows[: min(500, len(rows))]
    samples: list[dict[str, Any]] = []
    vtot = 0
    for i, row in enumerate(sample):
        v = validate_row_matches_tier_constraints(row, tier_num, ctx)
        if v:
            vtot += 1
            if len(samples) < 5:
                samples.append({"index": i, "ts_utc": row.get("ts_utc"), "violations": v})
    return {
        "tier": tier_num,
        "rows_checked": len(sample),
        "violations_total": vtot,
        "sample_violations": samples,
    }


def widening_steps_are_sequential(tier_trace: list[dict]) -> bool:
    tiers_seen = [int(x["tier"]) for x in tier_trace if "tier" in x]
    for i in range(len(tiers_seen) - 1):
        if tiers_seen[i + 1] != tiers_seen[i] + 1:
            return False
    return True


def inspection_row_projection(row: dict) -> dict[str, Any]:
    def _b(v: Any) -> str | None:
        if v is None:
            return None
        try:
            return dist_bucket(float(v))
        except (TypeError, ValueError):
            return None

    nad = row.get("nearest_above_dist")
    nbd = row.get("nearest_below_dist")
    return {
        "snapshot_id": row.get("snapshot_id"),
        "ticker": row.get("ticker"),
        "timeframe": row.get("timeframe"),
        "ts_utc": row.get("ts_utc"),
        "ts_et": row.get("ts_et"),
        "spot": row.get("spot"),
        "zone": row.get("zone"),
        "vwap_side": row.get("vwap_side"),
        "nearest_above_dist": nad,
        "nearest_below_dist": nbd,
        "nearest_above_dist_bucket_derived": _b(nad),
        "nearest_below_dist_bucket_derived": _b(nbd),
        "match_tier": row.get("match_tier"),
        "outcome_1c": row.get("outcome_1c"),
        "outcome_3c": row.get("outcome_3c"),
        "outcome_5c": row.get("outcome_5c"),
        "outcome_8c": row.get("outcome_8c"),
        "outcome_13c": row.get("outcome_13c"),
        "outcome_15c": row.get("outcome_15c"),
        "outcome_60c": row.get("outcome_60c"),
    }


def similarity_trace_machine_summary(trace: dict[str, Any]) -> dict[str, Any]:
    """Deterministic, JSON-friendly export for validation / future ablation (Issue 21 Part D)."""
    fc = trace.get("final_selected_labeled_counts") or trace.get("final_labeled_counts") or {}
    return {
        "schema": "similarity_trace_summary_v1",
        "ticker": trace.get("ticker"),
        "timeframe": trace.get("timeframe"),
        "final_selected_tier": trace.get("final_selected_tier", trace.get("chosen_tier")),
        "final_selected_row_count": trace.get("final_selected_row_count", trace.get("final_similar_count")),
        "stop_reason": trace.get("stop_reason"),
        "final_tier_stop_viable": trace.get("final_tier_stop_viable", trace.get("final_empirically_viable")),
        "final_all_tracked_viable": trace.get("final_all_tracked_viable"),
        "tier_stop_outcome_columns": trace.get("tier_stop_outcome_columns"),
        "labeled_counts_final": dict(fc) if fc else {},
        "withheld_horizons_count": len(trace.get("withheld_horizons") or []),
        "widening_occurred": (trace.get("widening_analysis") or {}).get("widening_occurred"),
    }


def build_similar_inspection_bundle(
    rows: list[dict],
    trace: dict[str, Any],
    *,
    max_rows: int = 100,
) -> dict[str, Any]:
    """Developer-facing bundle: trace header + projected rows (Issue 21 Part B)."""
    tier = int(trace.get("final_selected_tier") or trace.get("chosen_tier") or 0)
    lim = max(0, min(max_rows, len(rows)))
    projected = [inspection_row_projection(r) for r in rows[:lim]]
    return {
        "schema": "similar_set_inspection_v1",
        "final_selected_tier": tier,
        "row_projection_count": len(projected),
        "total_rows_returned": len(rows),
        "trace_summary": similarity_trace_machine_summary(trace),
        "rows": projected,
    }


def merge_trace_with_shadow_extension(
    trace: dict[str, Any],
    shadow_extension_payload: dict[str, Any],
) -> dict[str, Any]:
    """Additive Issue 21 extension — parent trace keys unchanged; adds shadow_extension only."""
    out = dict(trace)
    out["shadow_extension"] = {
        "extension_schema": "similarity_trace_shadow_extension_v1",
        **shadow_extension_payload,
    }
    return out
