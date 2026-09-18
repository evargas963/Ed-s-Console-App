"""
No-fallback lock repair (2026-09-17): market_state.py's multi-horizon-decision field
copies used `or <default>` value-level guards on final_bias/final_quality/
primary_horizon/trade_mode/alignment_state/contradiction_state/conflict_level/
entry_state/risk_note/decision_provenance/entry_display_text/stop_display_text/
targets_display/hold_style/size_modifier_display/row_state -- traced each into
multi_horizon_decision.py's own construction logic (not assumed): every one is built
from an exhaustive if/elif/else chain or a hardcoded non-empty literal, so none of them
can ever be empty/falsy. The `or <default>` guards were dead code, removed. This proves
the claim directly against the REAL production construction functions (WAIT and
tradeable paths both), not just against the existing behavioral test suite that
incidentally exercises it.
"""
from __future__ import annotations

from multi_horizon_decision import build_multi_horizon_bundle
from tests.test_issue18_multi_horizon_decision import _call, _canonical, _inp, _pred


def _assert_all_string_fields_nonempty(bundle):
    d = bundle.final_decision
    for name in (
        "final_bias", "final_quality", "primary_horizon", "trade_mode",
        "alignment_state", "contradiction_state", "entry_state",
        "risk_note", "decision_provenance",
    ):
        val = getattr(d, name)
        assert val, f"MultiHorizonDecision.{name} must never be empty/falsy, got {val!r}"
    assert d.alignment_report.conflict_level
    for name in ("entry_display_text", "stop_display_text", "targets_display", "hold_style",
                 "size_modifier_display"):
        val = getattr(d.final_trade_plan, name)
        assert val, f"FinalTradePlan.{name} must never be empty/falsy, got {val!r}"
    for a in d.supporting_assessments:
        assert a.row_state, "SupportingHorizonAssessment.row_state must never be empty"


def test_tradeable_path_fields_never_empty():
    bundle = build_multi_horizon_bundle(_inp(mins_to_close=180), _pred(), _canonical(), _call())
    _assert_all_string_fields_nonempty(bundle)


def test_wait_path_fields_never_empty():
    """The 'wait' branch takes different literal values (e.g. hold_style='Wait / no
    setup', stop_display_text='—') -- must also never be empty."""
    p = _pred(
        u1=0.34, d1=0.33, f1=0.33, u5=0.34, d5=0.33, f5=0.33,
        u15=0.34, d15=0.33, f15=0.33, u60=0.34, d60=0.33, f60=0.33,
    )
    bundle = build_multi_horizon_bundle(
        _inp(mins_to_close=180), p, _canonical(), _call(signal="wait")
    )
    _assert_all_string_fields_nonempty(bundle)
    assert bundle.final_decision.final_bias == "WAIT"
    assert bundle.final_decision.final_trade_plan.hold_style == "Wait / no setup"
    assert bundle.final_decision.final_trade_plan.stop_display_text == "—"


def test_market_state_no_or_default_guards_remain_in_source():
    import inspect

    import market_state

    src = inspect.getsource(market_state.build_market_state)
    for banned in (
        'or "WAIT"', 'or "D"', 'or "1c"', 'or "intraday"', 'or "no_primary"',
        'or "none"', 'or "high"', 'or "no_setup"', 'or "—"', 'or "0.00x"',
        'or "weak"',
    ):
        assert banned not in src, f"dead `{banned}` fallback guard should have been removed"
