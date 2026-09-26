"""call_engine chunk-1: I-01 contract when canonical/fusion/mh_policy are absent."""

from __future__ import annotations

from types import SimpleNamespace





    # TEST_SYSTEM_REHAB_V2: was `call.signal not in ("long","short") or not
    # call.validation_passed` -- line 147 above already asserts `call.signal ==
    # "wait"`, which makes `signal not in ("long","short")` unconditionally true, so
    # this could never fail regardless of `validation_passed`. Line 147 already
    # covers "not in (long, short)"; dropped as dead weight rather than kept as a
    # tautology.








def _phase3_vol_regime():
    return SimpleNamespace(
        vol_regime="normal",
        trade_permissive=True,
        conviction_multiplier=1.0,
        risk_multiplier=1.0,
        breakout_bias=0.6,
        reversal_bias=0.5,
    )








def test_the_charm_note_does_not_credit_time_decay_with_a_price_target():
    """RC-313: the Call card sentence, EXECUTED.

    It read "Time decay pushing dealers to {dir} toward {strike}". Charm measured the
    direction; it did NOT measure the strike. `charm_drift_toward` is
    pick_net_gex_peak_strike over the SELECTED expiry, republished unchanged (RC-292/RC-302),
    and RC-295 already deleted the identical claim from the pinning score while leaving this
    sentence — which makes the same assertion to a reader who has no score to check it
    against. Both measured quantities must still reach the operator; only the causal claim
    between them goes.
    """
    from call_engine import _greek_notes

    inp = SimpleNamespace(net_gamma=None, charm_direction="selling",
                          charm_drift_toward=772.5, iv_direction=None, vix_level=None)
    notes = [n for n in _greek_notes(inp) if "772.5" in n or "decay" in n.lower()]
    assert len(notes) == 1, f"expected exactly one charm note, got {notes}"
    note = notes[0]

    assert "772.50" in note, "the strike stopped reaching the operator"
    assert "selling" in note, "charm's own measured direction stopped reaching the operator"
    assert "toward" not in note.lower(), (
        f"the note still points time decay at a price target it did not measure: {note!r}")
    assert "pushing dealers to" not in note, f"the RC-313 wording is back: {note!r}"
    assert "net-gex peak" in note.lower(), (
        f"the note does not say WHICH quantity the strike is: {note!r}")
    assert "expiry" in note.lower(), (
        f"the note does not say the strike is selected-expiry scoped: {note!r}")

    # Absence stays absent: no direction or no strike means no sentence at all.
    for missing in ({"charm_direction": None}, {"charm_drift_toward": None}):
        fields = {"net_gamma": None, "charm_direction": "selling",
                  "charm_drift_toward": 772.5, "iv_direction": None, "vix_level": None}
        fields.update(missing)
        partial = SimpleNamespace(**fields)
        assert not [n for n in _greek_notes(partial) if "772.5" in n or "decay" in n.lower()], (
            f"a charm note was emitted with {missing} — half a claim is still a claim")


def test_call_stack_uses_all_consolidated_not_fusion_multi_horizon_slots():
    """Phase 3 mechanical: stack vote keys are 8-wide with single all_consolidated ML slot."""
    import inspect

    import call_engine as ce

    assert ce.CONFLUENCE_TOTAL_SOURCES == 5   # no index-ETF votes (operator 2026-09-23)
    src = inspect.getsource(ce.compute_call)
    assert '"all_consolidated":' in src
    idx = src.index("stack_votes = {")
    block = src[idx : idx + 700]
    assert '"fusion"' not in block
    assert '"multi_horizon"' not in block
