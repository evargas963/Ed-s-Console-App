"""A2 lifecycle advisory sidecar v0.

This sidecar intentionally emits structure only. At entry time there is no
active position to manage, so v0 does not project stop/target behavior or claim
any dynamic lifecycle decision authority.
"""

from __future__ import annotations

from typing import Any

from lifecycle_rule_core import LIFECYCLE_RULE_CORE_VERSION


LIFECYCLE_GAP_NAMES = (
    "a2_lifecycle_policy_pending",
    "a2_lifecycle_static_rule_core_pending",
    "a2_lifecycle_legacy_exit_logic_divergence_audit_pending",
    "a2_lifecycle_eod_force_exit_logic_not_implemented",
    "a2_lifecycle_time_stop_force_exit_clock_threshold_policy_object_pending",
    "a2_lifecycle_eod_window_threshold_minutes_policy_object_pending",
    "a2_lifecycle_iv_crush_handler_not_implemented",
    "a2_lifecycle_pin_risk_handler_not_implemented",
    "a2_lifecycle_gamma_spike_handler_not_implemented",
    "a2_lifecycle_assignment_risk_handler_not_implemented",
    "a2_lifecycle_spread_widening_exit_not_implemented",
    "a2_lifecycle_partial_fill_handler_not_implemented",
    "a2_lifecycle_dynamic_policy_not_implemented",
    "a2_lifecycle_promotion_to_runtime_authority_not_authorized",
)

THRESHOLD_POLICY_OBJECTS = (
    "a2_lifecycle_time_stop_force_exit_clock_threshold_policy_object_pending",
    "a2_lifecycle_eod_window_threshold_minutes_policy_object_pending",
)

PROMOTION_CRITERIA = (
    (
        "replay_live_parity_passing",
        "Replay/live parity exists for the static rule core, but lifecycle sidecar behavior is not validated as a promoted runtime authority.",
    ),
    (
        "bound_threshold_policies",
        "Lifecycle threshold policy objects remain unbound.",
    ),
    (
        "empirical_improvement_over_static_baseline",
        "No dynamic lifecycle candidate has demonstrated improvement over the static baseline.",
    ),
    (
        "uncertainty_disclosure",
        "No conformal or uncertainty disclosure exists for lifecycle decisions.",
    ),
    (
        "a2_replay_label_validation",
        "A2 replay labels exist as a scaffold but are not validated as a lifecycle label source.",
    ),
    (
        "post_trade_attribution_coherence",
        "Lifecycle sidecar outcomes are not reconciled to realized PnL through post-trade attribution.",
    ),
    (
        "operator_decision_register_approval",
        "No operator decision register entry promotes lifecycle behavior to runtime authority.",
    ),
)


def build_a2_lifecycle_sidecar(ms_dict: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the minimal advisory lifecycle sidecar for A2.

    ``ms_dict`` is accepted for future input expansion but v0 deliberately does
    not consume market fields or projected geometry.
    """
    _ = ms_dict
    return {
        "schema_version": "v2.0",
        "module_id": "A",
        "expression_profile_id": "A2",
        "authority": {
            "mode": "advisory_non_authoritative",
            "tier": "C_analytics_only",
            "changes_trade_behavior": False,
        },
        "static_rule_core_version": LIFECYCLE_RULE_CORE_VERSION,
        "lifecycle_action": "no_active_position",
        "lifecycle_conflict_state": "lifecycle_warning_only",
        "event_sources": [],
        "threshold_policy_objects": [
            {"id": policy_id, "source": "policy_object_pending"}
            for policy_id in THRESHOLD_POLICY_OBJECTS
        ],
        "named_gaps": list(LIFECYCLE_GAP_NAMES),
        "source_classification": {
            "inputs": "schwab_native_normalized",
            "decision": "derived_because_schwab_does_not_provide",
            "thresholds": "policy_object_pending",
        },
        "promotion_state": {
            criterion: {"satisfied": False, "reason": reason}
            for criterion, reason in PROMOTION_CRITERIA
        },
    }
