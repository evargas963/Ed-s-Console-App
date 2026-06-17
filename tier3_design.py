"""
Tier 3 (market context) design — research / shadow only.

Does not modify production get_similar_setups, Issue 19 tiers, or transport.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from similarity_audit import normalize_anchor_distances_for_issue19_sql
from similarity_feature_search import SHADOW_SOFT_CATEGORICAL_ALLOWLIST, resolve_overlay_for_anchor

SCHEMA_TIER3_INVENTORY = "tier3_context_candidate_inventory_v1"
SCHEMA_TIER3_DESIGN = "tier3_design_comparison_v1"
SCHEMA_TIER3_DECISIONS = "tier3_feature_decisions_v1"
SCHEMA_TIER3_ARCH = "tier3_architecture_proposal_v1"

# Snapshot-backed context fields (categorical / ordinal labels) historically usable for shadow.
# Keys aligned with survivorship REGIME_DEPENDENT + related context; not all are Tier-3 candidates.
_GENERALIZED: list[dict[str, Any]] = [
    {
        "generalized_name": "primary_market_regime",
        "source_fields": ["regime_primary"],
        "snapshot_columns": ["regime_primary"],
        "data_kind": "categorical",
        "historically_usable": True,
        "universal_across_ticker_classes": True,
        "ticker_specific_proxy": False,
        "must_abstract_before_universal_use": False,
        "notes": "regime_engine primary label; same semantics for any primary ticker snapshot row.",
    },
    {
        "generalized_name": "primary_regime_confidence_band",
        "source_fields": ["regime_confidence"],
        "snapshot_columns": ["regime_confidence"],
        "data_kind": "ordinal_band",
        "historically_usable": True,
        "universal_across_ticker_classes": True,
        "ticker_specific_proxy": False,
        "must_abstract_before_universal_use": False,
        "notes": "low/medium/high for regime_primary classification strength.",
    },
    {
        "generalized_name": "market_session_context",
        "source_fields": ["market_session"],
        "snapshot_columns": ["market_session"],
        "data_kind": "categorical",
        "historically_usable": True,
        "universal_across_ticker_classes": True,
        "ticker_specific_proxy": False,
        "must_abstract_before_universal_use": False,
        "notes": "premarket/rth/afterhours/closed — execution liquidity context.",
    },
    {
        "generalized_name": "intraday_session_bucket",
        "source_fields": ["session_bucket"],
        "snapshot_columns": ["session_bucket"],
        "data_kind": "ordinal_bucket",
        "historically_usable": True,
        "universal_across_ticker_classes": True,
        "ticker_specific_proxy": False,
        "must_abstract_before_universal_use": False,
        "notes": "open/morning/midday/afternoon/close — finer intraday context.",
    },
    {
        "generalized_name": "volatility_regime_bucket",
        "source_fields": ["vix_bucket"],
        "snapshot_columns": ["vix_bucket"],
        "data_kind": "ordinal_band",
        "historically_usable": True,
        "universal_across_ticker_classes": True,
        "ticker_specific_proxy": False,
        "must_abstract_before_universal_use": False,
        "notes": "Derived VIX bucket on snapshot; not an external feed in shadow tooling.",
    },
    {
        "generalized_name": "volatility_direction_label",
        "source_fields": ["vix_direction"],
        "snapshot_columns": ["vix_direction"],
        "data_kind": "categorical",
        "historically_usable": True,
        "universal_across_ticker_classes": True,
        "ticker_specific_proxy": False,
        "must_abstract_before_universal_use": False,
        "notes": "rising/falling/flat — secondary to bucket for regime stability.",
    },
    {
        "generalized_name": "risk_regime_small_cap_proxy",
        "source_fields": ["iwm_risk_regime"],
        "snapshot_columns": ["iwm_risk_regime"],
        "data_kind": "categorical",
        "historically_usable": True,
        "universal_across_ticker_classes": False,
        "ticker_specific_proxy": True,
        "must_abstract_before_universal_use": True,
        "notes": "IWM-flavored label on every row; meaningful for small-cap read-through, not a universal filter on SPY primary.",
    },
    {
        "generalized_name": "breadth_risk_sector",
        "source_fields": ["sector_risk_signal"],
        "snapshot_columns": ["sector_risk_signal"],
        "data_kind": "categorical",
        "historically_usable": True,
        "universal_across_ticker_classes": True,
        "ticker_specific_proxy": False,
        "must_abstract_before_universal_use": False,
        "notes": "Sector breadth risk label; may be sparse on some rows.",
    },
    {
        "generalized_name": "breadth_risk_index",
        "source_fields": ["index_risk_signal"],
        "snapshot_columns": ["index_risk_signal"],
        "data_kind": "categorical",
        "historically_usable": True,
        "universal_across_ticker_classes": True,
        "ticker_specific_proxy": False,
        "must_abstract_before_universal_use": False,
        "notes": "Index trio breadth signal; correlated with ETF anchors.",
    },
    {
        "generalized_name": "cross_asset_equity_benchmark_zone",
        "source_fields": ["spy_zone"],
        "snapshot_columns": ["spy_zone"],
        "data_kind": "categorical",
        "historically_usable": True,
        "universal_across_ticker_classes": False,
        "ticker_specific_proxy": True,
        "must_abstract_before_universal_use": True,
        "notes": "SPY zone on row; use as cross-asset context when primary != SPY; do not treat as universal primary regime.",
    },
    {
        "generalized_name": "cross_asset_growth_benchmark_zone",
        "source_fields": ["qqq_zone"],
        "snapshot_columns": ["qqq_zone"],
        "data_kind": "categorical",
        "historically_usable": True,
        "universal_across_ticker_classes": False,
        "ticker_specific_proxy": True,
        "must_abstract_before_universal_use": True,
        "notes": "QQQ zone snapshot column — growth-tech proxy; not a generic regime primitive.",
    },
    {
        "generalized_name": "cross_asset_small_cap_benchmark_zone",
        "source_fields": ["iwm_zone"],
        "snapshot_columns": ["iwm_zone"],
        "data_kind": "categorical",
        "historically_usable": True,
        "universal_across_ticker_classes": False,
        "ticker_specific_proxy": True,
        "must_abstract_before_universal_use": True,
        "notes": "IWM zone on row — small-cap proxy only.",
    },
    {
        "generalized_name": "composite_conviction_band",
        "source_fields": ["combined_conviction"],
        "snapshot_columns": ["combined_conviction"],
        "data_kind": "ordinal_band",
        "historically_usable": True,
        "universal_across_ticker_classes": True,
        "ticker_specific_proxy": False,
        "must_abstract_before_universal_use": False,
        "notes": "Stack conviction; risk of circularity with empirical labels — Tier4 cautious only.",
    },
]


def _validation_evidence() -> dict[str, Any]:
    """Load survivorship validation bundle when present (post overlay-fix)."""
    p = Path("data/survivorship_multi_anchor_20_validation.json")
    if not p.is_file():
        return {"source": "embedded_defaults", "note": "validation JSON absent — use embedded metrics"}
    d = json.loads(p.read_text(encoding="utf-8"))
    tbl = {r["feature"]: r for r in d["survivorship"]["feature_survivorship_table"]}
    pick = lambda k: {
        "classification": tbl.get(k, {}).get("classification"),
        "inclusion_frequency": tbl.get(k, {}).get("inclusion_frequency"),
        "stability_score": tbl.get(k, {}).get("stability_score"),
    }
    return {
        "source": str(p),
        "overlay_failures": len(d["survivorship"].get("failure_anchors_no_matching_overlay") or []),
        "metrics": {k: pick(k) for k in (
            "regime_primary", "regime_confidence", "market_session", "vix_bucket",
            "iwm_risk_regime", "session_bucket", "spy_zone", "qqq_zone", "iwm_zone",
            "sector_risk_signal", "index_risk_signal",
        )},
    }


def build_tier3_candidate_inventory_v1() -> dict[str, Any]:
    allow = sorted(SHADOW_SOFT_CATEGORICAL_ALLOWLIST)
    rows = list(_GENERALIZED)
    inv_names = {r["snapshot_columns"][0] for r in rows}
    other_allowlist = [a for a in allow if a not in inv_names]
    return {
        "schema": SCHEMA_TIER3_INVENTORY,
        "production_authority_note": "Tier 3 is design-only; db.EdDB.get_similar_setups unchanged",
        "candidates": rows,
        "allowlist_columns_not_promoted_to_tier3_inventory_detail": sorted(other_allowlist),
        "evidence_ref": _validation_evidence(),
    }


def build_tier3_design_comparison_v1() -> dict[str, Any]:
    """
    Structured comparison of Tier 3 roles; no production side-effects.
    Scores 1–3 are qualitative rubrics for documentation only.
    """
    return {
        "schema": SCHEMA_TIER3_DESIGN,
        "options": [
            {
                "id": "no_tier3",
                "description": "All context remains Tier 4 soft scoring only.",
                "preserves_structural_integrity": 3,
                "sample_efficiency_viability": 2,
                "cross_anchor_stability": 2,
                "interpretability": 3,
                "cross_ticker_generalization": 3,
                "drawback": "Validated CONDITIONAL context (regime_primary, vix_bucket) under-used; harder to audit context layer.",
            },
            {
                "id": "tier3_context_threshold",
                "description": "Hard or semi-hard gate: cohort restricted when context label mismatches anchor.",
                "preserves_structural_integrity": 2,
                "sample_efficiency_viability": 1,
                "cross_anchor_stability": 2,
                "interpretability": 3,
                "cross_ticker_generalization": 2,
                "drawback": "Risk of tier-stop collapse on sparse labels; needs calibrated thresholds per feature.",
            },
            {
                "id": "tier3_medium_strict_filter",
                "description": "SQL-equivalent extra AND clauses on context columns (mirror Issue 19 tier widening).",
                "preserves_structural_integrity": 2,
                "sample_efficiency_viability": 1,
                "cross_anchor_stability": 2,
                "interpretability": 3,
                "cross_ticker_generalization": 2,
                "drawback": "Same as gate; production change required later — out of scope now.",
            },
            {
                "id": "tier3_hybrid_gate_score",
                "description": "Tier 3A: soft context score in shadow (weighted match). Tier 3B: optional future semi-strict gate after calibration.",
                "preserves_structural_integrity": 3,
                "sample_efficiency_viability": 3,
                "cross_anchor_stability": 3,
                "interpretability": 3,
                "cross_ticker_generalization": 3,
                "drawback": "Two-phase lifecycle; requires Adaptive Shadow v2 to implement 3A first.",
            },
        ],
        "recommended_option_id": "tier3_hybrid_gate_score",
        "recommendation_confidence": "MEDIUM",
        "recommendation_reason": (
            "Post-overlay 20-anchor validation shows CONDITIONAL survival for regime_primary, market_session, "
            "vix_bucket, regime_confidence without collapsing structural tiers; a hard gate would likely "
            "duplicate Issue 19 viability risk. Hybrid matches current adaptive_similarity_engine extra_soft pattern."
        ),
    }


def build_tier3_feature_decisions_v1() -> dict[str, Any]:
    ev = _validation_evidence()
    m = ev.get("metrics") or {}

    def _c(snapshot_col: str, decision: str, role: str, conf: str, reason: str) -> dict[str, Any]:
        meta = m.get(snapshot_col) or {}
        return {
            "snapshot_column": snapshot_col,
            "generalized_name": next(
                (x["generalized_name"] for x in _GENERALIZED if x["snapshot_columns"][0] == snapshot_col),
                snapshot_col,
            ),
            "decision": decision,
            "role": role,
            "confidence": conf,
            "reasoning": reason,
            "validation_metrics": meta,
        }

    decisions = [
        _c(
            "regime_primary",
            "INCLUDE",
            "TIER3_SOFT",
            "MEDIUM",
            f"Survivorship: classification={m.get('regime_primary',{}).get('classification')}, "
            f"inclusion_frequency≈{m.get('regime_primary',{}).get('inclusion_frequency')} — recurrent in top configs.",
        ),
        _c(
            "vix_bucket",
            "INCLUDE",
            "TIER3_SOFT",
            "MEDIUM",
            "Survivorship: volatility_regime_bucket survives CONDITIONAL; universal bucket label.",
        ),
        _c(
            "market_session",
            "INCLUDE",
            "TIER3_SOFT",
            "MEDIUM",
            "Survivorship: market_session CONDITIONAL with highest inclusion among regime dependents in validation run.",
        ),
        _c(
            "regime_confidence",
            "INCLUDE",
            "TIER3_SOFT",
            "MEDIUM",
            "Upgraded from OMIT to CONDITIONAL after overlay fix — previously starved by missing overlays.",
        ),
        _c(
            "session_bucket",
            "OMIT",
            "OMIT",
            "LOW",
            "Survivorship: remains OMIT, inclusion near zero — keep Tier4 exploratory only or withhold until denser coverage.",
        ),
        _c(
            "iwm_risk_regime",
            "INCLUDE",
            "TIER4_ONLY",
            "LOW",
            "Ticker-specific IWM column name; use generalized risk_regime_small_cap_proxy only as read-through / optional small-cap stack, not universal Tier 3.",
        ),
        _c(
            "spy_zone",
            "OMIT",
            "TIER4_ONLY",
            "LOW",
            "Cross-asset SPY zone on row — proxy; do not universalize as Tier3 primitive for all primaries.",
        ),
        _c(
            "qqq_zone",
            "OMIT",
            "TIER4_ONLY",
            "LOW",
            "Growth proxy zone — same rationale as spy_zone.",
        ),
        _c(
            "iwm_zone",
            "OMIT",
            "TIER4_ONLY",
            "LOW",
            "Small-cap proxy zone — same rationale.",
        ),
        _c(
            "sector_risk_signal",
            "OMIT",
            "TIER4_ONLY",
            "LOW",
            "Survivorship OMIT on validation grid; breadth useful but not yet Tier3 without evidence.",
        ),
        _c(
            "index_risk_signal",
            "OMIT",
            "TIER4_ONLY",
            "LOW",
            "Survivorship OMIT on validation grid.",
        ),
        _c(
            "vix_direction",
            "OMIT",
            "TIER4_ONLY",
            "LOW",
            "Survivorship OMIT; subordinate to vix_bucket for volatility regime.",
        ),
        _c(
            "combined_conviction",
            "OMIT",
            "TIER4_ONLY",
            "LOW",
            "Potential circularity with outcome-facing stack; not Tier3 without ablation proof.",
        ),
    ]
    return {
        "schema": SCHEMA_TIER3_DECISIONS,
        "evidence": ev,
        "decisions": decisions,
        "proxy_features_do_not_universalize": [
            "spy_zone",
            "qqq_zone",
            "iwm_zone",
            "iwm_risk_regime",
        ],
        "strong_tier3_shadow_members": [
            "regime_primary",
            "vix_bucket",
            "market_session",
            "regime_confidence",
        ],
    }


def build_final_tier_architecture_proposal_v1() -> dict[str, Any]:
    return {
        "schema": SCHEMA_TIER3_ARCH,
        "production_note": "Tiers 1–2 mirror Issue 19 SQL; Tier 3–4 are shadow / adaptive design only until explicitly promoted.",
        "tiers": {
            "Tier 1": {
                "features": ["zone", "vwap_side"],
                "role": "STRICT_STRUCTURAL_IDENTITY_AND_PIN_PLANE",
                "production_mapping": "Issue 19 tier filters 1–3 active features",
            },
            "Tier 2": {
                "features": ["nearest_above_dist", "nearest_below_dist"],
                "role": "STRICT_DISTANCE_BUCKET_ALIGNED_TO_MATH_EXPOSURE_DIST_BUCKET",
                "production_mapping": "Issue 19 tier filters 1–2 (bucketed distances)",
            },
            "Tier 3": {
                "generalized_features": [
                    {"name": "primary_market_regime", "column": "regime_primary"},
                    {"name": "volatility_regime_bucket", "column": "vix_bucket"},
                    {"name": "market_session_context", "column": "market_session"},
                    {"name": "primary_regime_confidence_band", "column": "regime_confidence"},
                ],
                "role": "CONTEXT_SCORE_LAYER_SHADOW_V2 — categorical soft match with optional future SEMI_STRICT threshold after calibration",
                "implementation_first_step": "adaptive_similarity_engine extra_soft_weights scoped to Tier 3 columns; no SQL changes",
            },
            "Tier 4": {
                "features": [
                    "remaining SHADOW_SOFT allowlist",
                    "order-flow / conviction / cross-asset proxies",
                    "order_variant presets",
                    "ablation / exploration features",
                ],
                "role": "SOFT_ADAPTIVE_SCORING_AND_DIAGNOSTICS",
            },
        },
        "tier3_exists": True,
        "tier3_rationale": (
            "Distinct Tier 3 is justified: validated context features show CONDITIONAL survivorship separate from "
            "structural T1–T2; keeping them only in Tier 4 obscures audit. Initial implementation is soft (TIER3_SOFT) "
            "to preserve viability; semi-strict gate is Phase B."
        ),
    }


def run_tier3_context_probe(
    db: Any,
    *,
    anchors: list[dict[str, Any]],
    tier3_column: str,
    n_similar: int = 35,
    candidate_pool_cap: int = 250,
) -> dict[str, Any]:
    """
    Shadow-only: weighted selection with vs without one Tier 3 extra column; frozen Tier 1/2 via same anchor + weights.
    Deterministic given DB state.
    """
    from adaptive_similarity_engine import run_baseline_control, run_weighted_selection, _overlap_metrics

    if tier3_column not in SHADOW_SOFT_CATEGORICAL_ALLOWLIST:
        raise ValueError("tier3_column not allowlisted for shadow")

    per: list[dict[str, Any]] = []
    for a in anchors:
        aid = a["anchor_id"]
        nad_a, nbd_a = normalize_anchor_distances_for_issue19_sql(
            float(a["nearest_above_dist"]) if a.get("nearest_above_dist") is not None else None,
            float(a["nearest_below_dist"]) if a.get("nearest_below_dist") is not None else None,
        )
        r = resolve_overlay_for_anchor(
            db,
            ticker=a["ticker"],
            timeframe=a["timeframe"],
            zone=a["zone"],
            vwap_side=a["vwap_side"],
            nearest_above_dist=nad_a,
            nearest_below_dist=nbd_a,
        )
        overlay_full = r.get("overlay") or {}
        if tier3_column not in overlay_full:
            per.append(
                {
                    "anchor_id": aid,
                    "skipped": True,
                    "reason": "tier3_column_not_in_overlay",
                }
            )
            continue
        overlay_use = {tier3_column: overlay_full[tier3_column]}
        h = run_baseline_control(
            db,
            ticker=a["ticker"],
            timeframe=a["timeframe"],
            zone=a["zone"],
            vwap_side=a["vwap_side"],
            nearest_above_dist=nad_a,
            nearest_below_dist=nbd_a,
            n_similar=n_similar,
        )
        base_w = run_weighted_selection(
            db,
            ticker=a["ticker"],
            timeframe=a["timeframe"],
            zone=a["zone"],
            vwap_side=a["vwap_side"],
            nearest_above_dist=nad_a,
            nearest_below_dist=nbd_a,
            n_similar=n_similar,
            candidate_pool_cap=candidate_pool_cap,
            variant="tier3_probe_base",
            anchor_overlay=None,
            extra_soft_weights=None,
        )
        t3 = run_weighted_selection(
            db,
            ticker=a["ticker"],
            timeframe=a["timeframe"],
            zone=a["zone"],
            vwap_side=a["vwap_side"],
            nearest_above_dist=nad_a,
            nearest_below_dist=nbd_a,
            n_similar=n_similar,
            candidate_pool_cap=candidate_pool_cap,
            variant=f"tier3_probe_with_{tier3_column}",
            anchor_overlay=overlay_use,
            extra_soft_weights={tier3_column: 1.0},
        )
        hid = set(h.selected_row_ids)
        per.append(
            {
                "anchor_id": aid,
                "skipped": False,
                "heuristic_tier_stop_viable": h.tier_stop_viable,
                "base_weighted_tier_stop_viable": base_w.tier_stop_viable,
                "with_tier3_tier_stop_viable": t3.tier_stop_viable,
                "overlap_base_vs_heuristic": _overlap_metrics(hid, set(base_w.selected_row_ids)),
                "overlap_t3_vs_heuristic": _overlap_metrics(hid, set(t3.selected_row_ids)),
                "overlay_value_used": overlay_use,
            }
        )
    return {
        "schema": "tier3_context_probe_v1",
        "tier3_column": tier3_column,
        "anchors_attempted": len(anchors),
        "per_anchor": per,
    }


def emit_tier3_bundle_json(out_dir: Path) -> None:
    """Write machine-readable design artifacts (optional CLI helper)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "tier3_candidate_inventory_v1.json").write_text(
        json.dumps(build_tier3_candidate_inventory_v1(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (out_dir / "tier3_design_comparison_v1.json").write_text(
        json.dumps(build_tier3_design_comparison_v1(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (out_dir / "tier3_feature_decisions_v1.json").write_text(
        json.dumps(build_tier3_feature_decisions_v1(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (out_dir / "tier3_architecture_proposal_v1.json").write_text(
        json.dumps(build_final_tier_architecture_proposal_v1(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
