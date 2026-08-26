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

REMOVED, NOT REPAIRED, and the distinction is the point: at removal time `SignalInput`
carried `charm_drift_toward`, `pin_width_pts` and the gamma-wall distances but NO gamma-pin
field, so the test was scoring against the only strike it happened to have.

RC-292 RENAME BATCH UPDATE: the NEXT-DEPTH plumb has landed — `SignalInput.absolute_gamma_strike`
now carries terrain's max-total-gamma strike (full book, SSOT, fail-closed None on a stale
cache). The scoring point stays removed even so: RC-315 established that absolute gamma is
a pin CANDIDATE, not a magnet, so "charm flow toward it" remains an unvalidated directional
mechanism. The tripwire below flips accordingly: it now fires if regime_engine CONSUMES the
new field, sending the author to open the validated-mechanism RC row instead of quietly
re-adding the geometric point.
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
    assert "pick_pin_and_strength" in SRC, "the correct metric is not named for the next author"
    # The plumb landed (RC-292 batch): the site must now record that the INPUT exists and
    # that the point stays out pending a validated directional mechanism (RC-315).
    assert "absolute_gamma_strike" in SRC, "the plumbed field is not named at the site"
    assert "unvalidated directional claim" in flat, (
        "the reason the point stays removed after the plumb is not stated at the site")
    assert "owed as its own RC row" in flat, "the rebuild condition is not stated at the site"


def test_the_other_pinning_evidence_survived():
    """Removing one unsound signal must not quietly gut the regime."""
    # Cursor-audit F9: the dampening evidence now reads the AT-SPOT dealer gamma (the regime
    # authority) — "positive gamma at spot — dealers dampening" — not the whole-chain aggregate.
    for kept in ("tight pin width", "micro regime = ", "positive gamma at spot — dealers dampening"):
        assert kept in SRC, f"unrelated pinning evidence was lost with the removal: {kept}"


def test_signal_input_carries_the_plumbed_strike_and_regime_engine_does_not_consume_it():
    """The RC-295 NEXT-DEPTH plumb, locked — and the NEW tripwire.

    The old tripwire asserted SignalInput had NO gamma-pin field, so the day the plumb
    landed it would fire and send the author here. It fired (RC-292 rename batch). The
    honest post-plumb state it demanded: `absolute_gamma_strike` exists on SignalInput,
    defaults to None (fail-closed), and the pinning branch still consumes NEITHER it NOR
    charm_drift_toward — because RC-315 withdrew "toward the absolute-gamma strike" as a
    directional mechanism (candidate, not magnet). Rebuilding the point requires its own
    RC row with a validated mechanism; the day someone wires the field into regime_engine,
    THIS test fails and sends them there instead of letting the +1 return silently.
    """
    import inspect

    from signal_types import SignalInput

    fields = set(getattr(SignalInput, "__annotations__", {}))
    assert "absolute_gamma_strike" in fields, (
        "the RC-295 NEXT-DEPTH plumb regressed: SignalInput lost absolute_gamma_strike")
    assert SignalInput.__dataclass_fields__["absolute_gamma_strike"].default is None, (
        "absolute_gamma_strike must default to None — fail-closed, never a fabricated strike")
    assert "charm_drift_toward" in fields, (
        "premise changed: the field the old test used is gone, so re-derive RC-295")
    assert inspect.isclass(SignalInput)
    # The new tripwire: the plumbed field must NOT be consumed by regime scoring until the
    # validated-mechanism RC row exists (see RC-295 NEXT-DEPTH / RC-315).
    live = [ln.strip() for ln in SRC.splitlines()
            if "absolute_gamma_strike" in ln and not ln.strip().startswith("#")]
    assert not live, (
        f"regime_engine now consumes absolute_gamma_strike: {live}. That rebuild is owed "
        f"as its own RC row with an independently validated directional mechanism "
        f"(RC-295 NEXT-DEPTH, RC-315) — it must not return as a silent +1.")
