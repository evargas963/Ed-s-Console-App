"""
L1 Tier B — decision-relevant field taxonomy (Issue 47).

Single source for: which inputs drive Tier B / L1 decisions, fingerprint material paths,
and runtime classification of payload top-level keys (drift warnings).
"""

from __future__ import annotations

import logging
from typing import Any, Final, Mapping

from planes.context_light import _ORDER_FLOW_KEYS, _STRUCTURAL_KEYS

log = logging.getLogger("ed.planes.l1_decision_dependencies")

# --- Scalars: quote overlay + contract + merge facts (must match l1_fingerprint_material) ---
L1_DECISION_SCALAR_KEYS: Final[tuple[str, ...]] = (
    "plane",
    "schema_version",
    "merge_rule",
    "l1_generation",
    "l2_snapshot_version_used",
    "l2_merge_acknowledged",
    "l2_structural_scope_exact",
    "structural_context_stale",
    "l1_stale",
    "spot",
    "bid",
    "ask",
    "spot_disp",
    "bid_disp",
    "ask_disp",
    "spread",
    "spread_pts",
    "quote_ingestion",
    "ticker",
    "selected_exp",
)

L1_DECISION_SPOT_ANCHORS_KEYS: Final[tuple[str, ...]] = ("vwap", "vwap_side", "dist_to_vwap_pts")

L1_DECISION_LIQUIDITY_SUMMARY_KEYS: Final[tuple[str, ...]] = (
    "behavior_label",
    "absorption_score",
    "continuation_score",
)

L1_DECISION_READINESS_SUMMARY_KEYS: Final[tuple[str, ...]] = (
    "order_flow_readiness",
    "structural_anchor_stale",
    "has_acknowledged_l2_snapshot",
)

# Authoritative grouped view (API for tooling / tests).
L1_DECISION_DEPENDENCY_KEYS: Final[dict[str, tuple[str, ...]]] = {
    "scalars": L1_DECISION_SCALAR_KEYS,
    "structural": _STRUCTURAL_KEYS,
    "order_flow": _ORDER_FLOW_KEYS,
    "spot_anchors": L1_DECISION_SPOT_ANCHORS_KEYS,
    "liquidity_summary": L1_DECISION_LIQUIDITY_SUMMARY_KEYS,
    "readiness_summary": L1_DECISION_READINESS_SUMMARY_KEYS,
}

# Fingerprint path ids (section:key) permitted only when not decision-classified; keep minimal.
L1_ALLOWED_FINGERPRINT_EXTRA_KEYS: Final[frozenset[str]] = frozenset(
    {
        # Add ONLY if truly required (likely empty initially)
    }
)


def get_all_decision_dependency_keys() -> frozenset[str]:
    """
    Canonical material path ids: section:key, aligned with fingerprint material dict layout.
    Sections: scalars, structural, order_flow, spot_anchors, liquidity_summary, readiness_summary.
    """
    out: set[str] = set()
    for k in L1_DECISION_SCALAR_KEYS:
        out.add(f"scalars:{k}")
    for k in _STRUCTURAL_KEYS:
        out.add(f"structural:{k}")
    for k in _ORDER_FLOW_KEYS:
        out.add(f"order_flow:{k}")
    for k in L1_DECISION_SPOT_ANCHORS_KEYS:
        out.add(f"spot_anchors:{k}")
    for k in L1_DECISION_LIQUIDITY_SUMMARY_KEYS:
        out.add(f"liquidity_summary:{k}")
    for k in L1_DECISION_READINESS_SUMMARY_KEYS:
        out.add(f"readiness_summary:{k}")
    return frozenset(out)


def get_fingerprint_material_key_paths() -> frozenset[str]:
    """Paths included in SHA fingerprint input; must match build_l1_material_dict_for_fingerprint."""
    return get_all_decision_dependency_keys()


# Top-level keys that may appear on L1 payloads but are intentionally non-fingerprint
# (timing, diagnostics, duplicates, HTTP cache metadata). Update when build_l1_context / server adds keys.
L1_KNOWN_NON_MATERIAL_TOP_LEVEL_KEYS: Final[frozenset[str]] = frozenset(
    {
        "as_of_ts",
        "as_of_iso",
        "l1_pipeline_ms",
        "l2_analytics_refresh_in_progress",
        "l2_snapshot_ts_used_iso",
        "order_flow_as_of_ts",
        "liquidity_behavior_summary",
        "tier_b_structural",
        "_tier",
        "_endpoint",
        "_server_build_ts",
        "_pipeline_ms",
        "b_light_generated_at",
        "b_light_age_sec",
        "b_structural_source_ts",
        "b_structural_age_sec",
        "b_structural_stale",
        "b_order_flow_live",
        "vwap",
        "vwap_side",
        "dist_to_vwap_pts",
        "structural_context_age_sec",
        "_l1_input_fingerprint",
        "_l1_of_signature",
        "l1_instrumentation",
        "l1_projection",
        "order_flow_age_sec",
        "order_flow_stale",
        "quote_overlay_age_sec",
        "quote_live_overlay_applied",
        "_live_plane_fast_ts",
        "_quote_authority",
        "l1_live_overlay_applied",
        "quote_mid",
        "mid_source",
        "spread_source",
        "spread_pts_source",
        "kl_gamma_voids",
    }
)


def _material_top_level_key_names() -> frozenset[str]:
    """Top-level payload keys that participate in fingerprint extraction (containers + scalar names + structural)."""
    return (
        frozenset(L1_DECISION_SCALAR_KEYS)
        | frozenset(_STRUCTURAL_KEYS)
        | frozenset({"spot_anchors", "order_flow", "liquidity_summary", "readiness_summary"})
    )


def warn_l1_payload_key_drift(payload: Mapping[str, Any], *, logger: logging.Logger | None = None) -> list[str]:
    """
    Log a warning for each top-level key on the payload that is neither fingerprinted nor
    in the known non-material allowlist — indicates a new field was added without updating
    taxonomy (decision deps, fingerprint, or KNOWN_NON_MATERIAL).

    Returns the list of unclassified keys (empty if none).
    """
    lg = logger or log
    top = frozenset(payload.keys())
    classified = _material_top_level_key_names() | L1_KNOWN_NON_MATERIAL_TOP_LEVEL_KEYS
    drift = sorted(top - classified)
    if drift:
        lg.warning(
            "L1 payload scope drift: top-level keys outside decision ∪ known non-material: %s",
            drift,
        )
    return drift
