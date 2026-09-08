"""Mechanical contract locks for universal card fidelity runtime harness."""
from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tools" / "run_universal_card_fidelity_runtime.py"
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


def _load_harness_module():
    name = "run_universal_card_fidelity_runtime"
    spec = importlib.util.spec_from_file_location(name, HARNESS)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _harness_source() -> str:
    return HARNESS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def ucf():
    return _load_harness_module()


def test_harness_file_is_approved_path_only():
    assert HARNESS.name == "run_universal_card_fidelity_runtime.py"
    assert "tools" in HARNESS.parts


def test_default_institutional_ticker_set_includes_base_and_guest(ucf):
    assert list(ucf.DEFAULT_BASE_TICKERS) == ["SPY", "QQQ", "IWM"]
    assert "NVDA" in ucf.DEFAULT_GUEST_TICKERS
    assert set(ucf.DEFAULT_INSTITUTIONAL_TICKERS) == {"SPY", "QQQ", "IWM", "NVDA"}


def test_cli_accepts_arbitrary_ticker_list(ucf):
    assert ucf.parse_ticker_list("AAPL, MSFT GOOG") == ["AAPL", "MSFT", "GOOG"]
    assert ucf.parse_ticker_list("  tsla  ") == ["TSLA"]


def test_same_validation_path_no_ticker_specific_branches_in_source():
    src = _harness_source()
    # Forbidden: hard-coded per-ticker expected directions or institutional pass shortcuts.
    forbidden = [
        'if ticker == "SPY"',
        "if ticker == 'SPY'",
        'ticker == "QQQ"',
        'expected_dir["SPY"]',
        "SPY_ONLY_PASS",
    ]
    for pat in forbidden:
        assert pat not in src, f"ticker-specific branch forbidden: {pat}"


def test_hardcoded_expected_values_not_by_ticker(ucf):
    payload_spy = {
        "mhap_rows": [
            {"horizon": "1c", "call": "LONG", "confidence": 0.55},
            {"horizon": "5c", "call": "WAIT", "confidence": 0.40},
            {"horizon": "15c", "call": "WAIT", "confidence": 0.45},
            {"horizon": "60c", "call": "SHORT", "confidence": 0.60},
        ],
        "final_bias": "WAIT",
        "final_tradeable": False,
        "entry_state": "no_setup",
    }
    payload_nvda = {
        "mhap_rows": [
            {"horizon": "1c", "call": "SHORT", "confidence": 0.33},
            {"horizon": "5c", "call": "LONG", "confidence": 0.77},
            {"horizon": "15c", "call": "WAIT", "confidence": 0.50},
            {"horizon": "60c", "call": "WAIT", "confidence": 0.41},
        ],
        "final_bias": "LONG",
        "final_tradeable": True,
        "entry_state": "armed",
    }
    exp_spy = ucf.derive_card_parity_expectations(payload_spy)
    exp_nvda = ucf.derive_card_parity_expectations(payload_nvda)
    assert exp_spy[0]["expected_state"] == "up"
    assert exp_nvda[0]["expected_state"] == "down"
    assert exp_spy != exp_nvda


def test_expected_values_derived_from_payload_not_ticker_identity(ucf):
    row = ucf.derive_horizon_parity(
        {"mhap_rows": [{"horizon": "1c", "call": "SHORT", "confidence": 0.42}]},
        "1c",
    )
    assert row["expected_state"] == "down"
    assert row["expected_pct"] == 42


def test_stability_gate_implemented_in_source():
    src = _harness_source()
    assert "poll_stability" in src
    assert "consecutive_stable_reads" in src
    assert "mhap_rows" in src
    assert ">= 4" in src or "n_mhap >= 4" in src


def test_browser_dom_parity_implemented_in_source():
    src = _harness_source()
    assert "capture_browser_dom_live_transport" in src
    assert "compare_dom_to_expectations" in src
    assert "playwright" in src.lower()


def test_orphan_field_table_includes_all_required_fields(ucf):
    payload = {
        "pred_headline": "Fusion: UP",
        "reversal_risk": 0.33,
        "reversal_label": "moderate",
        "call_headline": "WAIT — insufficient",
        "call_signal": "wait",
        "call_state": "WATCH",
        "call_forecast_state": "forming",
        "em_straddle_upper": 100.0,
        "em_straddle_lower": 99.0,
    }
    table = ucf.build_orphan_table(payload, {"body_text": "", "card_text": ""})
    for name in ucf.ORPHAN_FIELD_NAMES:
        assert name in table
        if name in payload and payload[name] not in (None, ""):
            assert table[name] != "ABSENT", name
    assert table["pred_headline"] == ucf.DESIGN_APPROVED_PENDING_EXPLANATION_RAIL
    assert table["reversal_risk"] == ucf.DESIGN_APPROVED_PENDING_RISK_RAIL
    assert table["reversal_label"] == ucf.DESIGN_APPROVED_PENDING_RISK_RAIL
    assert table["call_headline"] == "BACKEND_ONLY"
    assert table["call_signal"] == "SUPPORTING_UNRENDERED"
    assert table["call_state"] == "OPERATOR_DECISION_REQUIRED"
    assert table["EM_bounds"] == "BACKEND_ONLY"


def test_guest_required_for_institutional_pass(ucf):
    tickers = ["SPY", "QQQ", "IWM"]
    results = {
        t: {
            "stability": {"status": "STABLE", "consecutive_stable_reads": 3},
            "browser_dom": {"status": "OK", "live_transport": "CAPTURED", "parity_rows": [{"parity_status": "PARITY"}]},
        }
        for t in tickers
    }
    proof = ucf.evaluate_institutional_proof(
        tickers=tickers,
        ticker_results=results,
        require_browser_dom=True,
        require_live_transport=True,
        stable_reads_required=3,
    )
    assert proof["institutional_proof_status"] == "NOT_PROVEN"
    assert any("missing_guest" in r for r in proof["reasons"])


def test_spy_only_institutional_pass_blocked(ucf):
    results = {
        "SPY": {
            "stability": {"status": "STABLE", "consecutive_stable_reads": 3},
            "browser_dom": {"status": "OK", "live_transport": "CAPTURED", "parity_rows": [{"parity_status": "PARITY"}]},
        }
    }
    assert ucf.spy_only_institutional_pass_possible(results, 3) is True
    proof = ucf.evaluate_institutional_proof(
        tickers=["SPY"],
        ticker_results=results,
        require_browser_dom=True,
        require_live_transport=True,
        stable_reads_required=3,
    )
    assert proof["institutional_proof_status"] == "NOT_PROVEN"


def test_base_only_institutional_pass_blocked(ucf):
    tickers = ["SPY", "QQQ", "IWM"]
    results = {
        t: {
            "stability": {"status": "STABLE", "consecutive_stable_reads": 3},
            "browser_dom": {"status": "OK", "live_transport": "CAPTURED", "parity_rows": [{"parity_status": "PARITY"}]},
        }
        for t in tickers
    }
    assert ucf.base_only_institutional_pass_possible(tickers, results) is False


def test_institutional_pass_impossible_without_stability(ucf):
    tickers = ["SPY", "QQQ", "IWM", "NVDA"]
    results = {
        t: {
            "stability": {"status": "NOT_PROVEN", "consecutive_stable_reads": 0},
            "browser_dom": {"status": "OK", "live_transport": "CAPTURED", "parity_rows": [{"parity_status": "PARITY"}]},
        }
        for t in tickers
    }
    proof = ucf.evaluate_institutional_proof(
        tickers=tickers,
        ticker_results=results,
        require_browser_dom=True,
        require_live_transport=True,
        stable_reads_required=3,
    )
    assert proof["institutional_proof_status"] == "NOT_PROVEN"
    assert any("stability" in r for r in proof["reasons"])


def test_institutional_pass_impossible_without_browser_dom(ucf):
    tickers = ["SPY", "QQQ", "IWM", "NVDA"]
    results = {
        t: {
            "stability": {"status": "STABLE", "consecutive_stable_reads": 3},
            "browser_dom": {"status": "SKIP", "live_transport": "NOT_PROVEN"},
        }
        for t in tickers
    }
    proof = ucf.evaluate_institutional_proof(
        tickers=tickers,
        ticker_results=results,
        require_browser_dom=True,
        require_live_transport=True,
        stable_reads_required=3,
    )
    assert proof["institutional_proof_status"] == "NOT_PROVEN"
    assert any("browser_dom" in r for r in proof["reasons"])


def test_institutional_pass_impossible_without_live_transport(ucf):
    tickers = ["SPY", "QQQ", "IWM", "NVDA"]
    results = {
        t: {
            "stability": {"status": "STABLE", "consecutive_stable_reads": 3},
            "browser_dom": {
                "status": "OK",
                "live_transport": "NOT_PROVEN",
                "parity_rows": [{"parity_status": "PARITY"}],
            },
        }
        for t in tickers
    }
    proof = ucf.evaluate_institutional_proof(
        tickers=tickers,
        ticker_results=results,
        require_browser_dom=True,
        require_live_transport=True,
        stable_reads_required=3,
    )
    assert proof["institutional_proof_status"] == "NOT_PROVEN"
    assert any("live_transport" in r for r in proof["reasons"])


def _trusted_payload(**overrides) -> dict:
    base = {
        "ticker": "SPY",
        "analytics_stale": False,
        "analytics_pending_shell": False,
        "fusion_available": True,
        "mhap_rows": [
            {"horizon": "1c", "call": "LONG", "confidence": 0.61},
            {"horizon": "5c", "call": "WAIT", "confidence": 0.40},
            {"horizon": "15c", "call": "WAIT", "confidence": 0.45},
            {"horizon": "60c", "call": "WAIT", "confidence": 0.50},
        ],
        "final_bias": "WAIT",
        "final_tradeable": False,
        "entry_state": "no_setup",
    }
    base.update(overrides)
    return base


def _withheld_dom(label: str) -> dict:
    dim = "tf-signal-card tf-state-dim tf-signal-card--non-actionable tf-signal-card--card-trust-withheld"
    card = {"class": dim, "dir": label, "pct": label}
    plan_state = "STALE" if label == "STALE" else ("PENDING" if label == "PENDING" else "NO SETUP")
    return {
        "1c": dict(card),
        "5c": dict(card),
        "15c": dict(card),
        "60c": dict(card),
        "consolidated": {"class": dim, "dir": label, "pct": label},
        "plan_state": plan_state,
    }


def test_dom_parity_compare_horizon_and_plan(ucf):
    payload = _trusted_payload()
    expectations = ucf.derive_card_parity_expectations(payload)
    dom = {
        "1c": {"class": "tf-signal-card tf-state-up tf-glow-1", "dir": "LONG", "pct": "61%"},
        "5c": {"class": "tf-signal-card tf-state-dim", "dir": "NEUTRAL", "pct": "—"},
        "15c": {"class": "tf-signal-card tf-state-dim", "dir": "NEUTRAL", "pct": "—"},
        "60c": {"class": "tf-signal-card tf-state-dim", "dir": "NEUTRAL", "pct": "—"},
        "consolidated": {"class": "tf-signal-card tf-state-dim", "dir": "NEUTRAL"},
        "plan_state": "NO SETUP",
    }
    rows = ucf.compare_dom_to_expectations(
        expectations,
        dom,
        payload=payload,
        active_ticker="SPY",
    )
    assert rows[0]["parity_status"] == "PARITY"
    assert any(r["field"] == "PLAN_entry_state" and r["parity_status"] == "PARITY" for r in rows)


def test_harness_arg_parser_defaults(ucf):
    p = ucf.build_arg_parser()
    args = p.parse_args([])
    assert ucf.parse_ticker_list(args.tickers) == list(ucf.DEFAULT_INSTITUTIONAL_TICKERS)
    assert args.stable_reads == 3


def test_harness_module_is_valid_python():
    assert ast.parse(_harness_source()).body  # parses to a non-empty module (raises SyntaxError otherwise)


def test_evaluate_institutional_proof_all_green_with_guest(ucf):
    tickers = ["SPY", "QQQ", "IWM", "NVDA"]
    parity = [{"parity_status": "PARITY"} for _ in range(6)]
    results = {
        t: {
            "stability": {"status": "STABLE", "consecutive_stable_reads": 3},
            "browser_dom": {"status": "OK", "live_transport": "CAPTURED", "parity_rows": parity},
        }
        for t in tickers
    }
    proof = ucf.evaluate_institutional_proof(
        tickers=tickers,
        ticker_results=results,
        require_browser_dom=True,
        require_live_transport=True,
        stable_reads_required=3,
    )
    assert proof["institutional_proof_status"] == "PROVEN"
    assert proof["guest_tickers_present"] == ["NVDA"]


def test_z_score_and_expected_move_absent_classification(ucf):
    table = ucf.build_orphan_table({}, {})
    assert table["z_score"] == "ABSENT"
    assert table["expected_move"] == "ABSENT"


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


def test_execution_call_state_orphan_rendered_when_chip_matches(ucf):
    payload = {"call_state": "WATCH"}
    assert ucf.classify_orphan_field("call_state", payload, dom_snapshot={}) == "OPERATOR_DECISION_REQUIRED"
    snap = {
        "execution_chip_call_state": "WATCH",
        "execution_chip_text": "WATCH",
        "execution_chip_trusted": "true",
    }
    assert ucf.classify_orphan_field("call_state", payload, dom_snapshot=snap) == "RENDERED"
    active_payload = {"call_state": "ACTIVE"}
    withheld_snap = {
        "execution_chip_call_state": "ACTIVE",
        "execution_chip_text": "WITHHELD",
        "execution_chip_trusted": "false",
    }
    assert ucf.classify_orphan_field("call_state", active_payload, dom_snapshot=withheld_snap) == "RENDERED"


def test_orphan_field_table_call_state_not_operator_decision_when_rendered(ucf):
    payload = {
        "pred_headline": "Fusion: UP",
        "reversal_risk": 0.33,
        "reversal_label": "moderate",
        "call_headline": "WAIT — insufficient",
        "call_signal": "wait",
        "call_state": "WATCH",
        "em_straddle_upper": 100.0,
        "em_straddle_lower": 99.0,
    }
    table = ucf.build_orphan_table(
        payload,
        {
            "body_text": "",
            "card_text": "",
            "execution_chip_call_state": "WATCH",
            "execution_chip_text": "WATCH",
            "execution_chip_trusted": "true",
        },
    )
    assert table["call_state"] == "RENDERED"
    assert table["call_headline"] == "BACKEND_ONLY"
    assert table["call_signal"] == "SUPPORTING_UNRENDERED"
    assert table["pred_headline"] == ucf.DESIGN_APPROVED_PENDING_EXPLANATION_RAIL
    assert table["reversal_risk"] == ucf.DESIGN_APPROVED_PENDING_RISK_RAIL
    assert table["reversal_label"] == ucf.DESIGN_APPROVED_PENDING_RISK_RAIL


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


def test_call_signal_mh_promotion_path_classified(ucf):
    payload = {"call_signal": "long", "mh_promoted_directional": True}
    assert ucf.classify_orphan_field("call_signal", payload, dom_snapshot={}) == "OPERATOR_DECISION_REQUIRED"
    snap = {
        "mh_promotion_chip_visible": "true",
        "mh_promotion_chip_text": "MH PROMOTED LONG",
    }
    assert ucf.classify_orphan_field("call_signal", payload, dom_snapshot=snap) == "RENDERED"
    wait_payload = {"call_signal": "wait", "mh_promoted_directional": False}
    assert ucf.classify_orphan_field("call_signal", wait_payload, dom_snapshot={}) == "SUPPORTING_UNRENDERED"


def test_design_approved_pending_fields_not_rendered(ucf):
    payload = {
        "pred_headline": "Fusion: UP",
        "reversal_risk": 0.33,
        "reversal_label": "moderate",
    }
    table = ucf.build_orphan_table(payload, {"body_text": "", "card_text": ""})
    for field in ("pred_headline", "reversal_risk", "reversal_label"):
        status = table[field]
        assert status.startswith("DESIGN_APPROVED_PENDING_"), field
        assert status != "RENDERED", field


def test_non_target_orphan_fields_remain_operator_decision_required(ucf):
    payload = {
        "pred_headline": "Fusion: UP",
        "reversal_risk": 0.33,
        "reversal_label": "moderate",
        "call_headline": "WAIT — insufficient",
        "call_signal": "wait",
    }
    table = ucf.build_orphan_table(payload, {"body_text": "", "card_text": ""})
    assert table["call_headline"] == "BACKEND_ONLY"
    assert table["call_signal"] == "SUPPORTING_UNRENDERED"


def test_call_headline_backend_only_not_operator_orphan(ucf):
    reg = _load_card_consumer_contract()
    row = next(r for r in reg["fields"] if r["field_name"] == "call_headline")
    assert row["consumer_surface"] == "backend_only"
    assert row["operator_relevance"] == "backend_only"
    assert row["decision_status"] == "PROVEN"
    payload = {"call_headline": "WAIT — insufficient confirmation."}
    assert ucf.classify_orphan_field("call_headline", payload, dom_snapshot={}) == "BACKEND_ONLY"
    assert ucf.classify_orphan_field("call_headline", {}, dom_snapshot={}) == "ABSENT"
    table = ucf.build_orphan_table(payload, {"body_text": "WAIT — insufficient confirmation.", "card_text": ""})
    assert table["call_headline"] == "BACKEND_ONLY"


def test_call_headline_does_not_close_orphan_handling_overall(ucf):
    ticker_results = {
        "SPY": {
            "browser_dom": {
                "orphan_table": {
                    "call_headline": "BACKEND_ONLY",
                    "pred_headline": ucf.DESIGN_APPROVED_PENDING_EXPLANATION_RAIL,
                    "reversal_risk": ucf.DESIGN_APPROVED_PENDING_RISK_RAIL,
                }
            }
        }
    }
    assert ucf.evaluate_overall_card_fidelity(ticker_results) == "NOT_PROVEN"
    defects = ucf.collect_confirmed_defects(ticker_results)
    assert not any("call_headline=" in d for d in defects)
    assert any("pred_headline=DESIGN_APPROVED_PENDING_EXPLANATION_RAIL" in d for d in defects)


def test_call_signal_reclassification_remains_closed():
    reg = _load_card_consumer_contract()
    by_name = {row["field_name"]: row for row in reg["fields"]}
    assert by_name["call_signal"]["consumer_surface"] == "decision_rail_chip"
    assert by_name["call_signal"]["decision_status"] == "OPERATOR_DECISION_REQUIRED"
    assert by_name["call_state"]["consumer_surface"] == "execution_chip"
    assert reg["execution_channel"]["primary_field_today"] == "call_state"


def test_orphan_payload_handling_overall_stays_not_proven(ucf):
    assert ucf.evaluate_overall_card_fidelity({}) == "NOT_PROVEN"
    ticker_results = {
        "SPY": {
            "browser_dom": {
                "orphan_table": {
                    "pred_headline": ucf.DESIGN_APPROVED_PENDING_EXPLANATION_RAIL,
                    "call_signal": "SUPPORTING_UNRENDERED",
                    "call_state": "RENDERED",
                }
            }
        }
    }
    assert ucf.evaluate_overall_card_fidelity(ticker_results) == "NOT_PROVEN"
    defects = ucf.collect_confirmed_defects(ticker_results)
    assert any("pred_headline=DESIGN_APPROVED_PENDING_EXPLANATION_RAIL" in d for d in defects)
    assert not any("call_signal=" in d for d in defects)


def test_pred_headline_design_approved_pending_explanation_rail(ucf):
    reg = _load_card_consumer_contract()
    row = next(r for r in reg["fields"] if r["field_name"] == "pred_headline")
    assert row["consumer_surface"] == "explanation_rail"
    assert row["decision_status"] == "DESIGN_APPROVED_PENDING_UI"
    dr = row["design_record"]
    assert dr["proposed_dom_id"] == "#tf-explanation-rail"
    assert dr["authority"] == "supplemental_non_authoritative"
    assert dr["display_trust_gate"] == "analyticsCardTrustGate"
    assert dr["ui_status"] == "pending"
    assert dr["rendered"] is False
    assert ucf.classify_orphan_field("pred_headline", {"pred_headline": "Fusion: UP"}) == (
        ucf.DESIGN_APPROVED_PENDING_EXPLANATION_RAIL
    )


def test_reversal_pair_design_approved_pending_risk_rail(ucf):
    reg = _load_card_consumer_contract()
    risk = next(r for r in reg["fields"] if r["field_name"] == "reversal_risk")
    label = next(r for r in reg["fields"] if r["field_name"] == "reversal_label")
    for row in (risk, label):
        assert row["consumer_surface"] == "risk_rail_paired"
        assert row["decision_status"] == "DESIGN_APPROVED_PENDING_UI"
        assert row["design_record"]["proposed_dom_id"] == "#tf-reversal-risk-chip"
        assert row["design_record"]["display_trust_gate"] == "analyticsCardTrustGate"
        assert row["design_record"]["rendered"] is False
    assert risk["design_record"]["must_pair_with"] == "reversal_label"
    assert label["design_record"]["cannot_render_independently"] is True
    payload = {"reversal_risk": 0.31, "reversal_label": "moderate"}
    assert ucf.classify_orphan_field("reversal_risk", payload) == ucf.DESIGN_APPROVED_PENDING_RISK_RAIL
    assert ucf.classify_orphan_field("reversal_label", payload) == ucf.DESIGN_APPROVED_PENDING_RISK_RAIL


def test_reversal_label_cannot_close_independently(ucf):
    """Label without risk remains DESIGN_APPROVED_PENDING_RISK_RAIL — not independently PROVEN/CLOSED."""
    assert (
        ucf.classify_orphan_field("reversal_label", {"reversal_label": "high"}, dom_snapshot={})
        == ucf.DESIGN_APPROVED_PENDING_RISK_RAIL
    )
    reg = _load_card_consumer_contract()
    label = next(r for r in reg["fields"] if r["field_name"] == "reversal_label")
    assert label["design_record"]["derivative_of"] == "reversal_risk"
    assert label["decision_status"] != "PROVEN"


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


def test_orphan_payload_handling_overall_constant(ucf):
    assert ucf.ORPHAN_PAYLOAD_HANDLING_OVERALL_STATUS == "NOT_PROVEN"
    assert ucf.orphan_payload_handling_overall_status() == "NOT_PROVEN"


def test_harness_ui_dom_ids_not_wired_for_pending_surfaces(ucf):
    src = _harness_source()
    assert "#tf-explanation-rail" not in src
    assert "#tf-reversal-risk-chip" not in src
    assert "tf-explanation-rail" not in ucf.DOM_CARD_IDS.values()
    assert "tf-reversal-risk-chip" not in ucf.DOM_CARD_IDS.values()


def test_analytics_card_trust_gate_mirrors_ui_failure_reasons(ucf):
    reasons = {
        "no_payload": ucf.analytics_card_trust_gate(None)["reason"],
        "ticker_mismatch": ucf.analytics_card_trust_gate(
            {"ticker": "QQQ", "mhap_rows": [{}] * 4},
            active_ticker="SPY",
        )["reason"],
        "analytics_stale": ucf.analytics_card_trust_gate(
            _trusted_payload(analytics_stale=True), check_ticker=False
        )["reason"],
        "pending_shell": ucf.analytics_card_trust_gate(
            _trusted_payload(analytics_pending_shell=True), check_ticker=False
        )["reason"],
        "partial_tier_c": ucf.analytics_card_trust_gate(
            _trusted_payload(analytics_partial_tier_c=True), check_ticker=False
        )["reason"],
        "cache_refresh_in_progress": ucf.analytics_card_trust_gate(
            _trusted_payload(
                analytics_refresh_in_progress=True,
                _update_source="client_ticker_cache",
            ),
            check_ticker=False,
        )["reason"],
        "mhap_missing": ucf.analytics_card_trust_gate(
            _trusted_payload(mhap_rows=[]), check_ticker=False
        )["reason"],
        "fusion_unavailable": ucf.analytics_card_trust_gate(
            _trusted_payload(fusion_available=False), check_ticker=False
        )["reason"],
    }
    assert set(reasons.values()) == set(reasons.keys())


def test_stale_withheld_not_dom_mismatch_when_dom_matches_contract(ucf):
    payload = _trusted_payload(analytics_stale=True)
    expectations = ucf.derive_card_parity_expectations(payload)
    rows = ucf.compare_dom_to_expectations(
        expectations,
        _withheld_dom("STALE"),
        payload=payload,
        active_ticker="SPY",
    )
    assert all(r["parity_status"] == ucf.PARITY_STATUS_STALE_WITHHELD for r in rows)
    assert ucf.parity_status_passes_ui_fidelity(ucf.PARITY_STATUS_STALE_WITHHELD)


def test_pending_withheld_not_dom_mismatch(ucf):
    payload = _trusted_payload(analytics_pending_shell=True)
    expectations = ucf.derive_card_parity_expectations(payload)
    rows = ucf.compare_dom_to_expectations(
        expectations,
        _withheld_dom("PENDING"),
        payload=payload,
        active_ticker="SPY",
    )
    assert all(r["parity_status"] == ucf.PARITY_STATUS_PENDING_WITHHELD for r in rows)


def test_degraded_withheld_for_fusion_unavailable(ucf):
    payload = _trusted_payload(fusion_available=False)
    expectations = ucf.derive_card_parity_expectations(payload)
    rows = ucf.compare_dom_to_expectations(
        expectations,
        _withheld_dom("DEGRADED"),
        payload=payload,
        active_ticker="SPY",
    )
    assert all(r["parity_status"] == ucf.PARITY_STATUS_DEGRADED_WITHHELD for r in rows)


def test_ticker_mismatch_withheld_classification(ucf):
    payload = _trusted_payload(ticker="QQQ")
    expectations = ucf.derive_card_parity_expectations(payload)
    rows = ucf.compare_dom_to_expectations(
        expectations,
        _withheld_dom("WITHHELD"),
        payload=payload,
        active_ticker="SPY",
    )
    assert all(r["parity_status"] == ucf.PARITY_STATUS_TICKER_MISMATCH_WITHHELD for r in rows)


def test_missing_mhap_withheld_classification(ucf):
    payload = _trusted_payload(mhap_rows=[])
    expectations = ucf.derive_card_parity_expectations(payload)
    rows = ucf.compare_dom_to_expectations(
        expectations,
        _withheld_dom("PENDING"),
        payload=payload,
        active_ticker="SPY",
    )
    assert all(r["parity_status"] == ucf.PARITY_STATUS_MISSING_MHAP_WITHHELD for r in rows)


def test_trusted_dom_mismatch_remains_fail(ucf):
    payload = _trusted_payload()
    expectations = ucf.derive_card_parity_expectations(payload)
    dom = {
        "1c": {"class": "tf-signal-card tf-state-down", "dir": "SHORT", "pct": "61%"},
        "5c": {"class": "tf-signal-card tf-state-dim", "dir": "NEUTRAL", "pct": "—"},
        "15c": {"class": "tf-signal-card tf-state-dim", "dir": "NEUTRAL", "pct": "—"},
        "60c": {"class": "tf-signal-card tf-state-dim", "dir": "NEUTRAL", "pct": "—"},
        "consolidated": {"class": "tf-signal-card tf-state-dim", "dir": "NEUTRAL"},
        "plan_state": "NO SETUP",
    }
    rows = ucf.compare_dom_to_expectations(
        expectations,
        dom,
        payload=payload,
        active_ticker="SPY",
    )
    assert rows[0]["parity_status"] == ucf.PARITY_STATUS_DOM_MISMATCH
    assert not ucf.parity_status_passes_ui_fidelity(rows[0]["parity_status"])


def test_untrusted_bad_withheld_dom_remains_dom_mismatch(ucf):
    payload = _trusted_payload(analytics_stale=True)
    expectations = ucf.derive_card_parity_expectations(payload)
    dom = _withheld_dom("STALE")
    dom["1c"] = {"class": "tf-signal-card tf-state-up", "dir": "LONG", "pct": "44%"}
    rows = ucf.compare_dom_to_expectations(
        expectations,
        dom,
        payload=payload,
        active_ticker="SPY",
    )
    assert rows[0]["parity_status"] == ucf.PARITY_STATUS_DOM_MISMATCH


def test_stale_withheld_blocks_institutional_proof_non_rth(ucf):
    parity = [{"parity_status": ucf.PARITY_STATUS_STALE_WITHHELD} for _ in range(6)]
    tickers = ["SPY", "QQQ", "IWM", "NVDA"]
    results = {
        t: {
            "stability": {
                "status": "STABLE",
                "consecutive_stable_reads": 3,
                "payload": {"session_label": "After-Hours"},
            },
            "browser_dom": {
                "status": "OK",
                "live_transport": "CAPTURED",
                "parity_rows": parity,
                "session_label": "After-Hours",
            },
        }
        for t in tickers
    }
    proof = ucf.evaluate_institutional_proof(
        tickers=tickers,
        ticker_results=results,
        require_browser_dom=True,
        require_live_transport=True,
        stable_reads_required=3,
    )
    assert proof["institutional_proof_status"] == "NOT_PROVEN"
    assert any("stale_withheld_non_rth_not_admissible" in r for r in proof["reasons"])
    assert not any("dom_parity_mismatch" in r for r in proof["reasons"])


def test_stale_withheld_rth_counts_as_freshness_fail(ucf):
    parity = [{"parity_status": ucf.PARITY_STATUS_STALE_WITHHELD} for _ in range(6)]
    tickers = ["SPY", "QQQ", "IWM", "NVDA"]
    results = {
        t: {
            "stability": {
                "status": "STABLE",
                "consecutive_stable_reads": 3,
                "payload": {"session_label": "Regular Trading Hours"},
            },
            "browser_dom": {
                "status": "OK",
                "live_transport": "CAPTURED",
                "parity_rows": parity,
                "session_label": "Regular Trading Hours",
            },
        }
        for t in tickers
    }
    proof = ucf.evaluate_institutional_proof(
        tickers=tickers,
        ticker_results=results,
        require_browser_dom=True,
        require_live_transport=True,
        stable_reads_required=3,
    )
    assert any("stale_withheld_rth_freshness_expected" in r for r in proof["reasons"])


def test_trust_aware_acceptance_semantics_documented(ucf):
    sem = ucf.TRUST_AWARE_ACCEPTANCE_SEMANTICS
    assert sem["trust_withheld_ui_fidelity"] == "PASS"
    assert sem["stale_withheld_non_rth_closure"] == "NOT_ADMISSIBLE"
    assert sem["stale_withheld_rth_freshness"] == "FAIL"
    assert sem["true_dom_mismatch"] == "FAIL"
    assert sem["card_fidelity_overall"] == "NOT_PROVEN"


def test_card_consumer_contract_fidelity_classification_v1(ucf):
    reg = _load_card_consumer_contract()
    fc = reg.get("fidelity_classification_v1") or {}
    assert fc.get("card_fidelity_overall") == "NOT_PROVEN"
    assert ucf.PARITY_STATUS_STALE_WITHHELD in (fc.get("parity_status_vocabulary") or [])
    assert fc.get("acceptance_semantics", {}).get("true_dom_mismatch") == "FAIL"


def test_harness_source_declares_trust_aware_compare():
    src = _harness_source()
    assert "analytics_card_trust_gate" in src
    assert "STALE_WITHHELD" in src
    assert "compare_dom_to_expectations" in src
    assert "trust_reason_to_withheld_parity_status" in src


def test_card_consumer_contract_field_lineage_vocabulary_v1(ucf):
    reg = _load_card_consumer_contract()
    vocab = reg.get("field_lineage_vocabulary_v1") or {}
    assert vocab.get("payload_key") == "field_lineage"
    assert vocab.get("unknown_when_unproven") is True
    minimum = vocab.get("trade_determinative_minimum_fields") or []
    assert "mhap_rows" in minimum
    assert "fusion_triplets" in minimum


# ── HARNESS_CLASSIFIER_OPERATOR_MIRROR_ALIGNMENT_V1 — operator-mirror scoring ──


def _mirror_payload(*, actionable: bool, reason=None, codes=None, trust_state=None, bias="WAIT") -> dict:
    """Ticker-agnostic fresh-analytics payload with S2B operator mirror fields."""
    return {
        "ticker": "ZZTKR",
        "analytics_stale": False,
        "analytics_pending_shell": False,
        "fusion_available": True,
        "final_bias": bias,
        "final_tradeable": False,
        "entry_state": "no_setup",
        "mhap_rows": [
            {"horizon": h, "call": "WAIT", "confidence": 0.34}
            for h in ("1c", "5c", "15c", "60c")
        ],
        "operator_card_actionable": actionable,
        "operator_actionability_reason": reason,
        "operator_stale_reason_codes": codes or [],
        "operator_card_trust_state": trust_state,
    }


def _veto_dom_cards() -> dict:
    """DOM matching the UI preserveRawContext veto render: values + veto marker."""
    card = {
        "class": "tf-signal-card tf-state-dim tf-signal-card--non-actionable "
                 "tf-signal-card--operator-actionability-veto",
        "dir": "NEUTRAL",
        "pct": "34%",
        "cardTrustWithhold": "quote_newer_than_signal",
    }
    return {
        "1c": dict(card), "5c": dict(card), "15c": dict(card), "60c": dict(card),
        "consolidated": {
            "class": "tf-signal-card tf-state-dim tf-signal-card--non-actionable "
                     "tf-signal-card--operator-actionability-veto",
            "dir": "NEUTRAL",
            "cardTrustWithhold": "quote_newer_than_signal",
        },
        "plan_state": "STALE",
    }


def test_case_a_quote_newer_veto_expected_stale_not_no_setup(ucf):
    payload = _mirror_payload(
        actionable=False,
        reason="quote_newer_than_signal",
        codes=["quote_newer_than_signal", "mhap_older_than_quote"],
        trust_state="REFRESHING",
    )
    trust = ucf.resolve_card_trust_gate(payload, active_ticker="ZZTKR")
    assert trust["trusted"] is False
    assert trust["authority"] == ucf.SCORING_AUTHORITY_OPERATOR_MIRROR
    assert ucf.operator_mirror_withhold_label(trust) == "STALE"
    exp = ucf.derive_card_parity_expectations(payload)
    rows = ucf.compare_dom_to_expectations(exp, _veto_dom_cards(), payload=payload, active_ticker="ZZTKR")
    plan = next(r for r in rows if r["field"] == "PLAN_entry_state")
    assert plan["expected_withheld_plan_state"] == "STALE"
    assert plan["parity_status"] == ucf.PARITY_STATUS_QUOTE_VETO_WITHHELD


def test_case_b_actionable_true_preserves_trusted_scoring(ucf):
    payload = _mirror_payload(actionable=True)
    trust = ucf.resolve_card_trust_gate(payload, active_ticker="ZZTKR")
    assert trust["trusted"] is True
    exp = ucf.derive_card_parity_expectations(payload)
    cards = _veto_dom_cards()
    for k in ("1c", "5c", "15c", "60c", "consolidated"):
        cards[k]["class"] = "tf-signal-card tf-state-dim"
        cards[k]["cardTrustWithhold"] = ""
    cards["plan_state"] = "NO SETUP"
    rows = ucf.compare_dom_to_expectations(exp, cards, payload=payload, active_ticker="ZZTKR")
    assert all(r["parity_status"] == ucf.PARITY_STATUS_PARITY for r in rows)


def test_case_c_refreshing_without_veto_no_false_stale(ucf):
    payload = _mirror_payload(actionable=True, trust_state="REFRESHING")
    trust = ucf.resolve_card_trust_gate(payload, active_ticker="ZZTKR")
    assert trust["trusted"] is True
    assert trust["reason"] is None


def test_case_d_missing_mirror_fields_labeled_legacy_fallback(ucf):
    payload = _mirror_payload(actionable=True)
    for k in ("operator_card_actionable", "operator_actionability_reason",
              "operator_stale_reason_codes", "operator_card_trust_state"):
        payload.pop(k)
    trust = ucf.resolve_card_trust_gate(payload, active_ticker="ZZTKR")
    assert trust["authority"] == ucf.SCORING_AUTHORITY_LEGACY_DEGRADED
    assert trust["trusted"] is True  # legacy gate on a fresh payload


def test_case_e_payload_and_dom_stale_under_quote_veto_scores_pass(ucf):
    payload = _mirror_payload(
        actionable=False, reason="quote_newer_than_signal",
        codes=["quote_newer_than_signal"], trust_state="REFRESHING",
    )
    exp = ucf.derive_card_parity_expectations(payload)
    rows = ucf.compare_dom_to_expectations(exp, _veto_dom_cards(), payload=payload, active_ticker="ZZTKR")
    assert all(r["parity_status"] != ucf.PARITY_STATUS_DOM_MISMATCH for r in rows)
    assert all(ucf.parity_status_passes_ui_fidelity(r["parity_status"]) for r in rows)
    assert all(r.get("scoring_authority") == ucf.SCORING_AUTHORITY_OPERATOR_MIRROR for r in rows)


def test_case_f_same_scoring_path_across_base_style_payloads(ucf):
    outcomes = []
    for tkr in ("SPY", "QQQ", "IWM"):  # fixture data only — never conditional logic
        payload = _mirror_payload(
            actionable=False, reason="quote_newer_than_signal",
            codes=["quote_newer_than_signal"], trust_state="REFRESHING",
        )
        payload["ticker"] = tkr
        exp = ucf.derive_card_parity_expectations(payload)
        rows = ucf.compare_dom_to_expectations(exp, _veto_dom_cards(), payload=payload, active_ticker=tkr)
        outcomes.append([r["parity_status"] for r in rows])
    assert outcomes[0] == outcomes[1] == outcomes[2]


def test_case_g_guest_style_payload_uses_identical_path(ucf):
    payload = _mirror_payload(
        actionable=False, reason="quote_newer_than_signal",
        codes=["quote_newer_than_signal"], trust_state="REFRESHING",
    )
    payload["ticker"] = "NVDA"  # guest fixture data only
    exp = ucf.derive_card_parity_expectations(payload)
    rows = ucf.compare_dom_to_expectations(exp, _veto_dom_cards(), payload=payload, active_ticker="NVDA")
    assert all(r["parity_status"] == ucf.PARITY_STATUS_QUOTE_VETO_WITHHELD or
               r["parity_status"] == ucf.PARITY_STATUS_PARITY for r in rows)


def test_reason_code_table_decides_not_actionable_boolean(ucf):
    """SPY-like vs QQQ-like: same actionable=false, DIFFERENT expected card state —
    the reason-code → label table decides, never the boolean, never the ticker."""
    spy_like = _mirror_payload(
        actionable=False, reason="quote_newer_than_signal",
        codes=["quote_newer_than_signal", "mhap_older_than_quote"], trust_state="REFRESHING",
    )
    qqq_like = _mirror_payload(
        actionable=False, reason="missing_quote_ts",
        codes=["missing_quote_ts"], trust_state="REFRESHING",
    )
    t_spy = ucf.resolve_card_trust_gate(spy_like, active_ticker="ZZTKR")
    t_qqq = ucf.resolve_card_trust_gate(qqq_like, active_ticker="ZZTKR")
    assert t_spy["trusted"] is False and t_qqq["trusted"] is False  # same boolean...
    assert ucf.operator_mirror_withhold_label(t_spy) == "STALE"      # ...different labels
    assert ucf.operator_mirror_withhold_label(t_qqq) == "WITHHELD"
    assert ucf.expected_plan_state_for_withheld_label("STALE") == "STALE"
    assert ucf.expected_plan_state_for_withheld_label("WITHHELD") == "NO SETUP"
    # Parity statuses diverge accordingly; both pass UI fidelity.
    s_spy = ucf.trust_reason_to_withheld_parity_status("quote_newer_than_signal")
    s_qqq = ucf.trust_reason_to_withheld_parity_status("missing_quote_ts")
    assert s_spy == ucf.PARITY_STATUS_QUOTE_VETO_WITHHELD
    assert s_qqq == ucf.PARITY_STATUS_TRUST_WITHHELD
    assert ucf.parity_status_passes_ui_fidelity(s_spy) and ucf.parity_status_passes_ui_fidelity(s_qqq)
    # End-to-end: QQQ-like PLAN expectation is NO SETUP through the same path.
    exp = ucf.derive_card_parity_expectations(qqq_like)
    cards = _veto_dom_cards()
    cards["plan_state"] = "NO SETUP"
    rows = ucf.compare_dom_to_expectations(exp, cards, payload=qqq_like, active_ticker="ZZTKR")
    plan = next(r for r in rows if r["field"] == "PLAN_entry_state")
    assert plan["expected_withheld_plan_state"] == "NO SETUP"
    assert plan["parity_status"] == ucf.PARITY_STATUS_TRUST_WITHHELD


def test_classifier_functions_have_no_ticker_conditional_branches():
    """Ticker-agnostic construction lock: scoring functions contain no ticker literals."""
    import ast as _ast

    src = _harness_source()
    tree = _ast.parse(src)
    scoring_fns = {
        "resolve_card_trust_gate", "operator_mirror_withhold_label",
        "card_trust_operator_label", "trust_reason_to_withheld_parity_status",
        "compare_dom_to_expectations", "has_operator_card_mirror_fields",
    }
    for node in _ast.walk(tree):
        if isinstance(node, _ast.FunctionDef) and node.name in scoring_fns:
            seg = _ast.get_source_segment(src, node) or ""
            for lit in ("SPY", "QQQ", "IWM", "NVDA", "AAPL", "MSFT"):
                assert f'"{lit}"' not in seg and f"'{lit}'" not in seg, (
                    f"ticker literal {lit} inside scoring function {node.name}"
                )

