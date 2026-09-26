"""Production coherence: one directional-authorization authority, one MC-conditioning authority,
MC separated from predictive conviction, and canonical MC horizon semantics.

The four defects were one failure: a fact is derived where its inputs are known, thrown away, then
re-derived downstream from whatever weaker inputs are in scope.

SECTION A RULING (operator, 2026-08-29): active_bundle_contract — the serving/promotion contract —
is the authority on the approved composition. It is NOT weakened here and no model is retrained.
On the current tree that means 5c directional authorization is FALSE, because zero tickers satisfy
the 5c bundle contract. The 5c xgb_plus_transformer runtime blend may still COMPUTE for
diagnostics; it simply inherits no directional authorization. The runtime-vs-bundle-contract
divergence is reported separately as NOT_PROVEN, not resolved by blessing the runtime branch.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import monte_carlo  # noqa: E402

TRI = {"up": 0.55, "down": 0.25, "flat": 0.20}


def _code_only(src: str) -> str:
    """Python source with ALL comments and docstrings removed, EXACTLY — via ast, not heuristics.

    The first version of this helper dropped only lines whose first non-space character was `#`.
    That left TRAILING comments and docstring BODIES in the text, so a control asserting
    "construct X is gone" could be satisfied or defeated by prose that merely mentions X — which is
    the precise failure mode these ONE-FAUCET controls exist to catch. `ast.unparse` emits code
    only; docstrings are stripped explicitly below. Quotes are normalised because unparse
    re-renders string literals in its own style.
    """
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree).replace('"', "'")


def _composition(
    *,
    produced,
    required=("xgb", "lstm", "transformer"),
    compliant=True,
    executed_computation="meta_stack",
):
    missing = [r for r in required if r not in produced]
    return {
        "authorization_schema_version": 1,
        "horizon": "1c", "required": list(required), "produced": list(produced),
        "missing": missing, "collapsed": [], "contract_compliant": compliant,
        "contract_issues": [] if compliant else ["synthetic: bundle contract not satisfied"],
        "approved_computation": "meta_stack",
        "executed_computation": executed_computation,
        "computation_compliant": executed_computation == "meta_stack",
        "complete": bool(
            compliant and not missing and executed_computation == "meta_stack"
        ),
    }


def _layer(available=True, up=0.55, dn=0.25, flat=0.20):
    return SimpleNamespace(available=available, prob_up=up, prob_down=dn, prob_flat=flat)


# ── CONTROL 3: complete approved composition authorizes ───────────────────────────────────────


# ── CONTROL 2: partial / noncompliant composition stays unauthorized ──────────────────────────












# ── CONTROL 1 & 4 (MC): unauthorized ML => base_neutral; MC cannot create conviction ───────────












# ── CONTROL 5: canonical MC horizon semantics ─────────────────────────────────────────────────
def test_mc_emits_wall_clock_minutes_from_the_canonical_constant():
    assert monte_carlo.BAR_MINUTES == 1, "BAR_MINUTES is the canonical authority"
    out = monte_carlo.simulate(spot=450.0, iv=0.18, horizon_bars=5, n_paths=500, seed=42)
    assert out.available is True
    assert out.horizon_bars == 5
    assert out.horizon_minutes == 5, "a 5-bar horizon is ~5m fwd, never 25m"


# test_the_ui_consumes_the_transported_minutes_and_holds_no_time_authority (CONTROL 5's
# display half) was retired here (/console cutover, operator directive 2026-09-14): it checked
# legacy static/index.html for a d.mc_horizon_minutes reader, but the new console's Trade Desk
# explicitly defers all horizon signals as NOT_PROVEN ("THE CALL and 1m/5m/15m/60m horizons
# remain excluded until ticker-universal evidence earns them" -- ed-trade-desk.js's own text) —
# there is no MC-horizon display to hold this control against. CONTROL 5's backend half
# (test_mc_emits_wall_clock_minutes_from_the_canonical_constant above) is unaffected.


# ── CONTROL 6: weak fusion may not authorize a directional horizon ────────────────────────────




# ── CONTROL 7: ONE FAUCET — the verdict is transported, never recomputed ──────────────────────








# ── PRODUCER <-> GATE binding (added after adversarial review) ────────────────────────────────






