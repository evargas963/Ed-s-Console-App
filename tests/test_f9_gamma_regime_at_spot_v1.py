"""Cursor-audit F9: the operator-facing dealer dampen/amplify REGIME must be the SIGN of dealer
gamma AT SPOT (gamma_at_price(profile, spot)), the authority per math_levels.gamma_at_price / the
terrain card — NOT the whole-chain aggregate_net_gex (Σ over ALL strikes), which can differ in sign.

Before this fix, call_engine._greek_notes read inp.net_gamma (whole-chain), so the Call could print
"Dealers are absorbing moves — chop" while the terrain commentary said "Short gamma — amplifying"
off the at-spot value, on the same screen. The Call now reads net_gamma_at_spot, so the two agree.
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
