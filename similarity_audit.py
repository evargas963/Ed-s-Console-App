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
from ml_horizon import PRIMARY_DECISION_HORIZONS

SIMILARITY_EMPIRICAL_OUTCOME_COLUMNS: tuple[str, ...] = tuple(
    f"outcome_{hz}" for hz in PRIMARY_DECISION_HORIZONS
)
SIMILARITY_TIER_STOP_OUTCOME_COLUMNS: tuple[str, ...] = (
    "outcome_1c",
    "outcome_5c",
    "outcome_15c",
)






def _bucket_interval(bucket: str | None) -> dict[str, Any]:
    return {
        "bucket_label": bucket,
        "interval_lo_inclusive": bucket_lo(bucket),
        "interval_hi_inclusive": bucket_hi(bucket),
    }




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
















