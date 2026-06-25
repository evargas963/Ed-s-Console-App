"""Mechanical contract locks for universal card fidelity runtime harness."""
from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tools" / "run_universal_card_fidelity_runtime.py"


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
