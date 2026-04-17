"""
Controlled staged search over shadow similarity (analysis only).

No production authority changes. Uses adaptive_similarity_engine weighted / order presets
and optional categorical soft columns from snapshots (allowlisted).
"""
from __future__ import annotations

from db import (
    get_snapshot_sql,
    sql_overlay_count_zpred,
    sql_overlay_count_zpred_vwap,
    sql_overlay_count_zpred_vwap_bucket,
    sql_overlay_select_star_where,
)

from collections import defaultdict
from typing import Any, Optional

from adaptive_similarity_engine import (
    ORDERING_PRESETS,
    default_equal_weights,
    run_baseline_control,
    run_order_variant,
    run_weighted_selection,
    _overlap_metrics,
)
from math_exposure import bucket_hi, bucket_lo, dist_bucket

SCHEMA_STAGED = "similarity_feature_staged_search_v1"
SCHEMA_DIVERGENCE = "similarity_baseline_divergence_v1"

# Snapshots may omit `pin_neutral`; include it so test DBs / rare rows still match, and expand to directional pin labels.
PIN_FAMILY_ZONES_FOR_NEUTRAL_OVERLAY: tuple[str, ...] = ("pin_neutral", "pin_bull", "pin_bear", "pin_chaos")

# Narrow substitution when a ticker has no history for a zone (overlay row only; structural anchor zone unchanged).
_OVERLAY_ZONE_SUBSTITUTION: dict[tuple[str, str], str] = {
    ("IWM", "pin_bear"): "breakdown",
}

# Categorical snapshot columns permitted for shadow soft scoring (replay-safe TEXT-like).
SHADOW_SOFT_CATEGORICAL_ALLOWLIST: frozenset[str] = frozenset(
    {
        "session_bucket",
        "vix_bucket",
        "regime_primary",
        "regime_confidence",
        "market_session",
        "charm_direction",
        "iv_direction",
        "vix_direction",
        "spy_zone",
        "qqq_zone",
        "iwm_zone",
        "rules_conviction",
        "combined_conviction",
        "level_density_label",
        "sector_risk_signal",
        "index_risk_signal",
        "iwm_risk_regime",
        "rotation_signal",
        "bond_signal",
        "hedging_flow_direction",
        "dpi_direction",
        "last_sweep_type",
        "execution_mode",
    }
)

WEIGHT_BAND_SCALARS: dict[str, float] = {
    "HIGH": 2.0,
    "MEDIUM": 1.0,
    "LOW": 0.5,
    "EXPLORATORY": 0.35,
}


def weights_for_band(band: str) -> dict[str, float]:
    s = WEIGHT_BAND_SCALARS.get(band, 1.0)
    base = default_equal_weights()
    return {k: s for k in base}


def run_staged_shadow_search(
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
    candidate_pool_cap: int = 5000,
    anchor_overlay: Optional[dict[str, Any]] = None,
    extra_soft_candidates: Optional[list[str]] = None,
    search_profile: str = "full",
) -> dict[str, Any]:
    """
    Deterministic grid: weight bands × (full weighted + each order preset) × optional
    single extra soft feature (one at a time). Compares to heuristic baseline_control.

    search_profile:
      - \"full\": all weight bands × all ORDERING_PRESETS (audit / single-anchor)
      - \"multi_anchor\": subset for batch survivorship (faster, still deterministic)
    """
    ticker = (ticker or "").upper().strip()
    if search_profile == "multi_anchor":
        bands = ["MEDIUM", "HIGH", "EXPLORATORY"]
        preset_names = ["", "drop_vwap_first_soft", "drop_zone_last_soft"]
    else:
        bands = ["HIGH", "MEDIUM", "LOW", "EXPLORATORY"]
        preset_names = [""] + sorted(ORDERING_PRESETS.keys())
    extras = [None]
    if extra_soft_candidates:
        for c in sorted(extra_soft_candidates):
            if c in SHADOW_SOFT_CATEGORICAL_ALLOWLIST:
                extras.append(c)

    heuristic = run_baseline_control(
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
    h_ids = set(heuristic.selected_row_ids)

    trials: list[dict[str, Any]] = []
    for band in bands:
        wband = weights_for_band(band)
        for pn in preset_names:
            for extra in extras:
                esw = None
                if extra:
                    esw = {extra: WEIGHT_BAND_SCALARS.get("MEDIUM", 1.0)}
                if pn:
                    run = run_order_variant(
                        db,
                        pn,
                        ticker=ticker,
                        timeframe=timeframe,
                        zone=zone,
                        vwap_side=vwap_side,
                        nearest_above_dist=nearest_above_dist,
                        nearest_below_dist=nearest_below_dist,
                        n_similar=n_similar,
                        as_of_ts_utc=as_of_ts_utc,
                        weights=wband,
                        candidate_pool_cap=candidate_pool_cap,
                        anchor_overlay=anchor_overlay,
                        extra_soft_weights=esw,
                    )
                    trial_key = {"weight_band": band, "ordering_preset": pn, "extra_soft": extra}
                else:
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
                        weights=wband,
                        relaxed_features=frozenset(),
                        candidate_pool_cap=candidate_pool_cap,
                        variant=f"staged:{band}:weighted",
                        anchor_overlay=anchor_overlay,
                        extra_soft_weights=esw,
                    )
                    trial_key = {"weight_band": band, "ordering_preset": None, "extra_soft": extra}
                s_ids = set(run.selected_row_ids)
                trials.append(
                    {
                        "trial_key": trial_key,
                        "row_count": len(run.selected_rows),
                        "labeled_counts": run.labeled_counts,
                        "tier_stop_viable": run.tier_stop_viable,
                        "all_tracked_viable": run.all_tracked_viable,
                        "overlap_vs_heuristic": _overlap_metrics(h_ids, s_ids),
                        "score_mean": run.score_distribution.get("mean"),
                    }
                )

    viable_trials = [t for t in trials if t["tier_stop_viable"]]
    viable_trials.sort(
        key=lambda x: (
            -float(x["overlap_vs_heuristic"]["jaccard"]),
            -x["row_count"],
            str(x["trial_key"]),
        )
    )
    top_robust = viable_trials[: min(12, len(viable_trials))]

    return {
        "schema": SCHEMA_STAGED,
        "search_profile": search_profile,
        "production_authority_note": "shadow only — get_similar_setups unchanged",
        "heuristic_baseline": {
            "row_count": len(heuristic.selected_rows),
            "labeled_counts": heuristic.labeled_counts,
            "tier_stop_viable": heuristic.tier_stop_viable,
        },
        "trial_count": len(trials),
        "trials": trials,
        "top_robust_tier_stop_viable": top_robust,
        "allowlist_extra_soft": sorted(SHADOW_SOFT_CATEGORICAL_ALLOWLIST),
    }


def analyze_baseline_feature_outcome_divergence(
    db: Any,
    *,
    ticker: str,
    timeframe: str,
    min_group_size: int = 8,
    max_groups_report: int = 40,
) -> dict[str, Any]:
    """
    Groups rows by (zone, vwap_side, nearest_above bucket, nearest_below bucket).
    Flags groups with multiple distinct outcome_15c values (historical ambiguity).
    """
    from snapshot_access import require_snapshot_timeframe

    timeframe = require_snapshot_timeframe(
        timeframe, caller="analyze_baseline_feature_outcome_divergence"
    )
    ticker = (ticker or "").upper().strip()
    with db._connect() as conn:
        rows = conn.execute(
            get_snapshot_sql("similarity_feature_search.py:229"),
            (ticker, timeframe),
        ).fetchall()
    groups: dict[tuple[Any, ...], list[dict]] = defaultdict(list)
    for r in rows:
        rd = dict(r)
        z = rd.get("zone")
        vs = rd.get("vwap_side")
        ab = dist_bucket(rd.get("nearest_above_dist"))
        bb = dist_bucket(rd.get("nearest_below_dist"))
        key = (z, vs, ab, bb)
        groups[key].append(rd)

    ambiguous: list[dict[str, Any]] = []
    for key, lst in groups.items():
        if len(lst) < min_group_size:
            continue
        outs = {str(x.get("outcome_15c")) for x in lst if x.get("outcome_15c")}
        if len(outs) < 2:
            continue
        by_reg = defaultdict(set)
        for x in lst:
            rp = x.get("regime_primary")
            o = x.get("outcome_15c")
            if o is not None:
                by_reg[str(rp)].add(str(o))
        regime_splits = sum(1 for s in by_reg.values() if len(s) == 1)
        ambiguous.append(
            {
                "group_key": {
                    "zone": key[0],
                    "vwap_side": key[1],
                    "nearest_above_dist_bucket": key[2],
                    "nearest_below_dist_bucket": key[3],
                },
                "row_count": len(lst),
                "distinct_outcome_15c": sorted(outs),
                "regime_primary_values_observed": sorted({str(x.get("regime_primary")) for x in lst}),
                "hint_regime_splits_outcome": regime_splits,
            }
        )
    ambiguous.sort(key=lambda x: (-x["row_count"], -len(x["distinct_outcome_15c"])))
    ambiguous = ambiguous[:max_groups_report]

    return {
        "schema": SCHEMA_DIVERGENCE,
        "ticker": ticker,
        "timeframe": timeframe,
        "min_group_size": min_group_size,
        "ambiguous_baseline_groups": ambiguous,
        "notes": (
            "Ambiguous groups share current baseline structural keys but disagree on outcome_15c; "
            "candidate explainers include regime_primary / session_bucket / vix_bucket (see per-group hints)."
        ),
    }


def synthesize_per_feature_recommendations(
    inventory_partitions: dict[str, Any],
    staged: dict[str, Any],
    divergence: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Rule-based synthesis for audit JSON — not production policy."""
    recs: list[dict[str, Any]] = []
    baseline = sorted(
        {"zone", "vwap_side", "nearest_above_dist", "nearest_below_dist"}
    )
    for name in baseline:
        recs.append(
            {
                "feature_name": name,
                "decision": "KEEP",
                "recommended_role": "EARLY_STRICT"
                if name in ("zone", "vwap_side")
                else "MID_STRICT",
                "recommended_weight_band": "HIGH" if name == "zone" else "MEDIUM",
                "confidence": "STRONG",
                "evidence_summary": "Enforced by Issue 19 tier SQL + baseline_feature_contract_v1.",
            }
        )

    trials = staged.get("trials") or []
    extra_survival: dict[str, list[float]] = defaultdict(list)
    for t in trials:
        ex = (t.get("trial_key") or {}).get("extra_soft")
        if not ex:
            continue
        j = float((t.get("overlap_vs_heuristic") or {}).get("jaccard") or 0.0)
        if t.get("tier_stop_viable"):
            extra_survival[ex].append(j)

    historic = set(inventory_partitions.get("HISTORICALLY_USABLE_CANDIDATES") or [])
    for feat in sorted(SHADOW_SOFT_CATEGORICAL_ALLOWLIST & historic):
        if feat in baseline:
            continue
        js = extra_survival.get(feat, [])
        if not js:
            recs.append(
                {
                    "feature_name": feat,
                    "decision": "ADD_SHADOW_ONLY",
                    "recommended_role": "SOFT_WEIGHT",
                    "recommended_weight_band": "EXPLORATORY",
                    "confidence": "WEAK / EXPERIMENTAL",
                    "evidence_summary": "Allowlisted for shadow soft scoring; no staged trial without anchor_overlay value.",
                }
            )
            continue
        mean_j = sum(js) / len(js)
        recs.append(
            {
                "feature_name": feat,
                "decision": "ADD_SHADOW_ONLY",
                "recommended_role": "REGIME_DEPENDENT"
                if feat in ("regime_primary", "vix_bucket", "session_bucket")
                else "SOFT_WEIGHT",
                "recommended_weight_band": "LOW"
                if mean_j > 0.85
                else "MEDIUM",
                "confidence": "MODERATE" if len(js) >= 4 else "WEAK / EXPERIMENTAL",
                "evidence_summary": (
                    f"Staged shadow trials with this extra soft feature: mean Jaccard vs heuristic={round(mean_j, 4)}, "
                    f"n_trials={len(js)}."
                ),
            }
        )

    if divergence:
        amb = divergence.get("ambiguous_baseline_groups") or []
        if amb:
            recs.append(
                {
                    "feature_name": "_aggregate_divergence",
                    "decision": "ANALYSIS_NOTE",
                    "recommended_role": "N/A",
                    "recommended_weight_band": "N/A",
                    "confidence": "MODERATE",
                    "evidence_summary": (
                        f"{len(amb)} baseline-key groups show multiple outcome_15c values — "
                        "review regime/session/VIX context as missing-signal candidates."
                    ),
                }
            )

    return {
        "schema": "similarity_per_feature_recommendations_v1",
        "recommendations": sorted(recs, key=lambda x: x["feature_name"]),
    }


def anchor_overlay_from_snapshot_row(row: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Subset of snapshot columns for shadow soft scoring."""
    if not row:
        return {}
    out: dict[str, Any] = {}
    for k in SHADOW_SOFT_CATEGORICAL_ALLOWLIST:
        v = row.get(k)
        if v is not None and str(v).strip() != "":
            out[k] = v
    return out


def latest_snapshot_as_anchor_overlay(
    db: Any,
    ticker: str,
    timeframe: str,
    *,
    as_of_ts_utc: Optional[float] = None,
) -> dict[str, Any]:
    """Anchor overlay from the newest snapshot row with ``ts_utc < as_of_ts_utc`` when set.

    ``as_of_ts_utc=None`` keeps legacy behavior: newest row in the DB (live-tail / offline tools).
    For replay at decision time T, pass ``as_of_ts_utc=T`` so the anchor cannot come from the future.
    """
    rows = db.get_recent_snapshots(
        (ticker or "").upper().strip(),
        timeframe,
        n=1,
        as_of_ts_utc=as_of_ts_utc,
    )
    return anchor_overlay_from_snapshot_row(rows[0] if rows else None)


def _overlay_bucket_clauses(
    nearest_above_dist: Optional[float],
    nearest_below_dist: Optional[float],
) -> tuple[str, list[Any]]:
    """SQL fragments aligned with Issue 19 bucket intervals (null-aligned)."""
    parts: list[str] = []
    params: list[Any] = []
    if nearest_above_dist is None:
        parts.append("nearest_above_dist IS NULL")
    else:
        b = dist_bucket(float(nearest_above_dist))
        lo, hi = bucket_lo(b), bucket_hi(b)
        parts.append("nearest_above_dist BETWEEN ? AND ?")
        params.extend([lo, hi])
    if nearest_below_dist is None:
        parts.append("nearest_below_dist IS NULL")
    else:
        b = dist_bucket(float(nearest_below_dist))
        lo, hi = bucket_lo(b), bucket_hi(b)
        parts.append("nearest_below_dist BETWEEN ? AND ?")
        params.extend([lo, hi])
    return " AND ".join(parts), params


def _zone_predicate_for_overlay_lookup(
    ticker: str,
    zone: str,
) -> tuple[str, list[str], str]:
    """
    Returns (SQL boolean expr for zone column, bind values, note).
    Cohort `zone` in anchors is unchanged elsewhere; this is overlay-row lookup only.
    """
    t = (ticker or "").upper().strip()
    z = (zone or "").strip()
    sub = _OVERLAY_ZONE_SUBSTITUTION.get((t, z))
    if sub:
        return "zone = ?", [sub], f"overlay_zone_substitution:{z}->{sub}"
    if z == "pin_neutral":
        ph = ",".join("?" * len(PIN_FAMILY_ZONES_FOR_NEUTRAL_OVERLAY))
        return f"zone IN ({ph})", list(PIN_FAMILY_ZONES_FOR_NEUTRAL_OVERLAY), "pin_neutral_expanded_to_pin_family"
    return "zone = ?", [z], "exact_zone"


def diagnose_overlay_match_counts(
    db: Any,
    *,
    ticker: str,
    timeframe: str,
    zone: str,
    vwap_side: str,
    nearest_above_dist: Optional[float] = None,
    nearest_below_dist: Optional[float] = None,
) -> dict[str, Any]:
    """Counts at each filter stage for root-cause reporting (read-only)."""
    from snapshot_access import require_snapshot_timeframe

    timeframe = require_snapshot_timeframe(timeframe, caller="diagnose_overlay_match_counts")
    t = (ticker or "").upper().strip()
    vs = (vwap_side or "").strip()
    z = (zone or "").strip()
    stages: list[dict[str, Any]] = []
    with db._connect() as conn:
        n_tf = conn.execute(
            get_snapshot_sql("similarity_feature_search.py:467"),
            (t, timeframe),
        ).fetchone()[0]
        stages.append({"stage": "ticker_timeframe_outcome_1c", "count": n_tf})
        n3 = conn.execute(
            get_snapshot_sql("similarity_feature_search.py:472"),
            (t, timeframe, z),
        ).fetchone()[0]
        stages.append({"stage": "plus_exact_zone", "count": n3})
        n4 = conn.execute(
            get_snapshot_sql("similarity_feature_search.py:477"),
            (t, timeframe, z, vs),
        ).fetchone()[0]
        stages.append({"stage": "plus_vwap_side_exact_zone", "count": n4})
        zpred, zvals, _ = _zone_predicate_for_overlay_lookup(t, z)
        n5 = conn.execute(
            sql_overlay_count_zpred(zpred),
            (t, timeframe, *zvals),
        ).fetchone()[0]
        stages.append({"stage": "plus_resolved_zone_predicate", "count": n5})
        n6 = conn.execute(
            sql_overlay_count_zpred_vwap(zpred),
            (t, timeframe, *zvals, vs),
        ).fetchone()[0]
        stages.append({"stage": "plus_vwap_resolved_zone", "count": n6})
        bsql, bparams = _overlay_bucket_clauses(nearest_above_dist, nearest_below_dist)
        n7 = conn.execute(
            sql_overlay_count_zpred_vwap_bucket(zpred, bsql),
            (t, timeframe, *zvals, vs, *bparams),
        ).fetchone()[0]
        stages.append({"stage": "plus_distance_buckets_resolved_zone", "count": n7})

    first_zero = next((s["stage"] for s in stages if s["count"] == 0), None)
    return {
        "schema": "overlay_match_count_diagnosis_v1",
        "ticker": t,
        "timeframe": timeframe,
        "zone": z,
        "vwap_side": vs,
        "nearest_above_dist": nearest_above_dist,
        "nearest_below_dist": nearest_below_dist,
        "stages": stages,
        "first_zero_count_stage": first_zero,
    }


def matching_snapshot_overlay_for_anchor(
    db: Any,
    *,
    ticker: str,
    timeframe: str,
    zone: str,
    vwap_side: str,
    nearest_above_dist: Optional[float] = None,
    nearest_below_dist: Optional[float] = None,
) -> dict[str, Any]:
    """
    Replay-safe overlay for shadow soft features: most recent row matching resolved zone
    (pin_neutral → pin family in DB), optional ticker-specific zone substitution, vwap_side,
    and nearest_* distance buckets when distances are provided.
    """
    res = resolve_overlay_for_anchor(
        db,
        ticker=ticker,
        timeframe=timeframe,
        zone=zone,
        vwap_side=vwap_side,
        nearest_above_dist=nearest_above_dist,
        nearest_below_dist=nearest_below_dist,
    )
    return res.get("overlay") or {}


def resolve_overlay_for_anchor(
    db: Any,
    *,
    ticker: str,
    timeframe: str,
    zone: str,
    vwap_side: str,
    nearest_above_dist: Optional[float] = None,
    nearest_below_dist: Optional[float] = None,
) -> dict[str, Any]:
    """
    Overlay dict + resolution audit trail. Does not change similarity cohort parameters.
    """
    from snapshot_access import require_snapshot_timeframe

    timeframe = require_snapshot_timeframe(timeframe, caller="matching_snapshot_overlay_for_anchor")
    t = (ticker or "").upper().strip()
    vs = (vwap_side or "").strip()
    zpred, zvals, znote = _zone_predicate_for_overlay_lookup(ticker, zone)
    tries: list[dict[str, Any]] = []
    row = None
    with db._connect() as conn:
        for attempt, use_bucket in enumerate((True, False), start=1):
            if use_bucket and nearest_above_dist is None and nearest_below_dist is None:
                continue
            parts = [
                "ticker = ?",
                "timeframe = ?",
                f"({zpred})",
                "vwap_side = ?",
                "outcome_1c IS NOT NULL",
            ]
            params: list[Any] = [t, timeframe, *zvals, vs]
            if use_bucket:
                bsql, bparams = _overlay_bucket_clauses(nearest_above_dist, nearest_below_dist)
                parts.append(f"({bsql})")
                params.extend(bparams)
            cur = conn.execute(sql_overlay_select_star_where(" AND ".join(parts)), tuple(params))
            row = cur.fetchone()
            tries.append(
                {
                    "attempt": attempt,
                    "use_distance_buckets": use_bucket,
                    "zone_resolution": znote,
                    "matched": row is not None,
                }
            )
            if row is not None:
                break

    out_row = dict(row) if row else None
    return {
        "overlay": anchor_overlay_from_snapshot_row(out_row),
        "resolution": {
            "zone_lookup_note": znote,
            "cohort_zone_unchanged": (zone or "").strip(),
            "tries": tries,
            "selected_snapshot_id": out_row.get("snapshot_id") if out_row else None,
        },
    }
