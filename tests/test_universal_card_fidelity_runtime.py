"""Mechanical contract locks for the card consumer contract registry (CARD_CONSUMER_CONTRACT_V1)."""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CARD_CONSUMER_CONTRACT = ROOT / "reports" / "artifacts" / "CARD_CONSUMER_CONTRACT_V1.json"

_REQUIRED_FIELD_KEYS = frozenset(
    {
        "field_name",
        "category",
        "backend_source",
        "api_key",
        "consumer_surface",
        "operator_relevance",
        "allowed_type",
        "allowed_values",
        "nullable",
        "fallback_behavior",
        "stale_behavior",
        "pending_behavior",
        "ticker_agnostic_rule",
        "test_required",
        "decision_status",
    }
)

_VALID_DECISION_STATUSES = frozenset(
    {
        "PROVEN",
        "NOT_PROVEN",
        "OPERATOR_DECISION_REQUIRED",
        "BACKEND_ONLY",
        "DESIGN_APPROVED_PENDING_UI",
    }
)

_VALID_OPERATOR_SURFACES = frozenset(
    {
        "horizon_pill",
        "all_card",
        "plan_card",
        "execution_chip",
        "decision_rail_chip",
        "explanation_rail",
        "risk_rail",
        "risk_rail_paired",
        "probability_rail",
        "em_band",
        "freshness_banner",
        "backend_only",
        "removed",
        "operator_decision_required",
    }
)


def _load_card_consumer_contract() -> dict:
    return json.loads(CARD_CONSUMER_CONTRACT.read_text(encoding="utf-8"))


def test_card_consumer_contract_v1_registry_exists_and_schema():
    assert CARD_CONSUMER_CONTRACT.is_file()
    reg = _load_card_consumer_contract()
    assert reg["schema_version"] == 1
    assert reg["artifact"] == "reports/artifacts/CARD_CONSUMER_CONTRACT_V1.json"
    assert len(reg.get("contract_rules") or []) >= 10
    assert "card_freshness_v1" in reg
    fields = reg.get("fields") or []
    assert len(fields) >= 20
    for row in fields:
        missing = _REQUIRED_FIELD_KEYS - set(row)
        assert not missing, f"{row.get('field_name')}: missing {missing}"


_CARD_FRESHNESS_V1_REQUIRED_BACKEND_FIELDS = frozenset(
    {
        "card_trust_state",
        "card_actionable",
        "analytics_age_sec",
        "quote_age_sec",
        "bundle_age_sec",
        "analytics_ttl_sec",
        "quote_stale_sec",
        "bundle_trust_sec",
        "fallback_status",
        "carry_forward_status",
        "source_freshness",
        "stale_reason_codes",
        "quote_ts",
        "bundle_ts",
        "mhap_bundle_ts",
        "tier_c_cache_revalidated",
        "tier_c_cache_gate_ok",
        "analytics_stale",
        "analytics_generated_at",
        "analytics_refresh_in_progress",
        "quote_source_detail.carried_forward",
        "quote_source_detail.schwab_auth_degraded",
    }
)

_CARD_FRESHNESS_V1_REQUIRED_UI_LABELS = frozenset(
    {
        "LIVE",
        "SYNCED",
        "REFRESHING",
        "STALE",
        "LANE STALE",
        "FEED STALE",
        "CARRIED FORWARD",
        "AUTH FALLBACK",
        "ANALYTICS OLD",
        "QUOTE NEWER THAN SIGNAL",
        "NOT ACTIONABLE",
        "WITHHELD",
        "PENDING",
        "DEGRADED",
        "UNAVAILABLE",
    }
)

_CARD_FRESHNESS_V1_REQUIRED_STALE_REASON_CODES = frozenset(
    {
        "analytics_stale",
        "analytics_age_exceeded",
        "quote_age_exceeded",
        "bundle_age_exceeded",
        "quote_newer_than_signal",
        "mhap_older_than_quote",
        "quote_carried_forward",
        "auth_fallback",
        "auth_degraded",
        "tier_c_cache_stale_serve",
        "cache_refresh_in_progress",
        "revalidate_quarantine",
        "lane_stale",
        "feed_stale",
        "quote_ahead",
        "gen_stale",
        "pending_shell",
        "partial_tier_c",
        "pending_full_analytics",
        "slow_stale_vs_fast",
        "transport_down",
        "transport_delay",
        "missing_quote_ts",
        "missing_bundle_ts",
        "ticker_mismatch",
        "token_invalid",
        "fusion_unavailable",
        "stack_integrity_degraded",
        "signals_engine_failed",
        "stack_invalid",
        "state_error",
        "cached_spread_fallback",
    }
)

_CARD_FRESHNESS_V1_REQUIRED_FAIL_CLOSED_FIELDS = frozenset(
    {
        "call_state ACTIVE paint",
        "final_tradeable authoritative display",
        "entry_state armed/confirmed on PLAN",
        "tf-signal-card--trade-active class",
        "horizon confidence pct as authoritative",
        "ALL consolidated trade-active glow",
        "engineTradeableSetup true path",
        "call_signal long/short on actionable surfaces",
        "plan entry/stop/targets/size when untrusted",
    }
)


def _load_card_freshness_v1() -> dict:
    return _load_card_consumer_contract()["card_freshness_v1"]


def test_card_freshness_v1_design_block_present():
    cf = _load_card_freshness_v1()
    assert cf["lane_id"] == "STALE_CARD_REMEDIATION_S1"
    assert cf["status"] == "DESIGN_ONLY_NOT_WIRED"
    assert cf["binding_on_production"] is False
    assert cf["design_recommendation"] == "HYBRID"
    layers = cf.get("canonical_freshness_layers") or []
    assert len(layers) == 7
    layer_ids = {row["layer"] for row in layers}
    assert "quote_freshness" in layer_ids
    assert "ui_render_freshness" in layer_ids


def test_card_freshness_v1_stale_reason_codes_complete():
    cf = _load_card_freshness_v1()
    codes = set(cf.get("stale_reason_codes") or [])
    assert _CARD_FRESHNESS_V1_REQUIRED_STALE_REASON_CODES <= codes


def test_card_freshness_v1_ui_labels_complete():
    cf = _load_card_freshness_v1()
    labels = set(cf.get("ui_labels") or [])
    assert _CARD_FRESHNESS_V1_REQUIRED_UI_LABELS <= labels


def test_card_freshness_v1_fail_closed_fields_documented():
    cf = _load_card_freshness_v1()
    documented = set(cf.get("fail_closed_fields") or [])
    assert _CARD_FRESHNESS_V1_REQUIRED_FAIL_CLOSED_FIELDS <= documented


def test_card_freshness_v1_hybrid_policy_documented():
    cf = _load_card_freshness_v1()
    policy = cf.get("hybrid_render_policy") or {}
    assert policy.get("preserve_read_only_when_stale") is True
    assert policy.get("fail_closed_actionability_when_stale") is True
    assert policy.get("require_explicit_stale_labels") is True
    assert policy.get("restore_active_paint_requires_all_gates") is True
    fail_closed = set(policy.get("fail_closed_surfaces") or [])
    assert _CARD_FRESHNESS_V1_REQUIRED_FAIL_CLOSED_FIELDS <= fail_closed
    backend = set(cf.get("backend_contract_fields") or [])
    assert _CARD_FRESHNESS_V1_REQUIRED_BACKEND_FIELDS <= backend


def test_card_freshness_v1_fidelity_still_not_proven():
    cf = _load_card_freshness_v1()
    reg = _load_card_consumer_contract()
    fc = reg.get("fidelity_classification_v1") or {}
    assert cf["card_fidelity_overall"] == "NOT_PROVEN"
    assert cf["universal_runtime_live_proof"] == "NOT_PROVEN"
    assert cf["real_money_readiness"] == "NOT_PROVEN"
    assert fc["card_fidelity_overall"] == "NOT_PROVEN"
    assert fc["universal_runtime_live_proof"] == "NOT_PROVEN"
    assert fc["real_money_readiness"] == "NOT_PROVEN"


def test_card_freshness_v1_stale_withheld_rth_still_fail():
    cf = _load_card_freshness_v1()
    reg = _load_card_consumer_contract()
    fc = reg.get("fidelity_classification_v1") or {}
    assert cf["stale_withheld_rth_freshness"] == "FAIL"
    assert fc.get("acceptance_semantics", {}).get("stale_withheld_rth_freshness") == "FAIL"


def test_card_consumer_contract_no_speculative_meta_label_fields():
    reg = _load_card_consumer_contract()
    forbidden = set(reg["execution_channel"]["forbidden_speculative_contract_fields"])
    assert forbidden == {
        "meta_label_size",
        "triple_barrier_label",
        "meta_label_probability",
        "foundation_model_signal",
    }
    field_names = {row["field_name"] for row in reg["fields"]}
    assert field_names.isdisjoint(forbidden)
    for row in reg["fields"]:
        assert row["decision_status"] in _VALID_DECISION_STATUSES


def test_card_consumer_contract_execution_channel_meta_label_ready():
    reg = _load_card_consumer_contract()
    ch = reg["execution_channel"]
    assert ch["meta_label_ready"] is True
    assert ch["primary_field_today"] == "call_state"
    assert set(ch["vocabulary"]) == {"WAIT", "WATCH", "ACTIVE"}
    supporting = set(ch["supporting_fields_today"])
    assert {"call_signal", "final_tradeable", "entry_state", "wait_reason"} <= supporting
    assert "call_forecast_state" in ch["backend_only_fields_today"]
    forecast = next(r for r in reg["fields"] if r["field_name"] == "call_forecast_state")
    assert forecast["consumer_surface"] == "backend_only"


def test_card_consumer_contract_operator_relevant_fields_have_disposition():
    reg = _load_card_consumer_contract()
    for row in reg["fields"]:
        if row["operator_relevance"] in ("high", "medium"):
            assert row["consumer_surface"] in _VALID_OPERATOR_SURFACES
            assert row["decision_status"] in _VALID_DECISION_STATUSES
            assert row["decision_status"] != "BACKEND_ONLY" or row["operator_relevance"] == "backend_only"


def test_card_consumer_contract_orphan_fields_tracked_in_registry():
    reg = _load_card_consumer_contract()
    by_name = {row["field_name"]: row for row in reg["fields"]}
    for orphan in ("pred_headline", "reversal_risk", "reversal_label"):
        assert orphan in by_name
        assert by_name[orphan]["decision_status"] == "DESIGN_APPROVED_PENDING_UI"
    assert by_name["call_signal"]["decision_status"] == "OPERATOR_DECISION_REQUIRED"
    assert by_name["call_headline"]["decision_status"] == "PROVEN"
    assert by_name["call_headline"]["consumer_surface"] == "backend_only"
    assert by_name["call_state"]["decision_status"] == "PROVEN"


def test_card_consumer_contract_future_lane_recorded():
    reg = _load_card_consumer_contract()
    lanes = reg.get("future_lanes") or []
    assert any(l.get("lane_id") == "future_execution_state_sophistication" for l in lanes)
    lane = next(l for l in lanes if l["lane_id"] == "future_execution_state_sophistication")
    assert lane["status"] == "FUTURE_LANE_WITH_REASON"
    assert "triple-barrier" in lane["description"].lower()
    assert "meta-label" in lane["description"].lower()


def test_card_consumer_contract_horizon_vs_execution_separation():
    reg = _load_card_consumer_contract()
    by_name = {row["field_name"]: row for row in reg["fields"]}
    assert by_name["mhap_rows[].call"]["consumer_surface"] == "horizon_pill"
    assert by_name["call_state"]["consumer_surface"] == "execution_chip"
    assert by_name["call_state"]["category"] == "execution_state"
    assert by_name["call_state"]["decision_status"] == "PROVEN"
    assert by_name["final_tradeable"]["consumer_surface"] == "execution_chip"


def test_call_signal_decision_rail_not_primary_execution_chip():
    reg = _load_card_consumer_contract()
    by_name = {row["field_name"]: row for row in reg["fields"]}
    call_signal = by_name["call_signal"]
    call_state = by_name["call_state"]
    ch = reg["execution_channel"]
    assert ch["primary_field_today"] == "call_state"
    assert call_signal["consumer_surface"] == "decision_rail_chip"
    assert call_signal["consumer_surface"] != "execution_chip"
    assert call_state["consumer_surface"] == "execution_chip"
    assert call_state["decision_status"] == "PROVEN"
    assert "call_signal" in ch["supporting_fields_today"]
    assert call_signal["category"] == "direction_support"


def test_call_state_remains_primary_execution_chip_field():
    reg = _load_card_consumer_contract()
    ch = reg["execution_channel"]
    by_name = {row["field_name"]: row for row in reg["fields"]}
    assert ch["primary_field_today"] == "call_state"
    assert by_name["call_state"]["consumer_surface"] == "execution_chip"
    assert by_name["call_state"]["decision_status"] == "PROVEN"
    assert by_name["call_signal"]["consumer_surface"] != "execution_chip"


def test_call_signal_reclassification_remains_closed():
    reg = _load_card_consumer_contract()
    by_name = {row["field_name"]: row for row in reg["fields"]}
    assert by_name["call_signal"]["consumer_surface"] == "decision_rail_chip"
    assert by_name["call_signal"]["decision_status"] == "OPERATOR_DECISION_REQUIRED"
    assert by_name["call_state"]["consumer_surface"] == "execution_chip"
    assert reg["execution_channel"]["primary_field_today"] == "call_state"


def test_explainability_authority_hierarchy_recorded():
    reg = _load_card_consumer_contract()
    exp = reg["explainability_surface_v1"]
    assert exp["display_trust_gate"] == "analyticsCardTrustGate"
    assert exp["execution_authority_field"] == "call_state"
    assert exp["wait_explanation_authority_field"] == "wait_reason"
    assert exp["orphan_payload_handling_overall"] == "NOT_PROVEN"
    assert exp["ui_implementation_approved"] is False
    assert exp["reversal_pair_veto_authority"] is False
    assert exp["reversal_pair_must_stay_together"] is True
    assert "pred_headline" in exp["supplemental_explanation_fields"]
    assert set(exp["supplemental_risk_fields"]) == {"reversal_risk", "reversal_label"}
    assert "call_state" in exp["pred_headline_cannot_override"]


def test_pred_headline_cannot_override_execution_or_wait_authority():
    reg = _load_card_consumer_contract()
    exp = reg["explainability_surface_v1"]
    pred = next(r for r in reg["fields"] if r["field_name"] == "pred_headline")
    blocked = set(exp["pred_headline_cannot_override"])
    assert {"call_state", "wait_reason", "validation_summary", "mhap_rows"} <= blocked
    assert pred["design_record"]["authority"] == "supplemental_non_authoritative"


def test_reversal_pair_no_veto_and_cannot_downgrade_active():
    reg = _load_card_consumer_contract()
    exp = reg["explainability_surface_v1"]
    assert exp["reversal_pair_veto_authority"] is False
    assert exp["reversal_pair_cannot_downgrade_active"] is True
    risk = next(r for r in reg["fields"] if r["field_name"] == "reversal_risk")
    assert risk["design_record"]["veto_authority"] is False
    assert risk["design_record"]["cannot_downgrade_active"] is True
