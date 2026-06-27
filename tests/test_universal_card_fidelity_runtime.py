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
CARD_CONSUMER_CONTRACT = ROOT / "governance" / "artifacts" / "CARD_CONSUMER_CONTRACT_V1.json"

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
    {"PROVEN", "NOT_PROVEN", "OPERATOR_DECISION_REQUIRED", "BACKEND_ONLY"}
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
    required = set(ucf.ORPHAN_FIELD_NAMES) | {"EM_bounds"}
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
    assert table["pred_headline"] == "OPERATOR_DECISION_REQUIRED"
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


def test_dom_parity_compare_horizon_and_plan(ucf):
    payload = {
        "mhap_rows": [{"horizon": "1c", "call": "LONG", "confidence": 0.61}],
        "final_bias": "WAIT",
        "final_tradeable": False,
        "entry_state": "no_setup",
    }
    expectations = ucf.derive_card_parity_expectations(payload)
    dom = {
        "1c": {"class": "tf-signal-card tf-state-up tf-glow-1", "dir": "LONG", "pct": "61%"},
        "5c": {"class": "tf-signal-card tf-state-dim", "dir": "NEUTRAL", "pct": "—"},
        "15c": {"class": "tf-signal-card tf-state-dim", "dir": "NEUTRAL", "pct": "—"},
        "60c": {"class": "tf-signal-card tf-state-dim", "dir": "NEUTRAL", "pct": "—"},
        "consolidated": {"class": "tf-signal-card tf-state-dim", "dir": "NEUTRAL"},
        "plan_state": "NO SETUP",
    }
    rows = ucf.compare_dom_to_expectations(expectations, dom)
    assert rows[0]["parity_status"] == "PARITY"
    assert any(r["field"] == "PLAN_entry_state" and r["parity_status"] == "PARITY" for r in rows)


def test_harness_arg_parser_defaults(ucf):
    p = ucf.build_arg_parser()
    args = p.parse_args([])
    assert ucf.parse_ticker_list(args.tickers) == list(ucf.DEFAULT_INSTITUTIONAL_TICKERS)
    assert args.stable_reads == 3


def test_harness_module_is_valid_python():
    ast.parse(_harness_source())


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
    assert reg["artifact"] == "governance/artifacts/CARD_CONSUMER_CONTRACT_V1.json"
    assert len(reg.get("contract_rules") or []) >= 10
    fields = reg.get("fields") or []
    assert len(fields) >= 20
    for row in fields:
        missing = _REQUIRED_FIELD_KEYS - set(row)
        assert not missing, f"{row.get('field_name')}: missing {missing}"


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
    for orphan in (
        "pred_headline",
        "reversal_risk",
        "reversal_label",
        "call_signal",
    ):
        assert orphan in by_name
        assert by_name[orphan]["decision_status"] == "OPERATOR_DECISION_REQUIRED"
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
    assert table["pred_headline"] == "OPERATOR_DECISION_REQUIRED"


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


def test_non_target_orphan_fields_remain_operator_decision_required(ucf):
    payload = {
        "pred_headline": "Fusion: UP",
        "reversal_risk": 0.33,
        "reversal_label": "moderate",
        "call_headline": "WAIT — insufficient",
        "call_signal": "wait",
    }
    table = ucf.build_orphan_table(payload, {"body_text": "", "card_text": ""})
    for field in ("pred_headline", "reversal_risk", "reversal_label"):
        assert table[field] == "OPERATOR_DECISION_REQUIRED", field
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
                    "pred_headline": "OPERATOR_DECISION_REQUIRED",
                    "reversal_risk": "OPERATOR_DECISION_REQUIRED",
                }
            }
        }
    }
    assert ucf.evaluate_overall_card_fidelity(ticker_results) == "NOT_PROVEN"
    defects = ucf.collect_confirmed_defects(ticker_results)
    assert not any("call_headline=" in d for d in defects)
    assert any("pred_headline=OPERATOR_DECISION_REQUIRED" in d for d in defects)


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
                    "pred_headline": "OPERATOR_DECISION_REQUIRED",
                    "call_signal": "SUPPORTING_UNRENDERED",
                    "call_state": "RENDERED",
                }
            }
        }
    }
    assert ucf.evaluate_overall_card_fidelity(ticker_results) == "NOT_PROVEN"
    defects = ucf.collect_confirmed_defects(ticker_results)
    assert any("pred_headline=OPERATOR_DECISION_REQUIRED" in d for d in defects)
    assert not any("call_signal=" in d for d in defects)
