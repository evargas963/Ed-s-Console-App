from __future__ import annotations

from datetime import datetime

from lifecycle_rule_core import LIFECYCLE_RULE_CORE_VERSION
from v2_decision.a2_lifecycle_sidecar import LIFECYCLE_GAP_NAMES, PREVIEW_BLOCKING_GAPS
from v2_decision.module_a_adapter import build_module_a_a1_decision


from time_et import ET
def _epoch_ms_et(year: int, month: int, day: int, hour: int, minute: int) -> int:
    return int(datetime(year, month, day, hour, minute, tzinfo=ET).timestamp() * 1000)


def _winner() -> dict:
    # institutional-synthetic-ok: v2 lifecycle-sidecar test needs a controlled winner row.
    return {
        "expression": "500 CALL",
        "strike": 500.0,
        "side": "CALL",
        "composite_score": 8.25,
        "chain_row": {
            "symbol": "SPY260505C00500000",
            "putCall": "CALL",
            "strikePrice": 500.0,
            "bid": 1.2,
            "ask": 1.3,
            "delta": 0.52,
            "gamma": 0.08,
            "theta": -0.18,
            "vega": 0.02,
            "volatility": 0.22,
            "totalVolume": 1200,
            "openInterest": 4300,
            "expirationDate": "2026-05-05",
            "quoteTimeInLong": 1778018399000,
            "tradeTimeInLong": 1778018398500,
        },
    }


def _ms(**overrides) -> dict:
    base = {
        "ticker": "SPY",
        "selected_exp": "2026-05-05",
        "call_option_expiry": "2026-05-05",
        "dte_warn": "0DTE",
        "call_signal": "long",
        "fusion_available": True,
        "fusion_dominant_direction": "up",
        "fusion_dominant_prob": 0.64,
        "fusion_confidence": "high",
        "is_no_trade": False,
        "execution_mode": "STANDARD",
        "rec_strike": 500.0,
        "rec_side": "CALL",
        "call_option_right": "CALL",
        "liq_ok": True,
        "spread": 0.1,
        "ratio": 6.5,
        "vol_oi": 0.279,
        "spot": 499.5,
        "entry": 500.0,
        "et_hour": 10,
        "et_minute": 30,
        "vix_level": 21.0,
        "vol_regime_risk_mult": 1.0,
        "avg_5c_pts": 4.0,
        "avg_15c_pts": 6.0,
        "avg_60c_pts": 8.0,
        "vwap": 503.5,
        "call_gamma_wall": 505.0,
        "call_oi_wall": 506.0,
        "mins_to_close": 120.0,
        "decision_time_ms": _epoch_ms_et(2026, 5, 5, 10, 30),
        "entry_state": "armed",
        "option_chain_selection_proof": {
            "status": "ok",
            "winner": _winner(),
            "liquidity_summary": {"any_candidate_passed_liq_gate": True},
        },
        "contract_context": "SPY 2026-05-05 500C - 0DTE - mid~1.25",
        "stop": 498.5,
        "target": 503.0,
        "target2": 505.0,
    }
    base.update(overrides)
    return base


def _a2(ms: dict | None = None) -> dict:
    decision = build_module_a_a1_decision(ms or _ms())
    return decision["expression_profiles"]["A2"]


def test_a2_lifecycle_sidecar_is_nested_under_lifecycle():
    """Contract: PILOT_1B_A2_LIFECYCLE_CONTRACT.md section 148 - sidecar output exists."""
    a2 = _a2()

    assert "sidecar" in a2["lifecycle"]


def test_a2_lifecycle_sidecar_projected_preview_exists():
    """Contract: PILOT_1B_A2_LIFECYCLE_CONTRACT.md section 193 - projected_preview exists."""
    sidecar = _a2()["lifecycle"]["sidecar"]

    assert sidecar["projected_preview"]


def test_a2_lifecycle_sidecar_emits_all_contract_fields():
    """Contract: PILOT_1B_A2_LIFECYCLE_CONTRACT.md sections 148-163 - sidecar shape."""
    sidecar = _a2()["lifecycle"]["sidecar"]

    assert set(sidecar) == {
        "schema_version",
        "module_id",
        "expression_profile_id",
        "authority",
        "static_rule_core_version",
        "lifecycle_action",
        "cadence_observation_mode",
        "lifecycle_conflict_state",
        "event_sources",
        "threshold_policy_objects",
        "named_gaps",
        "source_classification",
        "promotion_state",
        "projected_preview",
    }
    assert sidecar["schema_version"] == "v2.0"
    assert sidecar["module_id"] == "A"
    assert sidecar["expression_profile_id"] == "A2"


def test_projected_preview_status_policy_pending_when_entry_candidate_derivable():
    """Contract: lifecycle contract L215-220 - policy_pending field-fill mapping."""
    preview = _a2()["lifecycle"]["sidecar"]["projected_preview"]

    assert preview["preview_status"] == "policy_pending"
    assert preview["projected_stop"]["value"] == 498.98
    assert preview["projected_target"]["value"] == 503.5
    assert preview["projected_target2"]["value"] == 506.0


def test_projected_preview_status_no_entry_candidate_when_a2_has_no_trade_candidate():
    """Contract: lifecycle contract L218 - no candidate means projected fields are None."""
    ms = _ms(is_no_trade=True)
    preview = _a2(ms)["lifecycle"]["sidecar"]["projected_preview"]

    assert preview["preview_status"] == "not_available_no_entry_candidate"
    assert _projected_values(preview) == {
        "projected_stop": None,
        "projected_target": None,
        "projected_target2": None,
        "projected_max_hold_bars": None,
        "projected_eod_force_exit_time": None,
    }


def test_projected_preview_status_missing_inputs_when_required_inputs_absent():
    """Contract: lifecycle contract L219 - missing required inputs are enumerated."""
    ms = _ms(entry=None)
    ms.pop("entry", None)
    preview = _a2(ms)["lifecycle"]["sidecar"]["projected_preview"]

    assert preview["preview_status"] == "not_available_missing_inputs"
    assert preview["derivation_inputs"]["entry"]["value"] is None
    assert preview["derivation_inputs"]["entry"]["source"] == "not_implemented"
    assert preview["derivation_inputs"]["entry"]["source_classification"] == "missing_from_ms_dict"
    assert preview["derivation_inputs"]["entry"]["detail"] == "missing_required_preview_input"
    assert _projected_values(preview)["projected_stop"] is None


def test_projected_preview_available_is_currently_unreachable_until_eod_gap_closes():
    """Contract: lifecycle contract L244 - preview remains policy pending until later phases."""
    preview = _a2()["lifecycle"]["sidecar"]["projected_preview"]

    assert preview["preview_named_gaps"] == []
    assert preview["projected_eod_force_exit_time"]["source"] == "policy_object_pending"
    assert preview["preview_status"] != "available"
    assert PREVIEW_BLOCKING_GAPS == ()


def test_projected_preview_policy_fields_remain_policy_object_pending():
    """Contract: lifecycle contract L243-244 - max-hold and EOD fields remain policy pending."""
    preview = _a2()["lifecycle"]["sidecar"]["projected_preview"]

    assert preview["projected_max_hold_bars"] == {
        "value": None,
        "source": "policy_object_pending",
        "source_classification": "policy_object_pending",
    }
    assert preview["projected_eod_force_exit_time"] == {
        "value": None,
        "source": "policy_object_pending",
        "source_classification": "policy_object_pending",
    }


def test_projected_preview_derivation_inputs_enumerate_all_contract_keys():
    """Contract: lifecycle contract L245 - derivation_inputs enumerates attempted inputs."""
    inputs = _a2()["lifecycle"]["sidecar"]["projected_preview"]["derivation_inputs"]

    assert set(inputs) == {
        "spot",
        "vix_level",
        "mins_elapsed_since_open",
        "risk_multiplier",
        "entry",
        "direction",
        "risk",
        "avg5",
        "avg15",
        "avg60",
        "structural_levels",
    }
    for payload in inputs.values():
        assert {"value", "source", "source_classification"}.issubset(payload)
    assert inputs["spot"]["value"] == 499.5
    # Schwab-direct equity quote ladder; see PILOT_1B_A2_0DTE_CONTRACT.md and
    # server.py::_extract_quote / market_context.py::_extract_quote.
    assert inputs["spot"]["source"] == "v2_compliant"
    assert inputs["spot"]["source_classification"] == "schwab_native_normalized"
    assert inputs["spot"]["detail"] == "quotes.quote.lastPrice"
    # Schwab-direct $VIX quote payload (same equity-quote ladder).
    assert inputs["vix_level"]["value"] == 21.0
    assert inputs["vix_level"]["source"] == "v2_compliant"
    assert inputs["vix_level"]["source_classification"] == "schwab_native_normalized"
    assert inputs["vix_level"]["detail"] == "quotes.$VIX.quote.lastPrice"
    assert inputs["mins_elapsed_since_open"]["value"] == 60.0
    # MarketState producer key is `vol_regime_risk_mult` (see market_state.py
    # ms.vol_regime_risk_mult). The consumer reads the real value, not None.
    assert inputs["risk_multiplier"]["value"] == 1.0
    assert inputs["risk_multiplier"]["source_classification"] == "schwab_native_normalized"


def test_projected_preview_metadata_source_module_and_timestamp():
    """Contract: lifecycle contract L246-247 - source module and timestamp are explicit."""
    preview = _a2()["lifecycle"]["sidecar"]["projected_preview"]

    assert preview["derivation_source_module"] == "lifecycle_rule_core"
    assert preview["would_apply_if_entered_at_time"] == _epoch_ms_et(2026, 5, 5, 10, 30)


def test_projected_preview_authority_blocks_runtime_interpretation():
    """Contract: lifecycle contract L250-258 - preview_authority is projection-not-decision."""
    preview = _a2()["lifecycle"]["sidecar"]["projected_preview"]

    assert preview["preview_authority"] == {
        "mode": "advisory_non_authoritative",
        "tier": "C_analytics_only",
        "changes_trade_behavior": False,
        "projection_not_decision": True,
        "text": "Projected lifecycle preview only; not an active lifecycle decision. Future lifecycle action may differ.",
    }


def test_projected_preview_named_gaps_are_preview_blocking_subset_only():
    """Contract: lifecycle contract L226-234 - preview_named_gaps are preview-blocking only."""
    preview = _a2()["lifecycle"]["sidecar"]["projected_preview"]

    assert preview["preview_named_gaps"] == list(PREVIEW_BLOCKING_GAPS)
    assert preview["preview_named_gaps"] == []


def test_projected_preview_no_silent_partial_fills_when_unavailable():
    """Contract: lifecycle contract L272-274 - unavailable preview fields disclose absence."""
    preview = _a2(_ms(entry=None))["lifecycle"]["sidecar"]["projected_preview"]

    assert preview["preview_status"] != "available"
    for key, value in _projected_values(preview).items():
        assert value is None, f"{key} must not contain a stale/default value"


def test_projected_preview_does_not_mutate_ms_dict_or_manage_active_position_data():
    """Implementation rule: preview remains pre-entry projection and does not mutate ms_dict."""
    ms = _ms(active_position={"entry": 1.0, "stop": 0.5}, position_state="open")
    before = dict(ms)

    preview = _a2(ms)["lifecycle"]["sidecar"]["projected_preview"]

    assert ms == before
    assert preview["preview_status"] == "policy_pending"
    assert preview["preview_authority"]["projection_not_decision"] is True


def test_a2_lifecycle_sidecar_uses_honest_entry_time_posture_alpha():
    """Operator posture alpha: no projected lifecycle action before an active position exists."""
    sidecar = _a2(_ms(entry_state="armed", decision_time_ms=_epoch_ms_et(2026, 5, 5, 15, 50)))["lifecycle"]["sidecar"]

    assert sidecar["lifecycle_action"] == "no_active_position"
    assert sidecar["event_sources"] == []


def test_a2_lifecycle_sidecar_conflict_defaults_to_warning_only():
    """Contract: PILOT_1B_A2_LIFECYCLE_CONTRACT.md sections 97-100 - advisory default."""
    sidecar = _a2()["lifecycle"]["sidecar"]

    assert sidecar["lifecycle_conflict_state"] == "lifecycle_warning_only"


def test_a2_lifecycle_sidecar_static_rule_core_version_matches_constant():
    """Contract: PILOT_1B_A2_LIFECYCLE_CONTRACT.md section 155 - static rule version."""
    sidecar = _a2()["lifecycle"]["sidecar"]

    assert sidecar["static_rule_core_version"] == LIFECYCLE_RULE_CORE_VERSION


def test_a2_lifecycle_sidecar_named_gaps_match_contract_verbatim():
    """Contract: PILOT_1B_A2_LIFECYCLE_CONTRACT.md sections 117-136 - named gaps."""
    sidecar = _a2()["lifecycle"]["sidecar"]

    assert sidecar["named_gaps"] == list(LIFECYCLE_GAP_NAMES)
    # Static rule core, B2-bound timing policy gaps, EOD force-exit logic, and pin-risk handler are retired.
    assert "a2_lifecycle_pin_risk_handler_not_implemented" not in sidecar["named_gaps"]
    assert len(sidecar["named_gaps"]) == 9
    assert sidecar["named_gaps"] == [
        "a2_lifecycle_policy_pending",
        "a2_lifecycle_legacy_exit_logic_divergence_audit_pending",
        "a2_lifecycle_iv_crush_handler_not_implemented",
        "a2_lifecycle_gamma_spike_handler_not_implemented",
        "a2_lifecycle_assignment_risk_handler_not_implemented",
        "a2_lifecycle_spread_widening_exit_not_implemented",
        "a2_lifecycle_partial_fill_handler_not_implemented",
        "a2_lifecycle_dynamic_policy_not_implemented",
        "a2_lifecycle_promotion_to_runtime_authority_not_authorized",
    ]


def test_a2_lifecycle_sidecar_authority_matches_contract_block():
    """Contract: PILOT_1B_A2_LIFECYCLE_CONTRACT.md sections 14-22 - authority block."""
    sidecar = _a2()["lifecycle"]["sidecar"]

    assert sidecar["authority"] == {
        "mode": "advisory_non_authoritative",
        "tier": "C_analytics_only",
        "changes_trade_behavior": False,
    }


def test_a2_lifecycle_sidecar_policy_objects_and_source_classification_are_explicit():
    """Contract: PILOT_1B_A2_LIFECYCLE_CONTRACT.md sections 26-34 and 148-163."""
    sidecar = _a2()["lifecycle"]["sidecar"]

    assert sidecar["threshold_policy_objects"] == []
    assert sidecar["source_classification"] == {
        "inputs": "schwab_native_normalized",
        "decision": "derived_because_schwab_does_not_provide",
        "thresholds": "policy_object_pending",
    }


def test_a2_lifecycle_sidecar_promotion_state_marks_all_criteria_unsatisfied():
    """Contract: PILOT_1B_A2_LIFECYCLE_CONTRACT.md sections 176-188 - promotion criteria."""
    sidecar = _a2()["lifecycle"]["sidecar"]

    assert set(sidecar["promotion_state"]) == {
        "replay_live_parity_passing",
        "bound_threshold_policies",
        "empirical_improvement_over_static_baseline",
        "uncertainty_disclosure",
        "a2_replay_label_validation",
        "post_trade_attribution_coherence",
        "operator_decision_register_approval",
    }
    for state in sidecar["promotion_state"].values():
        assert state["satisfied"] is False
        assert isinstance(state["reason"], str)
        assert state["reason"]


def test_existing_lifecycle_leaves_remain_unchanged_when_sidecar_is_added():
    """Regression: existing A2 lifecycle leaves remain byte-identical except the new sidecar key."""
    lifecycle = _a2()["lifecycle"]

    existing = {key: value for key, value in lifecycle.items() if key != "sidecar"}
    assert existing == {
        "entry_policy": {"value": "SPY 2026-05-05 500C - 0DTE - mid~1.25", "source": "v1_approximation"},
        "stop_policy": {"value": 498.5, "source": "v1_approximation"},
        "target_policy": {"value": 503.0, "source": "v1_approximation"},
        "timeout_policy": {"value": None, "source": "policy_object_pending"},
        "forced_exit_time": {"value": None, "source": "policy_object_pending"},
        "allowed_actions": {
            "value": ["hold", "exit", "tighten", "scale_out", "convert", "force_exit"],
            "source": "policy_object_pending",
        },
        "lifecycle_policy_id": {"value": None, "source": "policy_object_pending"},
    }


def test_a2_lifecycle_crosswalk_source_indicators_remain_unchanged():
    """Contract: PILOT_1B_A2_LIFECYCLE_CONTRACT.md section 172 - crosswalk leaves unchanged."""
    a2 = _a2()

    assert a2["probability_and_ev"]["P_lifecycle_adjusted_profit"]["source"] == "not_implemented"
    assert a2["lifecycle"]["timeout_policy"]["source"] == "policy_object_pending"
    assert a2["lifecycle"]["lifecycle_policy_id"]["source"] == "policy_object_pending"


def test_v0_sidecar_fields_remain_backward_compatible_with_v1_preview():
    """Contract: lifecycle contract L278-280 - v0 fields remain unchanged when preview is added."""
    sidecar = _a2()["lifecycle"]["sidecar"]

    current = {key: value for key, value in sidecar.items() if key != "projected_preview"}
    assert current == {
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
        "cadence_observation_mode": "event_triggered",
        "lifecycle_conflict_state": "lifecycle_warning_only",
        "event_sources": [],
        "threshold_policy_objects": [],
        "named_gaps": list(LIFECYCLE_GAP_NAMES),
        "source_classification": {
            "inputs": "schwab_native_normalized",
            "decision": "derived_because_schwab_does_not_provide",
            "thresholds": "policy_object_pending",
        },
        "promotion_state": sidecar["promotion_state"],
    }


def test_sidecar_emits_force_exit_recommended_when_predicates_hold():
    sidecar = _a2(
        _ms(
            entry_state="filled",
            decision_time_ms=_epoch_ms_et(2026, 5, 5, 15, 50),
            selected_exp="2026-05-05",
        )
    )["lifecycle"]["sidecar"]

    assert sidecar["lifecycle_action"] == "force_exit_recommended"


def test_sidecar_emits_no_active_position_when_predicates_fail():
    sidecar = _a2(
        _ms(
            entry_state="armed",
            decision_time_ms=_epoch_ms_et(2026, 5, 5, 15, 50),
            selected_exp="2026-05-05",
        )
    )["lifecycle"]["sidecar"]

    assert sidecar["lifecycle_action"] == "no_active_position"


def test_sidecar_emits_cadence_observation_mode_field():
    assert _a2(_ms(decision_time_ms=_epoch_ms_et(2026, 5, 5, 15, 29)))["lifecycle"]["sidecar"][
        "cadence_observation_mode"
    ] == "event_triggered"
    assert _a2(_ms(decision_time_ms=_epoch_ms_et(2026, 5, 5, 15, 30)))["lifecycle"]["sidecar"][
        "cadence_observation_mode"
    ] == "every_tier_c_cycle"


def test_sidecar_lifecycle_gap_names_drops_eod_force_exit_logic():
    sidecar = _a2()["lifecycle"]["sidecar"]

    assert "a2_lifecycle_eod_force_exit_logic_not_implemented" not in sidecar["named_gaps"]
    assert len(sidecar["named_gaps"]) == 9


def test_sidecar_preview_blocking_gaps_is_empty():
    assert PREVIEW_BLOCKING_GAPS == ()
    assert _a2()["lifecycle"]["sidecar"]["projected_preview"]["preview_named_gaps"] == []


def _projected_values(preview: dict) -> dict:
    return {
        key: preview[key]["value"]
        for key in (
            "projected_stop",
            "projected_target",
            "projected_target2",
            "projected_max_hold_bars",
            "projected_eod_force_exit_time",
        )
    }


# ── RC-337: decision-timestamp unit contract (retained enforcement) ──────────────────────
#
# `would_apply_if_entered_at_time` (a2_lifecycle_sidecar.py:251) is a pass-through of
# `_decision_timestamp(ms)`, which selects among FOUR sources with PROVEN units:
#   decision_time_ms        epoch-ms  (server.py:7763  int(_refresh_ts_utc * 1000))
#   decision_timestamp_utc  epoch-s   (live_decision_bundle.py:122  float(time.time()))
#   _server_build_ts        epoch-s   (server.py:7764 / :9480  time.time())
#   refresh_ts_utc          epoch-s   (server.py:7627  _utc_ts_refresh())
# The pre-fix resolver returned the first non-falsy source IN THAT SOURCE'S UNIT, so the
# same field was epoch-ms on one route and epoch-SECONDS on another (measured live:
# 1786383424954 vs 1786383424.2295866). Canonical unit is epoch-ms; fractional policy is
# TRUNCATE (`int(s * 1000)`), the repo convention at 12 sites incl. `_epoch_ms_et` above.
# These tests are the recurrence lock: they exercise the REAL resolver and each changed
# seconds-fallback branch, and they must fail if any source can again pass through in its
# native unit, get rounded, or be double-converted.

from v2_decision.a2_lifecycle_sidecar import _decision_timestamp  # noqa: E402

_RC337_SECONDS = 1786383424.2295866          # the live-measured seconds-path value


def test_decision_timestamp_ms_int_preserved_exactly_without_float_round_trip():
    big = 2**53 + 1                          # would corrupt through a float round-trip
    assert _decision_timestamp({"decision_time_ms": big}) == big
    assert _decision_timestamp({"decision_time_ms": 1786383424954}) == 1786383424954


def test_decision_timestamp_every_seconds_source_truncates_exactly_once():
    want = int(_RC337_SECONDS * 1000)        # 1786383424229 — truncate, NOT round (…230)
    for field in ("decision_timestamp_utc", "_server_build_ts", "refresh_ts_utc"):
        got = _decision_timestamp({field: _RC337_SECONDS})
        assert got == want, f"{field}: {got} != {want} (unit or rounding drift)"
        assert isinstance(got, int)


def test_decision_timestamp_precedence_unchanged():
    assert _decision_timestamp(
        {"decision_time_ms": 123, "_server_build_ts": _RC337_SECONDS}) == 123
    assert _decision_timestamp(
        {"decision_timestamp_utc": 2.0, "_server_build_ts": 9.0}) == 2000


def test_decision_timestamp_rejects_non_clock_values_per_source_contract():
    # bool: True is `1`, not an instant — must fall through, not become 1000.
    assert _decision_timestamp({"_server_build_ts": True}) is None
    assert _decision_timestamp({"decision_time_ms": True, "refresh_ts_utc": 5.0}) == 5000
    # string: no proven producer emits one — numeric strings included.
    assert _decision_timestamp({"decision_time_ms": "1786383424954"}) is None
    assert _decision_timestamp({"refresh_ts_utc": "5.0"}) is None
    # zero and negative are not instants.
    assert _decision_timestamp({"decision_time_ms": 0}) is None
    assert _decision_timestamp({"decision_time_ms": -5}) is None
    assert _decision_timestamp({"refresh_ts_utc": -1.0}) is None
    # NaN / +inf / -inf fall through to the next usable source.
    assert _decision_timestamp(
        {"_server_build_ts": float("nan"), "refresh_ts_utc": 7.0}) == 7000
    assert _decision_timestamp(
        {"_server_build_ts": float("inf"), "refresh_ts_utc": 8.0}) == 8000
    assert _decision_timestamp({"refresh_ts_utc": float("-inf")}) is None


def test_decision_timestamp_overflow_is_handled_not_raised():
    # Python's own arithmetic decides unrepresentability: 1e307 * 1000 -> inf ->
    # int(inf) raises OverflowError, which must be handled as fall-through.
    assert _decision_timestamp({"_server_build_ts": 1e307}) is None
    assert _decision_timestamp({"_server_build_ts": 1e307, "refresh_ts_utc": 5.0}) == 5000


def test_decision_timestamp_absent_is_none_and_input_never_mutated():
    assert _decision_timestamp({}) is None
    snap = {"decision_time_ms": None, "_server_build_ts": 3.0}
    frozen = dict(snap)
    assert _decision_timestamp(snap) == 3000
    assert snap == frozen


def test_downstream_would_apply_field_is_epoch_ms_on_the_seconds_fallback_route():
    """The REAL production path, seconds branch: decision_time_ms absent, so the resolver
    must serve _server_build_ts as truncated epoch-ms — never raw seconds (the measured
    live defect) and never a rounded value."""
    ms = _ms()
    ms.pop("decision_time_ms", None)
    ms["_server_build_ts"] = _RC337_SECONDS
    preview = _a2(ms)["lifecycle"]["sidecar"]["projected_preview"]
    got = preview["would_apply_if_entered_at_time"]
    assert got == int(_RC337_SECONDS * 1000), (
        f"seconds route emitted {got!r} — expected truncated epoch-ms "
        f"{int(_RC337_SECONDS * 1000)} (raw seconds pass-through or rounding regressed)")
    assert isinstance(got, int)
