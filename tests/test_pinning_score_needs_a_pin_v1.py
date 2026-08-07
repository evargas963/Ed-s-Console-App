"""RC-295 — the pinning regime scored a point for a relationship with no mechanism.

`regime_engine.py` added 1.0 to the pinning score and appended "charm drifting
upward/downward toward pin" whenever `charm_direction` agreed geometrically with
`charm_drift_toward` relative to spot.

That value is not a pin. It is `pick_net_gex_peak_strike` over the SELECTED expiry,
borrowed from the analytics faucet (RC-292), and charm performs no computation with it —
it republishes the caller's label unchanged (RC-294). Pinning is a MAGNITUDE mechanism:
price is held where total hedging volume is greatest, which is `pick_pin_and_strength` over
the wide book. The signed-net peak answers a different question.

Cursor v3 graded this the consequential consumer, because the `call_engine` sentence I had
quoted to the operator turned out to be dead code while this one moves regime
classification.

REMOVED, NOT REPAIRED, and the distinction is the point: `SignalInput` carries
`charm_drift_toward`, `pin_width_pts` and the gamma-wall distances but NO gamma-pin field,
so the test was scoring against the only strike it happened to have. The right test needs
terrain's max-total-gamma strike plumbed through, and that field does not exist yet.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

SRC = (REPO / "regime_engine.py").read_text(encoding="utf-8", errors="replace")


def test_the_unsupported_pinning_point_is_gone():
    assert 'support.append("charm drifting upward toward pin")' not in SRC, (
        "the pinning score awards a point for charm agreeing with a strike that is not a pin")
    assert 'support.append("charm drifting downward toward pin")' not in SRC


def test_no_pinning_score_reads_charm_drift_toward():
    """The field must not re-enter the pinning branch under any comparison."""
    live = [ln.strip() for ln in SRC.splitlines()
            if "charm_drift_toward" in ln and not ln.strip().startswith("#")]
    assert not live, (
        f"charm_drift_toward is being consumed in regime_engine again: {live}. It is a "
        f"selected-expiry net-GEX peak with no pinning semantics (RC-292/RC-294).")


def test_the_removal_states_why_and_what_would_replace_it():
    """A deletion with no reason is indistinguishable from an accident."""
    import re

    # The rationale spans wrapped comment lines, so the `# ` markers have to come out
    # before the sentence exists as a sentence — stripping whitespace alone leaves them
    # embedded mid-phrase, which is what made the first version of this test fail.
    flat = re.sub(r"\s+", " ", re.sub(r"^\s*#\s?", "", SRC, flags=re.M))
    assert "RC-295: REMOVED" in SRC
    assert "no gamma-pin field" in flat, "the blocker is not recorded at the site"
    assert "pick_pin_and_strength" in SRC, "the correct metric is not named for the next author"
    assert "does not exist yet" in flat, "the NEXT-DEPTH condition is not stated at the site"


def test_the_other_pinning_evidence_survived():
    """Removing one unsound signal must not quietly gut the regime."""
    for kept in ("tight pin width", "micro regime = ", "positive gamma — dealers dampening"):
        assert kept in SRC, f"unrelated pinning evidence was lost with the removal: {kept}"


def test_signal_input_still_has_no_gamma_pin_field():
    """The premise of the removal. If this changes, the real test becomes buildable.

    Deliberately asserted so the day someone plumbs the pin through, THIS test fails and
    sends them to RC-295 rather than leaving the honest-but-weaker score in place forever.
    """
    import inspect

    from signal_types import SignalInput

    fields = set(getattr(SignalInput, "__annotations__", {}))
    pin_fields = {f for f in fields if "gamma_pin" in f or f in ("absolute_gamma_strike",)}
    assert not pin_fields, (
        f"SignalInput now carries {sorted(pin_fields)} — the pinning point can and should be "
        f"rebuilt on the ACTUAL pinning magnet. See RC-295 NEXT-DEPTH.")
    assert "charm_drift_toward" in fields, (
        "premise changed: the field the old test used is gone, so re-derive RC-295")
    assert inspect.isclass(SignalInput)
