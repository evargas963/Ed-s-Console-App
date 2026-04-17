"""
Multi-anchor survivorship aggregation for shadow similarity (analysis only).

Does not modify production heuristics or Issue 19 thresholds.
"""
from __future__ import annotations

from db import get_snapshot_sql


from collections import Counter, defaultdict
from typing import Any, Optional

from similarity_audit import normalize_anchor_distances_for_issue19_sql
from similarity_feature_search import (
    SHADOW_SOFT_CATEGORICAL_ALLOWLIST,
    resolve_overlay_for_anchor,
    run_staged_shadow_search,
)
from timeframe_config import CANONICAL_TIMEFRAME

SCHEMA_SURVIVORSHIP = "similarity_feature_survivorship_v1"

REGIME_DEPENDENT_FEATURES: frozenset[str] = frozenset(
    {
        "regime_primary",
        "regime_confidence",
        "vix_bucket",
        "session_bucket",
        "market_session",
        "iwm_risk_regime",
    }
)

STRUCTURAL_FEATURE_ROLES: dict[str, str] = {
    "zone": "EARLY_STRICT",
    "vwap_side": "EARLY_STRICT",
    "nearest_above_dist": "MID_STRICT",
    "nearest_below_dist": "MID_STRICT",
}

STRUCTURAL_WEIGHT_BAND = "HIGH"


def default_multi_anchor_set_v1(
    *,
    extra_tickers: Optional[list[str]] = None,
    timeframe: str = "1m",
) -> list[dict[str, Any]]:
    """
    Reproducible anchor set (minimum 12 with tickers SPY+QQQ only).
    When extra_tickers provided, extends to 20 anchors (4 tickers × 5 structural combos + 4 × 1).
    """
    # Non-negative magnitudes — matches Issue 19 BETWEEN intervals + dist_bucket(abs).
    tier_specs: list[tuple[str, str, float, float, str]] = [
        ("pin_neutral", "above", 1.0, 1.0, "near_sym"),
        ("pin_neutral", "below", 1.0, 1.0, "near_sym_below"),
        ("pin_bull", "above", 0.5, 2.0, "asym_bear"),
        ("pin_bear", "below", 2.0, 0.5, "asym_bull"),
        ("breakout", "above", 0.25, 5.0, "wide_below"),
        ("breakdown", "below", 5.0, 0.25, "wide_above"),
    ]
    tickers = ["SPY", "QQQ"]
    if extra_tickers:
        for t in extra_tickers:
            u = (t or "").upper().strip()
            if u and u not in tickers:
                tickers.append(u)

    anchors: list[dict[str, Any]] = []
    # Wave 1: first two tickers × all zone specs → 12
    for ti in tickers[:2]:
        for idx, (z, vs, nad, nbd, tag) in enumerate(tier_specs):
            nad_n, nbd_n = normalize_anchor_distances_for_issue19_sql(nad, nbd)
            anchors.append(
                {
                    "anchor_id": f"{ti}__{z}__{vs}__{tag}",
                    "ticker": ti,
                    "timeframe": timeframe,
                    "zone": z,
                    "vwap_side": vs,
                    "nearest_above_dist": nad_n,
                    "nearest_below_dist": nbd_n,
                    "structural_tag": tag,
                }
            )

    # Wave 2: tickers 2–3 × first 4 specs → +8 when 4 tickers total
    if len(tickers) >= 4:
        for ti in tickers[2:4]:
            for z, vs, nad, nbd, tag in tier_specs[:4]:
                nad_n, nbd_n = normalize_anchor_distances_for_issue19_sql(nad, nbd)
                anchors.append(
                    {
                        "anchor_id": f"{ti}__{z}__{vs}__{tag}",
                        "ticker": ti,
                        "timeframe": timeframe,
                        "zone": z,
                        "vwap_side": vs,
                        "nearest_above_dist": nad_n,
                        "nearest_below_dist": nbd_n,
                        "structural_tag": tag,
                    }
                )
    return anchors


def discover_tickers_for_survivorship(
    db: Any,
    *,
    min_rows: int = 500,
    max_extra: int = 2,
) -> list[str]:
    with db._connect() as conn:
        rows = conn.execute(
            get_snapshot_sql("similarity_feature_survivorship.py:112"),
            (CANONICAL_TIMEFRAME, min_rows),
        ).fetchall()
    out = []
    for r in rows:
        t = str(r[0]).upper().strip()
        if t in ("SPY", "QQQ"):
            continue
        out.append(t)
        if len(out) >= max_extra:
            break
    return out


def _infer_role_for_extra(feature: str) -> str:
    if feature in REGIME_DEPENDENT_FEATURES:
        return "REGIME_DEPENDENT"
    return "SOFT_WEIGHT"


def _top_k_trial_keys(
    staged: dict[str, Any],
    *,
    k: int,
) -> list[dict[str, Any]]:
    tops = staged.get("top_robust_tier_stop_viable") or []
    out = []
    for t in tops[:k]:
        out.append(t.get("trial_key") or {})
    return out


def run_multi_anchor_survivorship(
    db: Any,
    *,
    anchors: list[dict[str, Any]],
    n_similar: int = 250,
    candidate_pool_cap: int = 1500,
    top_k: int = 5,
    as_of_ts_utc: Optional[float] = None,
    max_extra_soft_per_anchor: int = 8,
) -> dict[str, Any]:
    per_anchor: list[dict[str, Any]] = []
    extra_in_top: dict[str, list[str]] = defaultdict(list)
    extra_roles_when_top: dict[str, list[str]] = defaultdict(list)
    extra_weights_when_top: dict[str, list[str]] = defaultdict(list)
    overlay_had_key: dict[str, list[str]] = defaultdict(list)
    failure_no_overlay: list[str] = []
    failure_not_viable: list[str] = []

    for a in anchors:
        aid = a["anchor_id"]
        nad_a, nbd_a = normalize_anchor_distances_for_issue19_sql(
            float(a["nearest_above_dist"]) if a.get("nearest_above_dist") is not None else None,
            float(a["nearest_below_dist"]) if a.get("nearest_below_dist") is not None else None,
        )
        resolved = resolve_overlay_for_anchor(
            db,
            ticker=a["ticker"],
            timeframe=a["timeframe"],
            zone=a["zone"],
            vwap_side=a["vwap_side"],
            nearest_above_dist=nad_a,
            nearest_below_dist=nbd_a,
        )
        overlay = resolved.get("overlay") or {}
        raw_keys = sorted(overlay.keys()) if overlay else []
        reg_first = [k for k in raw_keys if k in REGIME_DEPENDENT_FEATURES]
        rest = [k for k in raw_keys if k not in REGIME_DEPENDENT_FEATURES]
        full_keys = reg_first + rest
        if not overlay:
            failure_no_overlay.append(aid)
        candidates = None
        if full_keys:
            candidates = (
                full_keys[:max_extra_soft_per_anchor]
                if max_extra_soft_per_anchor > 0
                else full_keys
            )

        for fk in full_keys:
            overlay_had_key[fk].append(aid)

        staged = run_staged_shadow_search(
            db,
            ticker=a["ticker"],
            timeframe=a["timeframe"],
            zone=a["zone"],
            vwap_side=a["vwap_side"],
            nearest_above_dist=nad_a,
            nearest_below_dist=nbd_a,
            n_similar=n_similar,
            as_of_ts_utc=as_of_ts_utc,
            candidate_pool_cap=candidate_pool_cap,
            anchor_overlay=overlay or None,
            extra_soft_candidates=candidates,
            search_profile="multi_anchor",
        )
        hb = staged.get("heuristic_baseline") or {}
        if not hb.get("tier_stop_viable"):
            failure_not_viable.append(aid)

        tops = _top_k_trial_keys(staged, k=top_k)
        seen_extras: set[str] = set()
        for tk in tops:
            ex = tk.get("extra_soft")
            if ex:
                seen_extras.add(ex)
                role = _infer_role_for_extra(ex)
                wb = tk.get("weight_band") or ""
                extra_in_top[ex].append(aid)
                extra_roles_when_top[ex].append(role)
                extra_weights_when_top[ex].append(wb)

        per_anchor.append(
            {
                "anchor_id": aid,
                "anchor": {
                    **{k: a[k] for k in a if k not in ("anchor_id", "nearest_above_dist", "nearest_below_dist")},
                    "nearest_above_dist": nad_a,
                    "nearest_below_dist": nbd_a,
                },
                "overlay_keys": sorted(overlay.keys()),
                "overlay_empty": not bool(overlay),
                "overlay_resolution": resolved.get("resolution"),
                "heuristic_baseline": hb,
                "trial_count": staged.get("trial_count"),
                "top_trial_keys": tops,
                "best_jaccard": float(
                    (staged.get("top_robust_tier_stop_viable") or [{}])[0]
                    .get("overlap_vs_heuristic", {})
                    .get("jaccard")
                    or 0.0
                ),
            }
        )

    n_anchors = len(anchors)
    table: list[dict[str, Any]] = []

    for fname, role in STRUCTURAL_FEATURE_ROLES.items():
        table.append(
            {
                "feature": fname,
                "inclusion_frequency": 1.0,
                "eligible_anchor_count": n_anchors,
                "included_anchor_count": n_anchors,
                "role_frequency": {role: 1.0},
                "weight_frequency": {STRUCTURAL_WEIGHT_BAND: 1.0},
                "stability_score": 1.0,
                "failure_cases": [],
                "classification": "ROBUST_CORE",
            }
        )

    extras = sorted(SHADOW_SOFT_CATEGORICAL_ALLOWLIST)
    for feat in extras:
        elig = overlay_had_key.get(feat, [])
        n_elig = len(set(elig))
        incl_anchors = sorted(set(extra_in_top.get(feat, [])))
        n_incl = len(incl_anchors)
        inc_freq = (n_incl / n_elig) if n_elig else 0.0
        stab = (n_incl / n_anchors) if n_anchors else 0.0

        roles = extra_roles_when_top.get(feat, [])
        rc: Counter[str] = Counter(roles)
        role_freq = {k: round(v / len(roles), 4) for k, v in rc.items()} if roles else {}

        ws = extra_weights_when_top.get(feat, [])
        wc: Counter[str] = Counter(ws)
        w_freq = {k: round(v / len(ws), 4) for k, v in wc.items()} if ws else {}

        failures = sorted(set(elig) - set(incl_anchors))

        if n_elig == 0:
            cls = "OMIT"
        elif inc_freq >= 0.65 and n_elig >= 6:
            cls = "ROBUST_CORE"
        elif inc_freq >= 0.55 and stab >= 0.35:
            cls = "CONDITIONAL"
        elif inc_freq >= 0.2:
            cls = "WEAK"
        else:
            cls = "OMIT"

        if feat in REGIME_DEPENDENT_FEATURES and cls == "WEAK" and inc_freq >= 0.15:
            cls = "CONDITIONAL"

        table.append(
            {
                "feature": feat,
                "inclusion_frequency": round(inc_freq, 4),
                "eligible_anchor_count": n_elig,
                "included_anchor_count": n_incl,
                "role_frequency": role_freq,
                "weight_frequency": w_freq,
                "stability_score": round(stab, 4),
                "failure_cases": failures,
                "classification": cls,
            }
        )

    return {
        "schema": SCHEMA_SURVIVORSHIP,
        "production_authority_unchanged": True,
        "anchor_count": n_anchors,
        "top_k_per_anchor": top_k,
        "per_anchor": per_anchor,
        "failure_anchors_no_matching_overlay": sorted(set(failure_no_overlay)),
        "failure_anchors_heuristic_not_tier_stop_viable": sorted(set(failure_not_viable)),
        "feature_survivorship_table": sorted(table, key=lambda x: (-x["stability_score"], x["feature"])),
    }


def final_structure_from_survivorship(report: dict[str, Any]) -> dict[str, Any]:
    """Derive EARLY/MID/LATE/SOFT/REGIME buckets from survivorship table."""
    early: list[str] = []
    mid: list[str] = []
    late: list[str] = []
    soft: list[str] = []
    reg: list[str] = []
    remove: list[str] = []
    add: list[str] = []
    regime_aware: list[str] = []

    for row in report.get("feature_survivorship_table", []):
        f = row["feature"]
        cls = row["classification"]
        if f in STRUCTURAL_FEATURE_ROLES:
            if STRUCTURAL_FEATURE_ROLES[f] == "EARLY_STRICT":
                early.append(f)
            else:
                mid.append(f)
            continue
        if cls == "OMIT":
            remove.append(f)
            continue
        role = _infer_role_for_extra(f)
        if role == "REGIME_DEPENDENT":
            reg.append(f)
            regime_aware.append(f)
            if cls in ("CONDITIONAL", "ROBUST_CORE"):
                add.append(f)
        else:
            soft.append(f)
            if cls in ("CONDITIONAL", "ROBUST_CORE"):
                add.append(f)

    return {
        "EARLY_STRICT": sorted(set(early)),
        "MID_STRICT": sorted(set(mid)),
        "LATE_STRICT": sorted(set(late)),
        "SOFT_WEIGHT": sorted(set(soft)),
        "REGIME_DEPENDENT": sorted(set(reg)),
        "features_to_remove_shadow_only": sorted(set(remove)),
        "features_to_add_shadow_only": sorted(set(add)),
        "regime_aware_handling": sorted(set(regime_aware)),
    }


def overall_confidence(report: dict[str, Any]) -> str:
    n = report.get("anchor_count", 0)
    no_ov = len(report.get("failure_anchors_no_matching_overlay") or [])
    nv = len(report.get("failure_anchors_heuristic_not_tier_stop_viable") or [])
    bad = no_ov + nv
    if n >= 16 and bad <= 2:
        return "HIGH"
    if n >= 12 and bad <= max(4, n // 4):
        return "MEDIUM"
    return "LOW"
