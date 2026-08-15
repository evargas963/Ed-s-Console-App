"""
Adaptive similarity — SHADOW / ANALYSIS ONLY (Issue adaptive shadow).

Does not replace or alter heuristic authority (get_similar_setups).
Same feature dimensions as production: zone, vwap_side, nearest_* distance buckets.

Modes:
- baseline_control — delegates to get_similar_setups (identical selection)
- weighted — scored ranking on a broad candidate pool, top N
- order_variant — weighted with relaxed_features excluded from scoring (soft drop)
- adaptive_shadow_v2 — Issue 19 tier-1 SQL pool only, additive structural + Tier 3 context score
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional

from math_exposure import bucket_hi, bucket_lo, dist_bucket

from db import sql_adaptive_broad_similarity_pool, sql_issue19_tier1_candidate_rows

from timeframe_config import CANONICAL_TIMEFRAME
from similarity_audit import query_context_for_similarity

from instrument_identity import ticker_storage_key  # noqa: E402
from db import (  # noqa: E402
    similarity_empirically_viable,
    similarity_labeled_counts,
    similarity_tier_stop_viable,
)

import logging

_log_sim = logging.getLogger(__name__)

# Bucket labels in distance order for adjacency credit
_BUCKET_INDEX: dict[str | None, int] = {
    None: -1,
    "0-1": 0,
    "1-2": 1,
    "2-5": 2,
    "5+": 3,
}

# ── Adaptive Shadow v2 (Issue 19 tier-1 SQL pool + Tier 3 context scoring only) ──
ADAPTIVE_SHADOW_V2_TIER3_COLUMNS: tuple[str, ...] = (
    "regime_primary",
    "vix_bucket",
    "market_session",
    "regime_confidence",
)

TIER3_WEIGHT_RANGES_V1: dict[str, tuple[float, float]] = {
    "regime_primary": (0.5, 2.0),
    "vix_bucket": (0.3, 1.5),
    "market_session": (0.3, 1.5),
    "regime_confidence": (0.2, 1.0),
}


def default_tier3_mid_weights_v1() -> dict[str, float]:
    """Midpoint of each calibrated band (deterministic)."""
    return {
        k: (TIER3_WEIGHT_RANGES_V1[k][0] + TIER3_WEIGHT_RANGES_V1[k][1]) / 2.0
        for k in ADAPTIVE_SHADOW_V2_TIER3_COLUMNS
    }


def calibration_weight_profiles_v1() -> list[dict[str, Any]]:
    """
    Small staged sweep (~15 configs): corners, mid baseline, per-feature low/high from mid.
    Deterministic and bounded — not a full factorial grid.
    """
    cols = list(ADAPTIVE_SHADOW_V2_TIER3_COLUMNS)
    lo = {c: TIER3_WEIGHT_RANGES_V1[c][0] for c in cols}
    hi = {c: TIER3_WEIGHT_RANGES_V1[c][1] for c in cols}
    mid = default_tier3_mid_weights_v1()
    profiles: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, float], ...]] = set()

    def push(config_id: str, w: dict[str, float]) -> None:
        key = tuple(sorted((k, round(w[k], 6)) for k in cols))
        if key in seen:
            return
        seen.add(key)
        profiles.append({"config_id": config_id, "tier3_weights": {c: float(w[c]) for c in cols}})

    push("all_low", lo)
    push("all_high", hi)
    push("mid_baseline", mid)
    for c in cols:
        w_lo = dict(mid)
        w_lo[c] = lo[c]
        push(f"from_mid_{c}_low", w_lo)
        w_hi = dict(mid)
        w_hi[c] = hi[c]
        push(f"from_mid_{c}_high", w_hi)
    for c in cols:
        w_only = dict(lo)
        w_only[c] = hi[c]
        push(f"emphasis_{c}_high_others_low", w_only)
    return profiles


def _fetch_issue19_tier1_candidate_rows(
    db: Any,
    *,
    ticker: str,
    timeframe: str,
    zone: str,
    vwap_side: str,
    nearest_above_dist: Optional[float],
    nearest_below_dist: Optional[float],
    as_of_ts_utc: Optional[float],
    structural_pool_cap: int,
) -> list[dict[str, Any]]:
    """
    Issue 19 tier-1 WHERE (zone + vwap_side + both distance buckets + outcome_1c),
    with configurable LIMIT for shadow ranking (production uses n_similar only).
    """
    if timeframe != CANONICAL_TIMEFRAME:
        _log_sim.warning(
            "_fetch_issue19_tier1_candidate_rows: timeframe=%r rejected — canonical %r only",
            timeframe,
            CANONICAL_TIMEFRAME,
        )
        return []
    t = ticker_storage_key(ticker)  # RC-345/F25: canonical snapshots/similarity identity
    above_bucket = dist_bucket(nearest_above_dist)
    below_bucket = dist_bucket(nearest_below_dist)
    _asof_sql = "" if as_of_ts_utc is None else " AND ts_utc < ? "
    _p1: tuple[Any, ...] = (
        t,
        timeframe,
        zone,
        vwap_side,
        nearest_above_dist,
        bucket_lo(above_bucket),
        bucket_hi(above_bucket),
        nearest_below_dist,
        bucket_lo(below_bucket),
        bucket_hi(below_bucket),
    )
    if as_of_ts_utc is not None:
        _p1 = _p1 + (as_of_ts_utc, structural_pool_cap)
    else:
        _p1 = _p1 + (structural_pool_cap,)
    with db._connect() as conn:
        rows = conn.execute(
            sql_issue19_tier1_candidate_rows(_asof_sql),
            _p1,
        ).fetchall()
    return [dict(r) for r in rows]


def _adaptive_v2_score_row(
    row: dict[str, Any],
    anchor_ctx: dict[str, Any],
    overlay_t3: dict[str, Any],
    tier3_weights: dict[str, float],
    *,
    adjacent_credit: float = 0.5,
) -> tuple[float, dict[str, float]]:
    """Additive: structural (zone/vwap fixed at 1 each in-pool + bucket scores) + weighted Tier 3."""
    s_z = 1.0
    s_v = 1.0
    s_a = _bucket_adjacency_score(
        row.get("nearest_above_dist"),
        anchor_ctx.get("nearest_above_dist_raw"),
        adjacent_credit=adjacent_credit,
    )
    s_b = _bucket_adjacency_score(
        row.get("nearest_below_dist"),
        anchor_ctx.get("nearest_below_dist_raw"),
        adjacent_credit=adjacent_credit,
    )
    structural_total = s_z + s_v + s_a + s_b
    contrib: dict[str, float] = {
        "struct_zone": s_z,
        "struct_vwap_side": s_v,
        "struct_above_bucket": s_a,
        "struct_below_bucket": s_b,
        "structural_subtotal": structural_total,
    }
    ctx_sum = 0.0
    for col in ADAPTIVE_SHADOW_V2_TIER3_COLUMNS:
        w = float(tier3_weights.get(col, 0.0))
        if w == 0.0:
            contrib[f"ctx_{col}"] = 0.0
            continue
        av = overlay_t3.get(col)
        if av is None:
            contrib[f"ctx_{col}"] = 0.0
            continue
        m = _categorical_soft_match(row.get(col), av)
        if m < 0.0:
            contrib[f"ctx_{col}"] = 0.0
            continue
        part = w * max(0.0, m)
        contrib[f"ctx_{col}"] = part
        ctx_sum += part
    contrib["context_subtotal"] = ctx_sum
    final = structural_total + ctx_sum
    contrib["final_score"] = final
    return final, contrib


def run_adaptive_shadow_v2(
    db: Any,
    *,
    ticker: str,
    timeframe: str,
    zone: str,
    vwap_side: str,
    nearest_above_dist: Optional[float],
    nearest_below_dist: Optional[float],
    n_similar: int = 500,
    as_of_ts_utc: Optional[float] = None,
    structural_pool_cap: int = 8000,
    tier3_weights: Optional[dict[str, float]] = None,
    adjacent_credit: float = 0.5,
    anchor_overlay: Optional[dict[str, Any]] = None,
    variant: str = "adaptive_shadow_v2",
) -> AdaptiveShadowRun:
    """
    Shadow-only ranking: strict Issue 19 tier-1 structural pool, then structural + Tier 3 scores.

    Tier 3 uses only ADAPTIVE_SHADOW_V2_TIER3_COLUMNS; anchor labels from resolve_overlay
    when anchor_overlay is omitted (lazy import avoids circular dependency).
    """
    ticker = ticker_storage_key(ticker)  # RC-345/F25: canonical snapshots/similarity identity
    if timeframe != CANONICAL_TIMEFRAME:
        _log_sim.warning(
            "run_adaptive_shadow_v2: timeframe=%r rejected — shadow Issue 19 pool is %r only",
            timeframe,
            CANONICAL_TIMEFRAME,
        )
        return AdaptiveShadowRun(
            mode="adaptive_shadow_v2",
            variant=variant,
            selected_rows=[],
            scores=[],
            row_contributions=[],
            score_distribution=_score_distribution([]),
            candidate_pool_size=0,
            weights_used={},
            relaxed_features=[],
            labeled_counts={},
            tier_stop_viable=False,
            all_tracked_viable=False,
            selected_row_ids=[],
            extra={
                "reject_reason": "non_canonical_timeframe",
                "requested_timeframe": timeframe,
                "canonical_timeframe": CANONICAL_TIMEFRAME,
            },
        )
    if tier3_weights:
        tw = {k: float(tier3_weights.get(k, 0.0)) for k in ADAPTIVE_SHADOW_V2_TIER3_COLUMNS}
    else:
        tw = default_tier3_mid_weights_v1()
    anchor_ctx = query_context_for_similarity(
        ticker=ticker,
        timeframe=timeframe,
        zone=zone,
        vwap_side=vwap_side,
        nearest_above_dist=nearest_above_dist,
        nearest_below_dist=nearest_below_dist,
        n_similar=n_similar,
        as_of_ts_utc=as_of_ts_utc,
    )
    overlay_resolution: Optional[dict[str, Any]] = None
    if anchor_overlay is None:
        from similarity_feature_search import resolve_overlay_for_anchor

        res = resolve_overlay_for_anchor(
            db,
            ticker=ticker,
            timeframe=timeframe,
            zone=zone,
            vwap_side=vwap_side,
            nearest_above_dist=nearest_above_dist,
            nearest_below_dist=nearest_below_dist,
        )
        anchor_overlay = res.get("overlay") or {}
        overlay_resolution = res.get("resolution")
    overlay_t3 = {k: v for k, v in anchor_overlay.items() if k in ADAPTIVE_SHADOW_V2_TIER3_COLUMNS}

    candidates = _fetch_issue19_tier1_candidate_rows(
        db,
        ticker=ticker,
        timeframe=timeframe,
        zone=zone,
        vwap_side=vwap_side,
        nearest_above_dist=nearest_above_dist,
        nearest_below_dist=nearest_below_dist,
        as_of_ts_utc=as_of_ts_utc,
        structural_pool_cap=structural_pool_cap,
    )
    scored: list[tuple[float, dict[str, Any], dict[str, float]]] = []
    for row in candidates:
        final, cdict = _adaptive_v2_score_row(
            row,
            anchor_ctx,
            overlay_t3,
            tw,
            adjacent_credit=adjacent_credit,
        )
        scored.append((final, row, cdict))
    scored.sort(
        key=lambda x: (
            -x[0],
            -float(x[1].get("ts_utc") or 0),
            -(x[1].get("snapshot_id") or 0),
        )
    )
    top = scored[:n_similar]
    sel_rows = [t[1] for t in top]
    scores = [t[0] for t in top]
    contribs = [t[2] for t in top]
    fc = similarity_labeled_counts(sel_rows)
    w_used = dict(default_equal_weights())
    w_used.update({f"tier3_{k}": tw[k] for k in ADAPTIVE_SHADOW_V2_TIER3_COLUMNS})
    return AdaptiveShadowRun(
        mode="adaptive_shadow_v2",
        variant=variant,
        selected_rows=sel_rows,
        scores=scores,
        row_contributions=contribs,
        score_distribution=_score_distribution(scores),
        candidate_pool_size=len(candidates),
        weights_used=w_used,
        relaxed_features=[],
        labeled_counts=dict(fc),
        tier_stop_viable=similarity_tier_stop_viable(fc),
        all_tracked_viable=similarity_empirically_viable(fc),
        selected_row_ids=_selected_ids(sel_rows),
        extra={
            "tier3_weights": tw,
            "anchor_overlay_tier3": overlay_t3,
            "structural_pool_fetched": len(candidates),
            "adjacent_credit": adjacent_credit,
            "issue19_pool": "tier1_only_strict",
            "overlay_resolution": overlay_resolution,
        },
    )


def default_equal_weights() -> dict[str, float]:
    return {
        "zone": 1.0,
        "vwap_side": 1.0,
        "above_bucket": 1.0,
        "below_bucket": 1.0,
    }


def _bucket_adjacency_score(
    row_val: Any,
    anchor_val: Any,
    *,
    adjacent_credit: float = 0.5,
) -> float:
    """1.0 exact bucket match; adjacent bucket distance 1 => adjacent_credit; else 0."""
    try:
        rb = dist_bucket(float(row_val)) if row_val is not None else None
    except (TypeError, ValueError):
        rb = None
    try:
        ab = dist_bucket(float(anchor_val)) if anchor_val is not None else None
    except (TypeError, ValueError):
        ab = None
    if rb is None and ab is None:
        return 1.0
    if rb is None or ab is None:
        return 0.0
    if rb == ab:
        return 1.0
    ir, ia = _BUCKET_INDEX.get(rb, -99), _BUCKET_INDEX.get(ab, -99)
    if ir >= 0 and ia >= 0 and abs(ir - ia) == 1:
        return adjacent_credit
    return 0.0


def _categorical_soft_match(row_val: Any, anchor_val: Any) -> float:
    """1.0 match, 0.0 mismatch, -1.0 skip (anchor missing)."""
    if anchor_val is None:
        return -1.0
    if row_val is None:
        return 0.0
    return (
        1.0
        if str(row_val).strip().lower() == str(anchor_val).strip().lower()
        else 0.0
    )


def _score_row(
    row: dict[str, Any],
    anchor: dict[str, Any],
    weights: dict[str, float],
    relaxed: frozenset[str],
    *,
    adjacent_credit: float = 0.5,
    anchor_overlay: Optional[dict[str, Any]] = None,
    extra_soft_weights: Optional[dict[str, float]] = None,
) -> tuple[float, dict[str, float]]:
    """Normalized score in [0,1] and per-feature contributions (pre-normalization)."""
    triples: list[tuple[str, float, float]] = []
    if "zone" not in relaxed:
        w = weights.get("zone", 1.0)
        m = 1.0 if (row.get("zone") == anchor.get("zone")) else 0.0
        triples.append(("zone", w, m))
    if "vwap_side" not in relaxed:
        w = weights.get("vwap_side", 1.0)
        m = 1.0 if (row.get("vwap_side") == anchor.get("vwap_side")) else 0.0
        triples.append(("vwap_side", w, m))
    if "above_bucket" not in relaxed:
        w = weights.get("above_bucket", 1.0)
        m = _bucket_adjacency_score(
            row.get("nearest_above_dist"),
            anchor.get("nearest_above_dist_raw"),
            adjacent_credit=adjacent_credit,
        )
        triples.append(("above_bucket", w, m))
    if "below_bucket" not in relaxed:
        w = weights.get("below_bucket", 1.0)
        m = _bucket_adjacency_score(
            row.get("nearest_below_dist"),
            anchor.get("nearest_below_dist_raw"),
            adjacent_credit=adjacent_credit,
        )
        triples.append(("below_bucket", w, m))
    ao = anchor_overlay or {}
    for col, wsf in (extra_soft_weights or {}).items():
        if col in relaxed:
            continue
        av = ao.get(col)
        cm = _categorical_soft_match(row.get(col), av)
        if cm < 0.0:
            continue
        triples.append((col, float(wsf), cm))
    terms = {k: w * m for k, w, m in triples}
    denom = sum(w for k, w, m in triples)
    raw_sum = sum(w * m for k, w, m in triples)
    norm = (raw_sum / denom) if denom > 0 else 0.0
    return norm, terms


def _score_distribution(scores: list[float]) -> dict[str, Any]:
    if not scores:
        return {
            "count": 0,
            "min": None,
            "max": None,
            "mean": None,
            "std": None,
            "p25": None,
            "p75": None,
        }
    s = sorted(scores)
    n = len(s)
    mean = sum(s) / n
    var = sum((x - mean) ** 2 for x in s) / n
    std = math.sqrt(var) if n else 0.0

    def _pct(p: float) -> float:
        i = int(p * (n - 1))
        return round(s[i], 6)

    return {
        "count": n,
        "min": round(s[0], 6),
        "max": round(s[-1], 6),
        "mean": round(mean, 6),
        "std": round(std, 6),
        "p25": _pct(0.25),
        "p75": _pct(0.75),
    }


def _fetch_candidate_rows(
    db: Any,
    *,
    ticker: str,
    timeframe: str,
    as_of_ts_utc: Optional[float],
    cap: int,
) -> list[dict]:
    _asof = "" if as_of_ts_utc is None else " AND ts_utc < ? "
    params: list[Any] = [ticker, timeframe]
    if as_of_ts_utc is not None:
        params.append(as_of_ts_utc)
    params.append(cap)
    with db._connect() as conn:
        rows = conn.execute(
            sql_adaptive_broad_similarity_pool(_asof),
            tuple(params),
        ).fetchall()
    return [dict(r) for r in rows]


def _selected_ids(rows: list[dict]) -> list[Any]:
    out = []
    for r in rows:
        sid = r.get("snapshot_id")
        if sid is not None:
            out.append(sid)
    return out


def _overlap_metrics(ids_a: set[Any], ids_b: set[Any]) -> dict[str, Any]:
    if not ids_a and not ids_b:
        return {"jaccard": 1.0, "recall_vs_a": 1.0, "precision_vs_a": 1.0, "intersection": 0}
    inter = len(ids_a & ids_b)
    union = len(ids_a | ids_b)
    jacc = inter / union if union else 0.0
    rec = inter / len(ids_a) if ids_a else 0.0
    prec = inter / len(ids_b) if ids_b else 0.0
    return {
        "jaccard": round(jacc, 6),
        "recall_vs_a": round(rec, 6),
        "precision_vs_a": round(prec, 6),
        "intersection": inter,
    }


@dataclass
class AdaptiveShadowRun:
    """One shadow selection run (analysis only)."""

    mode: str
    variant: str
    selected_rows: list[dict]
    scores: list[float]
    row_contributions: list[dict[str, float]]
    score_distribution: dict[str, Any]
    candidate_pool_size: int
    weights_used: dict[str, float]
    relaxed_features: list[str]
    labeled_counts: dict[str, int]
    tier_stop_viable: bool
    all_tracked_viable: bool
    selected_row_ids: list[Any]
    extra: dict[str, Any] = field(default_factory=dict)


def run_weighted_selection(
    db: Any,
    *,
    ticker: str,
    timeframe: str,
    zone: str,
    vwap_side: str,
    nearest_above_dist: Optional[float],
    nearest_below_dist: Optional[float],
    n_similar: int = 500,
    as_of_ts_utc: Optional[float] = None,
    weights: Optional[dict[str, float]] = None,
    relaxed_features: frozenset[str] = frozenset(),
    candidate_pool_cap: int = 5000,
    adjacent_credit: float = 0.5,
    variant: str = "weighted_equal",
    anchor_overlay: Optional[dict[str, Any]] = None,
    extra_soft_weights: Optional[dict[str, float]] = None,
) -> AdaptiveShadowRun:
    ticker = ticker_storage_key(ticker)  # RC-345/F25: canonical snapshots/similarity identity
    w = dict(weights or default_equal_weights())
    anchor = query_context_for_similarity(
        ticker=ticker,
        timeframe=timeframe,
        zone=zone,
        vwap_side=vwap_side,
        nearest_above_dist=nearest_above_dist,
        nearest_below_dist=nearest_below_dist,
        n_similar=n_similar,
        as_of_ts_utc=as_of_ts_utc,
    )

    candidates = _fetch_candidate_rows(
        db,
        ticker=ticker,
        timeframe=timeframe,
        as_of_ts_utc=as_of_ts_utc,
        cap=max(candidate_pool_cap, n_similar * 5),
    )
    scored: list[tuple[float, dict, dict[str, float]]] = []
    for row in candidates:
        sc, contrib = _score_row(
            row,
            anchor,
            w,
            relaxed_features,
            adjacent_credit=adjacent_credit,
            anchor_overlay=anchor_overlay,
            extra_soft_weights=extra_soft_weights,
        )
        scored.append((sc, row, contrib))
    scored.sort(key=lambda x: (-x[0], -float(x[1].get("ts_utc") or 0), -(x[1].get("snapshot_id") or 0)))

    top = scored[:n_similar]
    sel_rows = [t[1] for t in top]
    scores = [t[0] for t in top]
    contribs = [t[2] for t in top]
    fc = similarity_labeled_counts(sel_rows)
    return AdaptiveShadowRun(
        mode="weighted",
        variant=variant,
        selected_rows=sel_rows,
        scores=scores,
        row_contributions=contribs,
        score_distribution=_score_distribution(scores),
        candidate_pool_size=len(candidates),
        weights_used=w,
        relaxed_features=sorted(relaxed_features),
        labeled_counts=dict(fc),
        tier_stop_viable=similarity_tier_stop_viable(fc),
        all_tracked_viable=similarity_empirically_viable(fc),
        selected_row_ids=_selected_ids(sel_rows),
        extra={
            "anchor_query_context_keys": list(anchor.keys()),
            "adjacent_credit": adjacent_credit,
            "anchor_overlay_keys": sorted((anchor_overlay or {}).keys()),
            "extra_soft_weights": dict(extra_soft_weights or {}),
        },
    )


def run_baseline_control(
    db: Any,
    *,
    ticker: str,
    timeframe: str,
    zone: str,
    vwap_side: str,
    nearest_above_dist: Optional[float],
    nearest_below_dist: Optional[float],
    n_similar: int = 500,
    as_of_ts_utc: Optional[float] = None,
) -> AdaptiveShadowRun:
    """Heuristic — identical to production selection."""
    ticker = ticker_storage_key(ticker)  # RC-345/F25: canonical snapshots/similarity identity
    rows = db.get_similar_setups(
        ticker=ticker,
        timeframe=timeframe,
        zone=zone,
        vwap_side=vwap_side,
        nearest_above_dist=nearest_above_dist,
        nearest_below_dist=nearest_below_dist,
        n_similar=n_similar,
        return_trace=False,
        as_of_ts_utc=as_of_ts_utc,
    )
    fc = similarity_labeled_counts(rows)
    return AdaptiveShadowRun(
        mode="baseline_control",
        variant="heuristic_delegate",
        selected_rows=list(rows),
        scores=[1.0] * len(rows),
        row_contributions=[{"heuristic": 1.0} for _ in rows],
        score_distribution=_score_distribution([1.0] * len(rows) if rows else []),
        candidate_pool_size=-1,
        weights_used=default_equal_weights(),
        relaxed_features=[],
        labeled_counts=dict(fc),
        tier_stop_viable=similarity_tier_stop_viable(fc),
        all_tracked_viable=similarity_empirically_viable(fc),
        selected_row_ids=_selected_ids(rows),
        extra={"note": "rows from get_similar_setups only"},
    )


ORDERING_PRESETS: dict[str, frozenset[str]] = {
    "production_soft_below_first": frozenset({"below_bucket"}),
    "production_soft_above_first": frozenset({"above_bucket"}),
    "drop_vwap_first_soft": frozenset({"vwap_side"}),
    "drop_zone_last_soft": frozenset({"zone"}),
    "drop_both_distance_soft": frozenset({"above_bucket", "below_bucket"}),
}


def run_order_variant(
    db: Any,
    preset: str,
    *,
    ticker: str,
    timeframe: str,
    zone: str,
    vwap_side: str,
    nearest_above_dist: Optional[float],
    nearest_below_dist: Optional[float],
    n_similar: int = 500,
    as_of_ts_utc: Optional[float] = None,
    weights: Optional[dict[str, float]] = None,
    candidate_pool_cap: int = 5000,
    anchor_overlay: Optional[dict[str, Any]] = None,
    extra_soft_weights: Optional[dict[str, float]] = None,
) -> AdaptiveShadowRun:
    relaxed = ORDERING_PRESETS.get(preset, frozenset())
    return run_weighted_selection(
        db,
        ticker=ticker,
        timeframe=timeframe,
        zone=zone,
        vwap_side=vwap_side,
        nearest_above_dist=nearest_above_dist,
        nearest_below_dist=nearest_below_dist,
        n_similar=n_similar,
        as_of_ts_utc=as_of_ts_utc,
        weights=weights,
        relaxed_features=relaxed,
        candidate_pool_cap=candidate_pool_cap,
        variant=f"order_variant:{preset}",
        anchor_overlay=anchor_overlay,
        extra_soft_weights=extra_soft_weights,
    )


CORE_FEATURES = ("zone", "vwap_side", "above_bucket", "below_bucket")


def run_feature_ablations(
    db: Any,
    *,
    ticker: str,
    timeframe: str,
    zone: str,
    vwap_side: str,
    nearest_above_dist: Optional[float],
    nearest_below_dist: Optional[float],
    n_similar: int = 500,
    as_of_ts_utc: Optional[float] = None,
    baseline_run: Optional[AdaptiveShadowRun] = None,
    candidate_pool_cap: int = 5000,
    anchor_overlay: Optional[dict[str, Any]] = None,
    extra_soft_weights: Optional[dict[str, float]] = None,
) -> list[dict[str, Any]]:
    """Remove one scoring feature at a time (weighted mode); compare to full weighted baseline."""
    base = baseline_run or run_weighted_selection(
        db,
        ticker=ticker,
        timeframe=timeframe,
        zone=zone,
        vwap_side=vwap_side,
        nearest_above_dist=nearest_above_dist,
        nearest_below_dist=nearest_below_dist,
        n_similar=n_similar,
        as_of_ts_utc=as_of_ts_utc,
        variant="weighted_full_for_ablation",
        candidate_pool_cap=candidate_pool_cap,
        anchor_overlay=anchor_overlay,
        extra_soft_weights=extra_soft_weights,
    )
    base_ids = set(base.selected_row_ids)
    out: list[dict[str, Any]] = []
    for feat in CORE_FEATURES:
        relaxed = frozenset({feat})
        run = run_weighted_selection(
            db,
            ticker=ticker,
            timeframe=timeframe,
            zone=zone,
            vwap_side=vwap_side,
            nearest_above_dist=nearest_above_dist,
            nearest_below_dist=nearest_below_dist,
            n_similar=n_similar,
            as_of_ts_utc=as_of_ts_utc,
            relaxed_features=relaxed,
            variant=f"ablation_drop_{feat}",
            candidate_pool_cap=candidate_pool_cap,
            anchor_overlay=anchor_overlay,
            extra_soft_weights=extra_soft_weights,
        )
        oid = set(run.selected_row_ids)
        out.append(
            {
                "feature_removed": feat,
                "row_count": len(run.selected_rows),
                "row_count_delta_vs_full_weighted": len(run.selected_rows) - len(base.selected_rows),
                "labeled_counts": run.labeled_counts,
                "tier_stop_viable": run.tier_stop_viable,
                "all_tracked_viable": run.all_tracked_viable,
                "overlap_vs_full_weighted": _overlap_metrics(base_ids, oid),
                "score_distribution": run.score_distribution,
            }
        )
    return out


def shadow_run_to_dict(run: AdaptiveShadowRun) -> dict[str, Any]:
    return {
        "mode": run.mode,
        "variant": run.variant,
        "row_count": len(run.selected_rows),
        "selected_row_ids": run.selected_row_ids,
        "labeled_counts": run.labeled_counts,
        "tier_stop_viable": run.tier_stop_viable,
        "shadow_all_tracked_viable": run.all_tracked_viable,
        "score_distribution": run.score_distribution,
        "weights_used": run.weights_used,
        "relaxed_features": run.relaxed_features,
        "candidate_pool_size": run.candidate_pool_size,
        "extra": run.extra,
    }


def compare_heuristic_to_shadow(
    heuristic_ids: list[Any],
    shadow_run: AdaptiveShadowRun,
    *,
    heuristic_tier_stop_viable: bool,
    heuristic_labeled_counts: dict[str, int],
) -> dict[str, Any]:
    ha = set(heuristic_ids)
    sb = set(shadow_run.selected_row_ids)
    return {
        "schema": "heuristic_shadow_comparison_v1",
        "heuristic": {
            "selected_row_ids": heuristic_ids,
            "row_count": len(heuristic_ids),
            "labeled_counts": dict(heuristic_labeled_counts),
            "tier_stop_viable": heuristic_tier_stop_viable,
        },
        "shadow": shadow_run_to_dict(shadow_run),
        "overlap": _overlap_metrics(ha, sb),
        "widening_note": (
            "Heuristic uses tier widening; shadow uses global pool rank unless baseline_control."
        ),
    }

