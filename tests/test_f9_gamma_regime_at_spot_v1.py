"""Cursor-audit F9: the operator-facing dealer dampen/amplify REGIME must be the SIGN of dealer
gamma AT SPOT (gamma_at_price(profile, spot)), the authority per math_levels.gamma_at_price / the
terrain card — NOT the whole-chain aggregate_net_gex (Σ over ALL strikes), which can differ in sign.

NARRATIVE CORRECTION (gamma audit, AST-verified): an earlier version of this docstring claimed the
Call was printing a contradictory regime note to the operator "on the same screen". That was
OVERSTATED — `_greek_notes` has NO non-test caller, so it is dormant on the live path. The LIVE
instance of this defect class was regime_engine's pinning/acceleration scoring, which reads
SignalInput and is reached via classify_regime from signals.py; it scored the dampen/amplify regime
off whole-chain gamma. Both surfaces are fixed here; only the regime_engine one was live.

The value itself is sourced from the TERRAIN SSOT (the wide multi-expiry book the terrain card
renders as net_gex_at_spot), not the selected-expiry analytics slice — otherwise the two surfaces
could still disagree in sign. The sign THRESHOLD comes from the one authority
terrain_read.regime_from_signed_gamma, which withholds at exactly 0.
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from call_engine import _greek_notes
from signal_types import SignalInput


def _mk(**over) -> SignalInput:
    base = {f.name: None for f in dataclasses.fields(SignalInput)}
    base.update(ticker="SPY", timeframe="1m")
    base.update(over)
    return SignalInput(**base)


def _has(notes, sub):
    return any(sub in n for n in notes)


def test_dealer_regime_note_follows_at_spot_when_signs_disagree_f9():
    """Whole-chain positive (dampen) but at-spot negative (amplify): the note must follow AT-SPOT."""
    notes = _greek_notes(_mk(net_gamma=5.0e9, net_gamma_at_spot=-2.0e9))
    assert _has(notes, "amplifying moves"), f"note must follow at-spot (amplify): {notes}"
    assert not _has(notes, "absorbing moves"), f"note must NOT follow whole-chain (absorb): {notes}"

    # converse: whole-chain negative but at-spot positive -> absorb
    notes2 = _greek_notes(_mk(net_gamma=-5.0e9, net_gamma_at_spot=2.0e9))
    assert _has(notes2, "absorbing moves"), f"note must follow at-spot (absorb): {notes2}"
    assert not _has(notes2, "amplifying moves"), notes2


def test_dealer_regime_note_fails_closed_without_at_spot_f9():
    """No at-spot value -> NO dealer-regime note (never falls back to the whole-chain sign, which is
    the wrong basis; the terrain regime also stands aside when the at-spot gamma is unavailable)."""
    notes = _greek_notes(_mk(net_gamma=5.0e9, net_gamma_at_spot=None))
    assert not _has(notes, "absorbing moves") and not _has(notes, "amplifying moves"), notes


def test_exactly_zero_at_spot_gamma_is_withheld_everywhere_f1():
    """Gamma-audit F-1: the sign THRESHOLD is terrain_read.regime_from_signed_gamma, the one
    authority, which returns None at EXACTLY 0. An inline `> 0 else amplifying` would have called a
    0.0 "amplifying" in the Call while regime_engine withheld — two thresholds for one truth. Both
    consumers now route through the authority, so 0.0 is withheld on every surface."""
    from terrain_read import regime_from_signed_gamma

    assert regime_from_signed_gamma(0.0) is None
    notes = _greek_notes(_mk(net_gamma=5.0e9, net_gamma_at_spot=0.0))
    assert not _has(notes, "absorbing moves") and not _has(notes, "amplifying moves"), (
        f"exactly-zero at-spot gamma must withhold the regime claim, got: {notes}")


def test_regime_notes_disclose_the_modeled_dealer_sign_f9():
    """Operator requirement: modeled dealer inventory must not be presented as observed fact. The
    dealer sign is inferred from the +call/-put convention over public OI, which cannot establish
    actual ownership — so the note says 'Modeled dealer gamma', not 'Dealers are'."""
    for at_spot in (2.0e9, -2.0e9):
        notes = _greek_notes(_mk(net_gamma=1.0, net_gamma_at_spot=at_spot))
        regime = [n for n in notes if "chop/fade" in n or "trend/momentum" in n]
        assert regime, f"expected a regime note for at_spot={at_spot}"
        assert all(n.startswith("Modeled dealer gamma") for n in regime), (
            f"regime note must disclose the modeled basis, got: {regime}")
