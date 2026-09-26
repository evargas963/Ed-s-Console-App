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
from pathlib import Path

import governance.provenance_inventory as P
import governance.provenance_roots as R
import governance.provenance_rows as ROWS_MOD

REPO = Path(__file__).resolve().parents[1]
VERDICT_KEYS = {"call_signal", "call_conviction"}


# ── a directional setup (the same one test_call_prediction_vote proves reaches LONG) ──────





# ── behavioural: the owner vetoes itself on the emission facts ───────────────────────────







# ── the gate stamps facts and blocks; it rewrites no verdict field ────────────────────────





# ── wiring: one route, one gate fact, computed before the state is built ────────────────





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
    no-decision shell (flagged by state_error / pending / partial) and must carry NO verdict
    (None) — never a computed or directional one. (2026-09-24, operator rule no fallbacks: the
    shells used to say "wait" / "low" -- a trading instruction nobody computed.)"""
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
                    if not (keys & _NO_DECISION_MARKERS) or any(
                            isinstance(v, ast.Constant) and v.value is not None for v in verdict_vals):
                        offenders.append(f"{rel}:{n.lineno} dict literal")
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant) and t.slice.value in VERDICT_KEYS:
                        fn = _enclosing_function(tree, n.lineno)
                        body_src = ast.unparse(fn) if fn is not None else ""
                        if not (isinstance(n.value, ast.Constant) and n.value.value is None
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


