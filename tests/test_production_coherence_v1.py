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

import governed_stack_contract as gsc  # noqa: E402
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


def _js_code_only(src: str) -> str:
    """JS source with `//` line comments removed — same reason as _code_only.

    This is not hypothetical: the comment that documents the removed `else { hzFusionOk = true; }`
    fallback quotes it verbatim, so a raw-text control asserting that construct is gone reads its
    own explanation and fails. Controls must see CODE.
    """
    out = []
    for ln in src.splitlines():
        i = ln.find("//")
        out.append(ln if i < 0 else ln[:i])
    return "\n".join(out)


def _composition(*, produced, required=("xgb", "lstm", "transformer"), compliant=True):
    missing = [r for r in required if r not in produced]
    return {
        "horizon": "1c", "required": list(required), "produced": list(produced),
        "missing": missing, "collapsed": [], "contract_compliant": compliant,
        "contract_issues": [] if compliant else ["synthetic: bundle contract not satisfied"],
        "complete": bool(compliant and not missing),
    }


def _layer(available=True, up=0.55, dn=0.25, flat=0.20):
    return SimpleNamespace(available=available, prob_up=up, prob_down=dn, prob_flat=flat)


# ── CONTROL 3: complete approved composition authorizes ───────────────────────────────────────
def test_complete_approved_composition_is_authorized():
    """Proves the repair does not accidentally require an unrelated model: exactly the approved
    legs, contract satisfied => authorized."""
    ok, reason = gsc.unified_stack_team_can_authorize(
        xgb_out=_layer(), lstm_out=_layer(), transformer_out=_layer(),
        stack_probs=TRI, stack_probs_composition=_composition(
            produced=("xgb", "lstm", "transformer")))
    assert ok is True, reason
    assert reason.startswith("composition_complete:")


# ── CONTROL 2: partial / noncompliant composition stays unauthorized ──────────────────────────
def test_a_single_surviving_leg_cannot_forge_authorization():
    """THE defect, measured on this tree: _weighted_average_partial renormalises one surviving leg
    to weight 1.0, so a lone xgb produced {'up':0.55,'down':0.25,'flat':0.2} — a complete-LOOKING
    triplet that the old shape test authorized as 'stack_probs_meta_or_weighted'."""
    ok, reason = gsc.unified_stack_team_can_authorize(
        xgb_out=_layer(), lstm_out=_layer(available=False, up=None, dn=None, flat=None),
        transformer_out=_layer(available=False, up=None, dn=None, flat=None),
        stack_probs=TRI, stack_probs_composition=_composition(produced=("xgb",)))
    assert ok is False
    assert "composition_incomplete" in reason and "lstm" in reason and "transformer" in reason


def test_contract_noncompliant_composition_is_unauthorized_even_when_all_legs_produced():
    """The ruling: the serving/promotion contract is authority. Every leg producing is NOT enough
    if the bundle contract itself is unsatisfied — which is the live 5c state on this tree."""
    ok, reason = gsc.unified_stack_team_can_authorize(
        xgb_out=_layer(), lstm_out=_layer(), transformer_out=_layer(),
        stack_probs=TRI,
        stack_probs_composition=_composition(
            produced=("xgb", "lstm", "transformer"), compliant=False))
    assert ok is False
    assert reason.startswith("composition_contract_noncompliant")


def test_missing_composition_record_is_unauthorized_not_assumed():
    ok, reason = gsc.unified_stack_team_can_authorize(
        xgb_out=_layer(), lstm_out=_layer(), transformer_out=_layer(),
        stack_probs=TRI, stack_probs_composition=None)
    assert ok is False and reason == "composition_unknown"


def test_the_live_5c_composition_on_this_tree_is_unauthorized():
    """Anchors the ruling to reality: 5c requires meta_stack per active_bundle_contract and ZERO
    meta_*_5c artifacts exist, so no 5c bundle is compliant and 5c cannot authorize."""
    from ml_predict import stack_probs_composition_record
    rec = stack_probs_composition_record("SPY", "5c", {"xgb": TRI, "lstm": None, "transformer": TRI})
    assert rec["complete"] is False
    ok, reason = gsc.unified_stack_team_can_authorize(
        xgb_out=_layer(), lstm_out=_layer(available=False, up=None, dn=None, flat=None),
        transformer_out=_layer(), stack_probs=TRI, stack_probs_composition=rec)
    assert ok is False, reason


# ── CONTROL 1 & 4 (MC): unauthorized ML => base_neutral; MC cannot create conviction ───────────
def test_unauthorized_composition_means_mc_fails_closed_to_base_neutral():
    for reason_src in (gsc.UNIFORM_NO_STACK_TRI_CLASS_SIGNAL, "average_available_ml_layers"):
        assert gsc.mc_team_should_fail_closed(False, reason_src) is True


def test_mc_may_never_increase_dominant_or_margin():
    """CONTROL 4 — knife-edge around dominant .38 / margin .03. Argmax preservation is not enough:
    tradeability reads those two scalars (multi_horizon_decision.py:863-864). The clamp is a
    monotonicity constraint on exactly them; it does not read or tune the thresholds."""
    from dataclasses import dataclass

    import mc_fusion_adjustment as mcf

    @dataclass
    class _P:
        available: bool = True
        prob_up: float = 0.0
        prob_down: float = 0.0
        prob_flat: float = 0.0
        canonical_provenance: str = "ok"
        mc_post_fusion_audit: dict | None = None

    def _dm(t):
        s = sorted(t, reverse=True)
        return s[0], s[0] - s[1]

    # A knife-edge NON-tradeable state: dominant just under .38, margin just under .03.
    pre = (0.375, 0.355, 0.270)
    pre_dom, pre_margin = _dm(pre)
    assert pre_dom < 0.38 and pre_margin < 0.03, "premise: starts non-tradeable"

    mc_out = SimpleNamespace(
        available=True,
        mc_feature_dict=lambda: {"source": "derived_mc_normalized", "expected_move": 0.5,
                                 "volatility": 0.4, "skew": 0.0, "tail_risk": 0.02,
                                 "directional_bias": 0.05},
    )
    out = mcf.fuse_payload_apply_mc_adjustment(
        _P(prob_up=pre[0], prob_down=pre[1], prob_flat=pre[2]), mc_out, 450.0)
    post = (out.prob_up, out.prob_down, out.prob_flat)
    post_dom, post_margin = _dm(post)
    assert post_dom <= pre_dom + 1e-9, f"MC raised dominant {pre_dom}->{post_dom}"
    assert post_margin <= pre_margin + 1e-9, f"MC widened margin {pre_margin}->{post_margin}"
    # and it therefore cannot have crossed a non-tradeable state into tradeable
    assert not (post_dom >= 0.38 and post_margin >= 0.03)


def test_mc_may_still_soften_an_authorized_state():
    """CONTROL 4 (inverse half) — one-way means DOWNGRADE IS ALLOWED, behaviourally.

    The first version of this guard VETOED the whole adjustment whenever either scalar rose, which
    silently restored conviction MC had just removed. Measured on this tree before the repair: of
    20,775 exact-sum-1 triplets driven by the real feature keys, 73.7% of adjustments were
    discarded and 211 came back TRADEABLE after MC had made them WAIT. This is that exact case —
    dominance rises while margin collapses, so the veto fired and the softening was lost.
    """
    from dataclasses import dataclass

    import mc_fusion_adjustment as mcf

    @dataclass
    class _P:
        available: bool = True
        prob_up: float = 0.0
        prob_down: float = 0.0
        prob_flat: float = 0.0
        canonical_provenance: str = "ok"
        mc_post_fusion_audit: dict | None = None

    def _dm(t):
        s = sorted(t, reverse=True)
        return s[0], s[0] - s[1]

    pre = (0.25, 0.39, 0.36)
    pre_dom, pre_margin = _dm(pre)
    assert pre_dom >= 0.38 and pre_margin >= 0.03, "premise: starts TRADEABLE"

    mc_out = SimpleNamespace(
        available=True,
        mc_feature_dict=lambda: {"source": "derived_mc_normalized", "expected_move": 0.9,
                                 "volatility": 0.0148 * 450.0, "skew": -0.04,
                                 "tail_risk": 0.1, "directional_bias": -0.2},
    )
    out = mcf.fuse_payload_apply_mc_adjustment(
        _P(prob_up=pre[0], prob_down=pre[1], prob_flat=pre[2]), mc_out, 450.0)
    post = (out.prob_up, out.prob_down, out.prob_flat)
    post_dom, post_margin = _dm(post)

    assert post != pre, "the softening must survive — a veto here restores conviction MC removed"
    assert post_margin < pre_margin, "MC's downgrade must reach the stored triplet"
    assert not (post_dom >= 0.38 and post_margin >= 0.03), "MC made it WAIT; it must STAY WAIT"
    # and the cap still holds in the authority-increasing direction
    assert post_dom <= pre_dom + 1e-9 and post_margin <= pre_margin + 1e-9


# ── CONTROL 5: canonical MC horizon semantics ─────────────────────────────────────────────────
def test_mc_emits_wall_clock_minutes_from_the_canonical_constant():
    assert monte_carlo.BAR_MINUTES == 1, "BAR_MINUTES is the canonical authority"
    out = monte_carlo.simulate(spot=450.0, iv=0.18, horizon_bars=5, n_paths=500, seed=42)
    assert out.available is True
    assert out.horizon_bars == 5
    assert out.horizon_minutes == 5, "a 5-bar horizon is ~5m fwd, never 25m"


def test_the_ui_consumes_the_transported_minutes_and_holds_no_time_authority():
    """CONTROL 5 (display half): the browser must not multiply bars by a constant of its own."""
    ui = (ROOT / "static" / "index.html").read_text(encoding="utf-8", errors="replace")
    assert "d.mc_horizon_minutes" in ui, "UI must read the transported wall-clock value"
    assert "parseInt(d.mc_horizon, 10) * 5" not in ui, "the second time authority must be gone"
    assert "(5-min MC steps)" not in ui, "on-screen text contradicted BAR_MINUTES=1"


# ── CONTROL 6: weak fusion may not authorize a directional horizon ────────────────────────────
def test_setup_fusion_alone_cannot_light_a_directional_horizon():
    """The old fallback read `else { hzFusionOk = true; }` — a MISSING per-horizon map authorized
    EVERY horizon from bundle-level setup availability alone.

    That fallback was not a rare edge: `horizon_fusion_available` is not a MarketState field, so it
    is absent from /api/state on every tick and the fallback was ALWAYS taken. The second assertion
    proves that, so the first is not merely pinning text."""
    import market_state

    ui = _js_code_only((ROOT / "static" / "index.html").read_text(encoding="utf-8", errors="replace"))
    assert "hzFusionOk = true" not in ui, "the assume-authorized fallback must be gone"
    assert "hzFusionOk = false" in ui, "a missing per-horizon map must withhold"
    assert "horizon_fusion_available" not in market_state.MarketState.__dataclass_fields__, \
        "if this field ever IS emitted, the fallback stops being the always-taken branch and this " \
        "control must be rewritten to exercise the map itself"


def test_stack_health_requires_the_transported_verdict_and_cannot_substitute():
    """classify_stack_health may no longer substitute a fusion-availability predicate for the
    directional verdict. Proven behaviourally: with three ML layers available AND fusion
    available — the exact inputs the old fallback used — an unauthorized stack is still INVALID.
    The verdict is also now REQUIRED, so no caller can omit it and get the old substitution."""
    import inspect
    p = inspect.signature(gsc.classify_stack_health).parameters["unified_stack_team_ok"]
    assert p.default is inspect.Parameter.empty, "the verdict must be required, not defaulted"
    assert gsc.classify_stack_health(
        fusion_available=True, mc_available=True, n_ml_layers_available=3,
        unified_stack_team_ok=False) == "INVALID"
    assert gsc.classify_stack_health(
        fusion_available=True, mc_available=True, n_ml_layers_available=3,
        unified_stack_team_ok=True) == "FULL"


# ── CONTROL 7: ONE FAUCET — the verdict is transported, never recomputed ──────────────────────
def test_server_transports_the_verdict_and_does_not_recompute_it():
    src = _code_only((ROOT / "server.py").read_text(encoding="utf-8", errors="replace"))
    assert "unified_stack_team_can_authorize(" not in src, \
        "server must not hold a second authorization computation"
    assert "ms_dict.get('stack_directional_authorized')" in src, \
        "server must consume the transported verdict"
    assert "def classify_stack_health(*, fusion_available" not in src, \
        "the shadow stack-health copy must be gone"


def test_the_authorization_authority_requires_composition_from_every_caller():
    """Machine-forced ONE FAUCET: the kwarg has no default, so a caller cannot silently fall back
    to a weaker question."""
    import inspect
    sig = inspect.signature(gsc.unified_stack_team_can_authorize)
    p = sig.parameters["stack_probs_composition"]
    assert p.default is inspect.Parameter.empty, "composition must be required, not defaulted"


def test_display_mc_leg_consumes_the_governing_decision():
    """CONTROL 1/2 (display half): the 5m/15m leg must not derive its own priors."""
    import inspect

    import signals
    src = _code_only(inspect.getsource(signals._compute_display_wall_clock_mc_excursions))
    assert "mc_model_direction_inputs(" not in src, \
        "display leg must not re-derive directional priors"
    assert "ml_bundle.get('mc_conditioned')" in src, \
        "display leg must consume the governing MC conditioning decision"


def test_meta_is_credited_only_when_the_approved_composition_ran():
    """A complete-looking triplet must not credit a meta layer that never executed (zero
    meta_*_5c.pkl exist, yet the source string alone used to credit it)."""
    from ml_predict import stack_probs_bundle_key
    bundle = {
        stack_probs_bundle_key(): TRI,
        "mc_stack_probability_source": "stack_probs_meta_or_weighted",
        "stack_probs_composition": _composition(produced=("xgb",)),
    }
    scored = gsc.derive_stack_layers_scored(
        xgb_out=_layer(), lstm_out=_layer(available=False, up=None, dn=None, flat=None),
        transformer_out=_layer(available=False, up=None, dn=None, flat=None),
        mc_out=SimpleNamespace(available=False), ml_bundle=bundle,
        regime=SimpleNamespace(primary="unknown"), fusion_payload=None)
    assert "meta" not in scored


# ── PRODUCER <-> GATE binding (added after adversarial review) ────────────────────────────────
def test_producer_record_and_gate_agree_on_keys_and_semantics():
    """If the producer emitted a key the gate never reads — or named one differently — both sides
    would keep passing their own tests while production read `composition_unknown` forever. Bind
    them with the REAL record from the real producer, not a hand-built dict.

    Environment-independent by construction: whatever the local artifacts say, the gate's verdict
    for a COMPLETE triplet must equal the producer's own `complete`.
    """
    from ml_predict import stack_probs_composition_record

    rec = stack_probs_composition_record("SPY", "1c",
                                         {"xgb": TRI, "lstm": TRI, "transformer": TRI})
    for k in ("horizon", "required", "produced", "missing", "collapsed",
              "contract_compliant", "contract_issues", "complete"):
        assert k in rec, f"producer must emit {k!r} — the gate reads it"

    ok, _reason = gsc.unified_stack_team_can_authorize(
        xgb_out=_layer(), lstm_out=_layer(), transformer_out=_layer(),
        stack_probs=TRI, stack_probs_composition=rec)
    assert ok is bool(rec["complete"]), \
        "the gate's verdict must track the producer's record, not re-derive a weaker answer"


def test_composition_credits_only_the_legs_that_fed_the_triplet():
    """At 5c the runtime blend is xgb_plus_transformer, yet lstm_p is still COMPUTED upstream.
    Crediting LSTM there would authorize a triplet it never touched — shape over provenance, the
    exact error this record exists to end."""
    from ml_predict import stack_probs_composition_record

    rec = stack_probs_composition_record("SPY", "5c", {"xgb": TRI, "transformer": TRI})
    assert "lstm" in rec["missing"], "a leg that did not feed the blend is not a contributor"
    assert "lstm" not in rec["produced"]
    assert rec["complete"] is False


def test_ablation_scorer_builds_the_composition_it_gates_on():
    """The ablation leg read `ml_bundle.get("stack_probs_composition")` from a bundle literal that
    never set it, so its gate was hardwired to (False, 'composition_unknown') and every scored row
    ran base-neutral against an ML-conditioned production leg — the conditioning skew the call was
    added to remove."""
    src = _code_only((ROOT / "arch_competition" / "ablation_bundle_inference.py")
                     .read_text(encoding="utf-8", errors="replace"))
    assert "ml_bundle['stack_probs_composition'] = stack_probs_composition_record(" in src, \
        "the ablation leg must BUILD the record it authorizes on, not read an unset key"
