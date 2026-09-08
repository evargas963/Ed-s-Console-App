"""RC-534 — The Call is the ONE computation authority for call_signal / call_conviction.

Before: trade_impacting_gate.apply_trade_impacting_gate rewrote the verdict (call_signal → wait,
call_conviction → low, nested call.signal, trade_valid, a fabricated validation_summary) AFTER
compute_call had produced it, on quarantine or a non-production route — while call_option_right,
is_no_trade, rec_strike, headline and plan stayed derived from the pre-veto verdict.

After: server._fetch_state validates the emission facts ONCE (route class + market-data sanity)
before the state is built; they ride on SignalInput; compute_call vetoes itself; the gate stamps
the quarantine fact and blocks decision_id / persistence / actionability and rewrites nothing.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path
from types import SimpleNamespace

import governance.provenance_inventory as P
import governance.provenance_roots as R
import governance.provenance_rows as ROWS_MOD
from call_engine import WAIT_BLOCKER_REASON_EMISSION, compute_call
from signal_types import CanonicalForecast, PredictiveCard, RulesCard
from tests.mvp_test_fixtures import minimal_mvp_features
from tests.test_call_prediction_vote import _inp
from trade_impacting_gate import (
    apply_trade_impacting_gate,
    revalidate_cached_decision,
    validate_trade_impacting_gate,
)

REPO = Path(__file__).resolve().parents[1]
VERDICT_KEYS = {"call_signal", "call_conviction"}


# ── a directional setup (the same one test_call_prediction_vote proves reaches LONG) ──────

def _directional_kwargs() -> dict:
    canonical = CanonicalForecast(
        direction="up", probability_up=0.47, probability_down=0.30, probability_flat=0.23,
        confidence="low", provenance="bayesian_fusion",
    )
    rules = RulesCard(
        headline="Test", headline_1m="", detail="", zone_label="UP", zone_color="#fff",
        signal="long", conviction="low", alerts=[],
        micro=SimpleNamespace(
            regime="TREND_UP", structure_support=448.0, structure_resist=452.0, bos=None,
            sweeps=[], last_sweep=None, is_compressing=False, compression_bars=0,
        ),
    )
    pred = PredictiveCard(
        headline="Lean UP", prediction_dir="up", prediction_target=None,
        historical_5c_dominant_dir="up", historical_5c_dominant_prob=0.47, empirical_confidence="low",
        forward_direction=canonical.direction, forward_prob_up=canonical.probability_up,
        forward_prob_down=canonical.probability_down, forward_prob_flat=canonical.probability_flat,
        forward_confidence=canonical.confidence, forward_provenance=canonical.provenance,
        samples_used=40, model_note="weak lean", timeframe_reads={},
        up_prob_5c=0.47, down_prob_5c=0.30, flat_prob_5c=0.23,
    )
    return dict(
        rules=rules, pred=pred,
        regime=SimpleNamespace(primary="trend_continuation", confidence="medium"),
        fusion=SimpleNamespace(
            available=True, dominant_direction="flat", fusion_dominant_direction="flat",
            model_agreement=0.72, n_sources_active=2, fusion_confidence="low",
            reversal_posterior=0.25, continuation_posterior=0.2, breakout_posterior=0.2,
            mc_available=True, mc_containment=0.45, mc_expansion=0.4, mc_eae=0.8, mc_efe=1.0,
        ),
        vol_regime=SimpleNamespace(vol_regime="normal", trade_permissive=True,
                                   conviction_multiplier=1.0, risk_multiplier=1.0),
        canonical=canonical,
        mvp_features=minimal_mvp_features(zone="pin_bull"),
    )


def _call(inp):
    kw = _directional_kwargs()
    return compute_call(inp, kw.pop("rules"), kw.pop("pred"), **kw)


# ── behavioural: the owner vetoes itself on the emission facts ───────────────────────────

def test_baseline_setup_is_directional_and_no_fact_is_not_a_veto():
    assert _call(_inp()).signal == "long"
    assert _call(dataclasses.replace(_inp(), production_emission_allowed=None)).signal == "long"
    assert _call(dataclasses.replace(_inp(), production_emission_allowed=True)).signal == "long"


def test_owner_vetoes_on_quarantine_and_carries_the_reasons():
    inp = dataclasses.replace(
        _inp(), production_emission_allowed=False,
        emission_block_reasons=("price_out_of_sanity_range:0.01 not in [50.0, 2000.0] for SPY",),
    )
    call = _call(inp)
    assert call.signal == "wait"
    assert call.conviction == "low"
    wb = call.wait_blocker
    assert wb["reason"] == WAIT_BLOCKER_REASON_EMISSION
    assert wb["gated_signal"] == "long"
    assert wb["emission_block_reasons"] == list(inp.emission_block_reasons)
    # Everything coupled to the verdict follows WAIT inside the owner: no directional plan.
    assert call.trade_type not in ("long", "short")
    assert call.size_cue in ("SKIP", "NONE", "0", "") or "skip" in str(call.size_cue).lower()


def test_non_production_route_and_bad_spot_fail_closed_through_the_owner():
    for facts, route in (
        ({"ticker": "SPY", "spot": 450.0, "spread_age_ms": 0}, "server.api.debug_prediction"),
        ({"ticker": "SPY", "spot": 0.01, "spread_age_ms": 0}, "server._fetch_state"),
        ({"ticker": "SPY", "spot": 450.0, "spread_age_ms": 10_000_000}, "server._fetch_state"),
        ({"ticker": "SPY", "spot": 450.0, "spread_age_ms": 0}, "server._fetch_state.no_valid_expiry"),
    ):
        g = validate_trade_impacting_gate(facts, route=route)
        assert g.production_emission_allowed is False, (facts, route)
        inp = dataclasses.replace(_inp(), production_emission_allowed=g.production_emission_allowed,
                                  emission_block_reasons=tuple(g.reasons))
        call = _call(inp)
        assert call.signal == "wait" and call.wait_blocker["reason"] == WAIT_BLOCKER_REASON_EMISSION, route
    ok = validate_trade_impacting_gate({"ticker": "SPY", "spot": 450.0, "spread_age_ms": 0}, route="server._fetch_state")
    assert ok.production_emission_allowed is True
    assert _call(dataclasses.replace(_inp(), production_emission_allowed=True,
                                     emission_block_reasons=tuple(ok.reasons))).signal == "long"


# ── the gate stamps facts and blocks; it rewrites no verdict field ────────────────────────

def test_apply_gate_rewrites_no_verdict_field_on_quarantine():
    ms = {"ticker": "SPY", "spot": 0.01, "call_signal": "long", "call_conviction": "high",
          "validation_summary": "risk_ok", "call": {"signal": "long"}}
    before = dict(ms)
    result = apply_trade_impacting_gate(ms, route="server._fetch_state")
    assert result.quarantined and not result.production_emission_allowed
    assert ms["market_data_quarantine"]["active"] is True
    for k in ("call_signal", "call_conviction", "validation_summary", "call"):
        assert ms[k] == before[k], k
    assert "trade_valid" not in ms


def test_stale_cache_serve_blocks_actionability_and_manufactures_no_wait():
    md = {"ticker": "SPY", "spot": 500.0, "call_signal": "short", "call_conviction": "medium",
          "validation_summary": "risk_ok"}
    out = revalidate_cached_decision(md, route="server._tier_c_analytics_json_response", stale=True)
    assert out["tier_c_cache_gate_ok"] is False
    assert out["market_data_quarantine"]["active"] is True
    assert out["call_signal"] == "short" and out["call_conviction"] == "medium"


# ── wiring: one route, one gate fact, computed before the state is built ────────────────

def test_server_validates_the_emission_facts_once_before_build_and_hands_them_to_the_owner():
    src = (REPO / "server.py").read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    fetch = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_fetch_state")
    calls = {}
    for n in ast.walk(fetch):
        if isinstance(n, ast.Call):
            name = n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", "")
            if name in ("validate_trade_impacting_gate", "build_market_state", "resolve_fetch_state_decision_route"):
                calls.setdefault(name, []).append(n)
    assert len(calls["validate_trade_impacting_gate"]) == 1
    assert len(calls["resolve_fetch_state_decision_route"]) == 1  # one route resolution per fetch
    gate_line = calls["validate_trade_impacting_gate"][0].lineno
    bms = calls["build_market_state"][0]
    assert gate_line < bms.lineno
    assert any(k.arg == "emission_gate" for k in bms.keywords)


def test_market_state_hands_the_facts_to_signal_input_and_derives_identity_after_the_call():
    src = (REPO / "market_state.py").read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "build_market_state")
    assert any(a.arg == "emission_gate" for a in fn.args.kwonlyargs)
    sig = next(n for n in ast.walk(fn) if isinstance(n, ast.Call)
               and isinstance(n.func, ast.Name) and n.func.id == "SignalInput")
    kws = {k.arg for k in sig.keywords}
    assert {"production_emission_allowed", "emission_block_reasons"} <= kws
    # Option identity derives from ms.call_signal AFTER the call: one verdict, coherent fields.
    oe = next(n for n in ast.walk(fn) if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Name) and n.func.id == "recommend_option_expression")
    assert any(k.arg == "call_signal" and ast.unparse(k.value) == "ms.call_signal" for k in oe.keywords)
    assert oe.lineno > sig.lineno


# ── mutation control: the old second writer is detected; the live modules scan clean ─────

def verdict_writers(source: str) -> list[tuple[int, str]]:
    """Subscript writes of call_signal/call_conviction and attribute writes of .signal/.conviction."""
    hits: list[tuple[int, str]] = []
    for n in ast.walk(ast.parse(source)):
        if isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            for t in targets:
                if isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant) and t.slice.value in VERDICT_KEYS:
                    hits.append((n.lineno, str(t.slice.value)))
                if isinstance(t, ast.Attribute) and t.attr in ("signal", "conviction"):
                    hits.append((n.lineno, "." + t.attr))
    return hits


OLD_GATE_REWRITE = '''
def apply_trade_impacting_gate(ms_dict, *, route):
    result = validate_trade_impacting_gate(ms_dict, route=route)
    if result.quarantined or result.route_class != "production":
        ms_dict["trade_valid"] = False
        if ms_dict.get("call_signal") in ("long", "short"):
            ms_dict["call_signal"] = "wait"
            ms_dict["call_conviction"] = "low"
    return result
'''


def test_mutation_control_old_gate_rewrite_is_detected():
    assert [k for _, k in verdict_writers(OLD_GATE_REWRITE)] == ["call_signal", "call_conviction"]


def test_gate_bundle_and_record_modules_write_no_verdict():
    for rel in ("trade_impacting_gate.py", "live_decision_bundle.py", "decision_record.py"):
        assert verdict_writers((REPO / rel).read_text(encoding="utf-8", errors="replace")) == [], rel


# ── repo-wide residual: the only verdict writers are the owner, the carrier and flagged shells ──

_NON_PRODUCTION_PREFIXES = ("tests/", "governance/", "tools/", "verification/", "research/", "scripts/",
                            "calibration/", "arch_competition/")
_NO_DECISION_MARKERS = {"state_error", "analytics_pending_shell", "analytics_partial_tier_c"}
_HARNESS_FUNCTIONS = {"production_like_decision_emission", "_post_fetch_state_ms_stub"}  # decision_record test harnesses


def _enclosing_function(tree: ast.AST, lineno: int):
    best = None
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.lineno <= lineno <= n.end_lineno:
            if best is None or n.lineno > best.lineno:
                best = n
    return best


def test_repo_wide_every_verdict_literal_is_a_flagged_no_decision_sentinel(repo_index):
    """A dict literal or key write that carries call_signal outside the owner/carrier must be a
    no-decision shell (flagged by state_error / pending / partial) and must read 'wait' — never a
    computed or directional verdict."""
    offenders: list[str] = []
    for rel_path, _text, tree in repo_index.items():
        rel = rel_path.as_posix()
        if tree is None or rel.startswith(_NON_PRODUCTION_PREFIXES) or rel in ("call_engine.py", "market_state.py"):
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.Dict):
                keys = {k.value for k in n.keys if isinstance(k, ast.Constant)}
                if VERDICT_KEYS & keys:
                    fn = _enclosing_function(tree, n.lineno)
                    if fn is not None and fn.name in _HARNESS_FUNCTIONS:
                        continue
                    vals = {k.value: v for k, v in zip(n.keys, n.values) if isinstance(k, ast.Constant)}
                    verdict_vals = [v for k, v in vals.items() if k in VERDICT_KEYS]
                    if not any(isinstance(v, ast.Constant) for v in verdict_vals):
                        continue  # a relay of the owner's value (record / provenance / calibration), not a writer
                    sig = vals.get("call_signal")
                    if not (keys & _NO_DECISION_MARKERS) or not (isinstance(sig, ast.Constant) and sig.value == "wait"):
                        offenders.append(f"{rel}:{n.lineno} dict literal")
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant) and t.slice.value in VERDICT_KEYS:
                        fn = _enclosing_function(tree, n.lineno)
                        body_src = ast.unparse(fn) if fn is not None else ""
                        if not (isinstance(n.value, ast.Constant) and n.value.value == "wait"
                                and any(m in body_src for m in _NO_DECISION_MARKERS)):
                            offenders.append(f"{rel}:{n.lineno} key write")
    assert offenders == [], offenders


# ── provenance: both verdict roots close on the owner; the gate is the owner's input ──────

def test_verdict_roots_close_on_compute_call_with_the_gate_as_input():
    idx = P.index(ROWS_MOD.ROWS)
    for field in ("call_signal", "call_conviction"):
        cat, producer = R.MARKET_STATE[field]
        assert producer == "call_engine.py:compute_call", field
        ok, why = P.closes(producer, idx)
        assert ok, why
        assert field not in R.OPEN_ROOTS
    row = idx[("call_engine.py", "compute_call")]
    assert "trade_impacting_gate.py:validate_trade_impacting_gate" in row.producer_refs
    gate = idx[("trade_impacting_gate.py", "validate_trade_impacting_gate")]
    assert gate.producer_refs == ("server.py:_fetch_state",)
