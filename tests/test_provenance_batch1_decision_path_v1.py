"""Provenance batch 1 — the direct TRADE / WAIT / AVOID inputs (RC-533).

ONE FAUCET = ONE COMPUTATION for the verdict the operator trades on:

* The multi-horizon verdict (final_bias / tradeable / wait_reason / size) has ONE owner,
  ``multi_horizon_decision.compute_multi_horizon_synthesis``. The guest-anchor veto that
  ``signals._compute_signals_impl`` used to write onto the owner's result AFTER the owner
  returned is now the owner's own input (``guest_anchor=``).
* Two engine parameters that no production caller ever passed are gone: the synthesis
  ``pool_weights`` (an alternate weighting seam; the calibration reader is the one source)
  and the admission gate's ``component`` (a constant).
* The batch's roots close in the provenance authority; the two that keep a second writer
  (``call_signal`` / ``call_conviction``: the trade-impacting route/quarantine veto and the
  Tier-C failure shell) stay OPEN by name.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

import governance.provenance_inventory as P
import governance.provenance_roots as R
import governance.provenance_rows as ROWS_MOD
from governed_stack_contract import GuestAnchorContext
from multi_horizon_decision import compute_multi_horizon_synthesis
from tests.test_issue18_multi_horizon_decision import _inp
from tests.test_multi_horizon_decision_numeric_contract_v1 import _canonical, _pred

REPO = Path(__file__).resolve().parents[1]

OWNER_FIELDS = {
    "tradeable", "size_modifier", "wait_reason", "final_bias", "final_tradeable",
    "final_confidence", "entry_state", "call_state", "call_forecast_state",
}
# The only files that may assign these as attributes: the owner (constructs its result)
# and the MarketState carrier (ms.<field> = owner's value).
ATTRIBUTE_WRITER_FILES = {"multi_horizon_decision.py", "market_state.py"}

BATCH_CLOSED = (
    "final_bias", "final_confidence", "final_tradeable", "entry_state", "wait_reason", "mhap_rows",
    "call_state", "call_forecast_state",
    "is_no_trade", "rec_strike", "rec_side", "call_option_right", "call_option_expiry",
    "bias_signal", "bias_resolved", "dte_warn",
)
BATCH_NOT_PROVEN = ("call_signal", "call_conviction")


def _anchor() -> GuestAnchorContext:
    return GuestAnchorContext(guest_ticker="XLK", anchor_ticker="QQQ", affiliation="sector", rationale="test")


# ── behavioural: the veto lives in the owner ─────────────────────────────────────────────

def test_guest_anchor_veto_is_applied_by_the_synthesis_owner():
    base = compute_multi_horizon_synthesis(_inp(), _pred(), _canonical(), None)
    anchored = compute_multi_horizon_synthesis(_inp(), _pred(), _canonical(), None, guest_anchor=_anchor())
    assert anchored.tradeable is False
    assert anchored.size_modifier == 0.0
    assert anchored.wait_reason == _anchor().wait_reason
    # Everything the anchor does not veto is the same verdict.
    assert anchored.final_bias == base.final_bias
    assert anchored.selected == base.selected
    assert anchored.hmap.keys() == base.hmap.keys()


def test_no_anchor_means_the_owner_verdict_is_untouched():
    a = compute_multi_horizon_synthesis(_inp(), _pred(), _canonical(), None)
    b = compute_multi_horizon_synthesis(_inp(), _pred(), _canonical(), None, guest_anchor=None)
    assert (a.tradeable, a.size_modifier, a.wait_reason, a.final_bias) == (
        b.tradeable, b.size_modifier, b.wait_reason, b.final_bias)


def test_the_guest_anchor_is_keyword_only_and_the_alternate_weight_seam_is_gone():
    args = P.function_args("multi_horizon_decision.py", "compute_multi_horizon_synthesis")
    assert "pool_weights" not in args
    assert "guest_anchor" in args
    with pytest.raises(TypeError):
        compute_multi_horizon_synthesis(_inp(), _pred(), _canonical(), None, _anchor())  # positional refused


def test_admission_gate_has_no_component_parameter():
    assert P.function_args("decision_gate.py", "evaluate_decision_path_admission") == ["path"]


# ── negative / mutation control: a second writer of the owner's result is caught ─────────

def _result_names_bound_to(tree: ast.AST, callee: str) -> set[str]:
    names: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call):
            f = n.value.func
            fname = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")
            if fname == callee:
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        names.add(t.id)
    return names


def second_writers_of_synthesis(source: str) -> list[tuple[int, str]]:
    """Attribute assignments onto a name bound from compute_multi_horizon_synthesis(...)."""
    tree = ast.parse(source)
    bound = _result_names_bound_to(tree, "compute_multi_horizon_synthesis")
    hits: list[tuple[int, str]] = []
    for n in ast.walk(tree):
        if isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            for t in targets:
                if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id in bound:
                    hits.append((n.lineno, t.attr))
    return hits


OLD_DEFECT = '''
def _compute_signals_impl(inp, pred_for_stack, canonical, mh_ml_fusion_bundle, _guest_anchor):
    mh_syn = compute_multi_horizon_synthesis(inp, pred_for_stack, canonical, mh_ml_fusion_bundle)
    if _guest_anchor is not None:
        mh_syn.tradeable = False
        mh_syn.size_modifier = 0.0
        mh_syn.wait_reason = _guest_anchor.wait_reason
    return mh_syn
'''


def test_mutation_control_the_old_second_writer_is_detected():
    hits = second_writers_of_synthesis(OLD_DEFECT)
    assert [a for _, a in hits] == ["tradeable", "size_modifier", "wait_reason"]


def test_the_orchestrator_passes_the_anchor_to_the_owner_and_writes_nothing_after():
    src = (REPO / "signals.py").read_text(encoding="utf-8", errors="replace")
    assert second_writers_of_synthesis(src) == []
    tree = ast.parse(src)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "compute_multi_horizon_synthesis"]
    assert len(calls) == 1
    assert [k.arg for k in calls[0].keywords] == ["guest_anchor"]


_NON_PRODUCTION_PREFIXES = (
    "tests/", "governance/", "tools/", "verification/", "research/", "scripts/", "calibration/", "arch_competition/",
)


def test_repo_wide_no_attribute_writer_of_the_verdict_outside_owner_and_carrier(repo_index):
    """Residual search: the defect class (writing the owner's verdict fields onto an object
    after the owner returned) has exactly zero instances in production code."""
    offenders: list[str] = []
    for rel_path, _text, tree in repo_index.items():
        rel = rel_path.as_posix()
        if tree is None or rel.startswith(_NON_PRODUCTION_PREFIXES) or rel in ATTRIBUTE_WRITER_FILES:
            continue
        for n in ast.walk(tree):
            if isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                targets = n.targets if isinstance(n, ast.Assign) else [n.target]
                for t in targets:
                    if isinstance(t, ast.Attribute) and t.attr in OWNER_FIELDS:
                        offenders.append(f"{rel}:{n.lineno} .{t.attr}")
    assert offenders == [], offenders


# ── provenance: the batch closes, the NOT_PROVEN pair stays open by name ─────────────────

def test_batch_roots_close_in_the_authority():
    idx = P.index(ROWS_MOD.ROWS)
    for field in BATCH_CLOSED:
        category, producer = R.MARKET_STATE[field]
        assert producer is not None, field
        ok, why = P.closes(producer, idx)
        assert ok, f"{field} -> {producer}: {why}"
        assert field not in R.OPEN_ROOTS
    for (file, fn) in (("call_engine.py", "compute_call"), ("call_engine.py", "compute_position_size"),
                       ("multi_horizon_decision.py", "compute_multi_horizon_synthesis"),
                       ("decision_gate.py", "evaluate_decision_path_admission")):
        for arg, producer in R.ENGINE_INPUTS[(file, fn)].items():
            assert producer is not None, f"{file}:{fn}/{arg}"
            ok, why = P.closes(producer, idx)
            assert ok, f"{file}:{fn}/{arg} -> {producer}: {why}"


def test_the_former_second_writer_survivors_now_close_on_the_owner():
    # Batch 1 left these OPEN because trade_impacting_gate rewrote them after The Call.
    # RC-534 moved the emission veto into the owner; the gate writes no verdict field now.
    idx = P.index(ROWS_MOD.ROWS)
    for field in BATCH_NOT_PROVEN:
        assert R.MARKET_STATE[field][1] == "call_engine.py:compute_call"
        assert P.closes(R.MARKET_STATE[field][1], idx)[0]
        assert field not in R.OPEN_ROOTS


def test_the_verdict_owner_row_names_the_anchor_as_its_input():
    idx = P.index(ROWS_MOD.ROWS)
    row = idx[("multi_horizon_decision.py", "compute_multi_horizon_synthesis")]
    assert "governed_stack_contract.py:resolve_guest_anchor_for_ticker" in row.producer_refs
    assert "multi_horizon_decision.py:_horizon_skill_weights_cached" in row.producer_refs


def test_guest_anchor_context_wait_reason_is_the_verdict_text():
    ctx = SimpleNamespace(wait_reason="anchored")
    out = compute_multi_horizon_synthesis(_inp(), _pred(), _canonical(), None, guest_anchor=ctx)
    assert out.wait_reason == "anchored" and out.tradeable is False
