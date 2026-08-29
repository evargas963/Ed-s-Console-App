"""STACK-WIRE-3 — call_engine + prediction_engine overlay (FIND-WIRE3-1..7)."""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import call_engine
import prediction_engine as pe
from time_et import RTH_OPEN_MINS, RTH_START_MINS

from tests.test_call_time_warning import (
    _minimal_input,
    _minimal_rules_pred_regime_fusion,
)


def _ce_src() -> str:
    return inspect.getsource(call_engine)


def _pe_src() -> str:
    return inspect.getsource(pe)


def test_call_engine_reads_timeframe_60m_not_legacy_1h():
    src = inspect.getsource(call_engine.compute_call)
    assert '_tf.get("60m"' in src
    assert '_tf.get("1h"' not in src

    captured: list[dict] = []

    def _fake_call_readiness(inp, **kwargs):
        captured.append(inp if isinstance(inp, dict) else vars(inp) if hasattr(inp, "__dict__") else inp)
        return SimpleNamespace(
            readiness_score=50,
            call_state="WAIT",
            forecast_state="dormant",
            reasons=[],
            missing=[],
            component_scores={},
        )

    rules, pred, regime, fusion, vol_regime, canonical = _minimal_rules_pred_regime_fusion()
    pred.timeframe_reads = {"60m": "Uptrend test signal"}
    inp = _minimal_input(mins_to_close=300.0)

    with patch("setup_readiness.compute_call_readiness", _fake_call_readiness):
        with patch("setup_readiness.compute_put_readiness", _fake_call_readiness):
            call_engine.compute_call(
                inp,
                rules,
                pred,
                regime=regime,
                fusion=fusion,
                vol_regime=vol_regime,
                canonical=canonical,
                mvp_features={"zone": "pin_bull", "vwap_side": "above"},
            )

    assert captured
    assert captured[0].get("structure_higher_tf") == "Uptrend test signal"


def test_rth_open_mins_single_authority_call_engine_prediction_engine():
    assert RTH_OPEN_MINS == RTH_START_MINS == 570
    stop_src = inspect.getsource(call_engine._stop_distance)
    assert "570" not in stop_src
    assert "RTH_OPEN_MINS" in stop_src
    overlay_src = inspect.getsource(pe.build_fusion_model_overlay_for_stack)
    assert "(inp.et_hour - 9) * 60 + (inp.et_minute - 30)" not in overlay_src
    assert "RTH_OPEN_MINS" in overlay_src


def test_exec_mode_derives_from_exec_modes_dict():
    sizing_src = inspect.getsource(call_engine.compute_position_size)
    assert "elif r_units <= 0.30" not in sizing_src
    assert "_exec_mode_for_r_units" in sizing_src
    assert call_engine._exec_mode_for_r_units(0.0) == "NO_TRADE"
    assert call_engine._exec_mode_for_r_units(0.01) == "PROBE"
    assert call_engine._exec_mode_for_r_units(0.30) == "PROBE"
    assert call_engine._exec_mode_for_r_units(0.31) == "REDUCED"
    assert call_engine._exec_mode_for_r_units(0.55) == "REDUCED"
    assert call_engine._exec_mode_for_r_units(0.56) == "STANDARD"
    assert call_engine._exec_mode_for_r_units(1.00) == "STANDARD"
    assert call_engine._exec_mode_for_r_units(1.01) == "MAX"
    assert call_engine._exec_mode_for_r_units(1.25) == "MAX"


def test_wait_blocker_reason_constants_exist_and_used():
    assert call_engine.WAIT_BLOCKER_REASON_STACK == "stack"
    assert call_engine.WAIT_BLOCKER_REASON_TIME == "time"
    src = inspect.getsource(call_engine.compute_call)
    assert '"reason": "stack"' not in src
    assert '"reason": "time"' not in src
    assert "WAIT_BLOCKER_REASON_STACK" in src
    assert "WAIT_BLOCKER_REASON_TIME" in src


def test_call_engine_threshold_constants_exist_and_used():
    assert call_engine.VIX_EXTREME_THRESHOLD == 35.0
    assert call_engine.MINS_TO_CLOSE_REDUCE_SIZE == 120
    assert call_engine.MINS_TO_CLOSE_NO_NEW_ENTRIES == 30
    assert call_engine.CONF_MULT_VERY_LOW == 0.25
    assert call_engine.CONFLUENCE_TOTAL_SOURCES == 8
    assert call_engine.MC_EAE_GATE_EXPANSION == 2.5
    assert call_engine.MC_EAE_GATE_CONTAINED == 1.5
    assert call_engine.AGREE_THRESHOLD_UNSTABLE == 0.50
    assert call_engine.MODEL_AGREEMENT_CUT_THRESHOLD == 0.35
    assert call_engine.MODEL_AGREEMENT_BOOST_THRESHOLD == 0.80

    body = _ce_src()
    tail = body[body.index("def compute_position_size") :]
    banned = [
        r"(?<![\w.])35(?![\w.])",
        r"(?<![\w.])120(?![\w.])",
        r"(?<![\w.])30(?![\w.])",
        r"(?<![\w.])25(?![\w.])",
        r"(?<![\w.])2\.0(?![\w.])",
        r"(?<![\w.])2\.5(?![\w.])",
        r"(?<![\w.])1\.5(?![\w.])",
        r"(?<![\w.])0\.50(?![\w.])",
        r"(?<![\w.])0\.45(?![\w.])",
        r"(?<![\w.])0\.80(?![\w.])",
        r"(?<![\w.])0\.35(?![\w.])",
    ]
    for pat in banned:
        assert re.search(pat, tail) is None, f"literal still in call_engine body: {pat}"


def test_prediction_engine_threshold_constants_exist_and_used():
    assert pe.MC_EAE_EFE_AMPLIFY_THRESHOLD == 1.2
    assert pe.CANONICAL_DOM_PROB_PREDICTION_DIR_MIN == 0.45
    assert pe.MOVE_SEVERITY_SEVERE_PCT_OF_SPOT == 0.004
    assert pe.CONTAINMENT_LOW_THRESHOLD == 0.40

    body = _pe_src()
    marker = "AVG_OUTCOME_MIN_SAMPLES"
    tail = body[body.index(marker) + len(marker) :]
    banned = [
        r"(?<![\w.])0\.45(?![\w.])",
        r"(?<![\w.])0\.004(?![\w.])",
        r"(?<![\w.])0\.002(?![\w.])",
        r"(?<![\w.])1\.2(?![\w.])",
        r"(?<![\w.])1\.3(?![\w.])",
        r"(?<![\w.])0\.40(?![\w.])",
        r"(?<![\w.])0\.60(?![\w.])",
        r"(?<![\w.])0\.50(?![\w.])",
    ]
    for pat in banned:
        assert re.search(pat, tail) is None, f"literal still in prediction_engine body: {pat}"


def test_prediction_engine_probs_variable_naming_consistent():
    overlay_src = inspect.getsource(pe.build_fusion_model_overlay_for_stack)
    core_src = inspect.getsource(pe.compute_prediction_core)
    assert "probs_15m" not in overlay_src
    assert "probs_60m" not in overlay_src
    assert "probs_15c" in overlay_src
    assert "probs_60c" in overlay_src
    assert "probs_15m" not in core_src
    assert "probs_60m" not in core_src


def test_tradability_gates_use_authority_only():
    ce = inspect.getsource(call_engine.compute_call)
    pe_enrich = inspect.getsource(pe.compute_prediction_enrichment)
    assert 'provenance == "bayesian_fusion"' not in ce
    assert 'provenance != "fusion_unavailable"' not in ce
    assert "canonical_provenance_is_tradable" in ce
    assert "fusion_has_tradable_direction" in ce
    assert "is_canonical_tradable" in pe_enrich or "fusion_is_authoritative" in pe_enrich


def test_no_legacy_timeframe_keys_in_call_engine_consumer_source():
    root = Path(__file__).resolve().parents[1]
    src = (root / "call_engine.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    allowed = {"15m", "60m"}
    bad: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "get":
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        if not isinstance(node.args[0].value, str):
            continue
        base = func.value
        if isinstance(base, ast.Name) and base.id == "_tf":
            key = node.args[0].value
            if key not in allowed:
                bad.append(key)
    assert bad == []
