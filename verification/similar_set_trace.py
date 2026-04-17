"""
Phase 2 — full similar-set + empirical horizon trace (same DB path as live compute_prediction).

Maps diagnostic letters A–G to measurable counts. Session/regime are not SQL filters
in get_similar_setups; that is explicit in the output.
"""
from __future__ import annotations

import sqlite3
from typing import Any, Optional

from db import get_snapshot_sql
from math_exposure import MIN_SAMPLES_STATISTICAL, bucket_hi, bucket_lo, dist_bucket
from prediction_engine import _count_labeled, _literal_empirical_horizon
from similarity_audit import similarity_trace_machine_summary
from timeframe_config import CANONICAL_TIMEFRAME

PRODUCT_EMPIRICAL = (
    ("1c", "outcome_1c", 1),
    ("5c", "outcome_5c", 5),
    ("15c", "outcome_15c", 15),
    ("60c", "outcome_60c", 60),
)


def _one(cur: sqlite3.Cursor, sql: str, params: tuple) -> int:
    return int(cur.execute(sql, params).fetchone()[0])


def sql_tier_pool_counts_unlimited(
    cur: sqlite3.Cursor,
    *,
    ticker: str,
    timeframe: str,
    zone: str,
    vwap_side: str,
    nearest_above_dist: Optional[float],
    nearest_below_dist: Optional[float],
    as_of_ts_utc: Optional[float] = None,
) -> dict[str, Any]:
    """Rows satisfying each tier WHERE clause (no LIMIT), optional replay cut."""
    ab = dist_bucket(nearest_above_dist)
    bb = dist_bucket(nearest_below_dist)
    _asof = "" if as_of_ts_utc is None else " AND ts_utc < ? "
    _asof_param: tuple = () if as_of_ts_utc is None else (as_of_ts_utc,)

    t1_sql = get_snapshot_sql("tools/_diag_db_counts.py:103").strip() + _asof
    t1p = (
        ticker,
        timeframe,
        zone,
        vwap_side,
        nearest_above_dist,
        bucket_lo(ab),
        bucket_hi(ab),
        nearest_below_dist,
        bucket_lo(bb),
        bucket_hi(bb),
    ) + _asof_param

    t2_sql = get_snapshot_sql("tools/_diag_db_counts.py:122").strip() + _asof
    t2p = (
        ticker,
        timeframe,
        zone,
        vwap_side,
        nearest_above_dist,
        bucket_lo(ab),
        bucket_hi(ab),
    ) + _asof_param

    t3_sql = get_snapshot_sql("tools/_diag_db_counts.py:129").strip() + _asof
    t3p = (ticker, timeframe, zone, vwap_side) + _asof_param

    t4_sql = get_snapshot_sql("tools/_diag_db_counts.py:135").strip() + _asof
    t4p = (ticker, timeframe, zone) + _asof_param

    t5_sql = get_snapshot_sql("tools/_diag_db_counts.py:141").strip() + _asof
    t5p = (ticker, timeframe) + _asof_param

    return {
        "tier1_zone_vwap_both_dist_buckets": _one(cur, t1_sql, t1p),
        "tier2_zone_vwap_above_bucket": _one(cur, t2_sql, t2p),
        "tier3_zone_vwap": _one(cur, t3_sql, t3p),
        "tier4_zone_only": _one(cur, t4_sql, t4p),
        "tier5_ticker_timeframe": _one(cur, t5_sql, t5p),
    }


def full_similar_and_empirical_trace(
    db,
    *,
    ticker: str,
    timeframe: str = CANONICAL_TIMEFRAME,
    zone: str,
    vwap_side: str,
    nearest_above_dist: Optional[float],
    nearest_below_dist: Optional[float],
    n_similar: int = 500,
    as_of_ts_utc: Optional[float] = None,
    include_similar: bool = False,
) -> dict[str, Any]:
    """
    One-stop trace: base counts, tier pools, returned similar list + SQL trace,
    and _literal_empirical_horizon for product horizons (1c/5c/15c/60c).
    """
    ticker = (ticker or "").upper().strip()
    out: dict[str, Any] = {"ticker": ticker, "timeframe": timeframe, "as_of_ts_utc": as_of_ts_utc}

    with db._connect() as conn:
        cur = conn.cursor()
        if as_of_ts_utc is None:
            base_total = _one(
                cur,
                get_snapshot_sql("tools/_diag_db_counts.py:36"),
                (ticker, timeframe),
            )
            pool_1c = _one(
                cur,
                get_snapshot_sql("tools/_diag_db_counts.py:141"),
                (ticker, timeframe),
            )
        else:
            base_total = _one(
                cur,
                get_snapshot_sql("tools/_diag_db_counts.py:36") + " AND ts_utc < ?",
                (ticker, timeframe, as_of_ts_utc),
            )
            pool_1c = _one(
                cur,
                get_snapshot_sql("tools/_diag_db_counts.py:141") + " AND ts_utc < ?",
                (ticker, timeframe, as_of_ts_utc),
            )

        tier_pools = sql_tier_pool_counts_unlimited(
            cur,
            ticker=ticker,
            timeframe=timeframe,
            zone=zone,
            vwap_side=vwap_side,
            nearest_above_dist=nearest_above_dist,
            nearest_below_dist=nearest_below_dist,
            as_of_ts_utc=as_of_ts_utc,
        )

    similar, sql_trace = db.get_similar_setups(
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

    horizon_filter: dict[str, Any] = {}
    for hz_key, col, _bars in PRODUCT_EMPIRICAL:
        horizon_filter[hz_key] = {
            "outcome_column": col,
            "labeled_count_in_similar": _count_labeled(similar, col),
        }

    empirical: dict[str, Any] = {}
    for hz_key, col, bars in PRODUCT_EMPIRICAL:
        probs, src_key, note, n = _literal_empirical_horizon(similar, col, bars)
        if probs is not None:
            st = "OK"
        elif not similar:
            st = "MISSING"
        else:
            st = "WITHHELD"
        empirical[hz_key] = {
            "status": st,
            "labeled_count": n,
            "min_required": MIN_SAMPLES_STATISTICAL,
            "probability_triplet_present": probs is not None,
            "tradeable_triplet": probs is not None,
            "source_key": src_key,
            "source": "empirical" if probs is not None else "withheld",
            "note": note,
        }

    out["narrowing"] = {
        "A_base_candidate_snapshots_ticker_timeframe": base_total,
        "B_after_outcome_1c_non_null_pool_same_ticker_timeframe": pool_1c,
        "C_session_time_filter": {
            "applies_in_sql": False,
            "detail": "Not a WHERE clause in get_similar_setups (tiered similarity only).",
        },
        "D_regime_filter": {
            "applies_in_sql": False,
            "detail": "Regime is not a WHERE clause in get_similar_setups.",
        },
        "E_tier_progression_sql": sql_trace.get("tiers"),
        "chosen_tier": sql_trace.get("chosen_tier"),
        "tier_pool_counts_full_db_no_limit": tier_pools,
        "F_horizon_label_counts_in_returned_similar": horizon_filter,
        "G_final_similar_list_size": len(similar),
    }
    out["sql_trace"] = sql_trace
    out["similarity_trace_machine_summary"] = similarity_trace_machine_summary(sql_trace)
    out["empirical_horizons"] = empirical
    out["similar_preview_ts_utc"] = [r.get("ts_utc") for r in similar[:3]]
    if include_similar:
        out["similar"] = similar
    return out
