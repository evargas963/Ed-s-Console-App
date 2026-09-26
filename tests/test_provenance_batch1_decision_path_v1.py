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




# ── behavioural: the veto lives in the owner ─────────────────────────────────────────────









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







