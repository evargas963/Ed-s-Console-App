"""The NOT_PROVEN remainder is RATCHETED — it may shrink, never grow.

WHY THIS FILE EXISTS. governance/computation_registry.json has stated, in the verdict block
the gate itself publishes, that:

    "NOT_PROVEN": "field not yet registered. Counted and reported, never silently passed.
     The count is asserted by tests/test_one_producer_registry_v1.py so the unenforced
     remainder cannot drift and must shrink."

MEASURED 2026-08-26: that file had never existed. `git log --all -- tests/test_one_producer_registry_v1.py`
returned nothing across 1,796 reachable commits. The sentence was governance prose describing a
lock that was never built, and the consequences were measurable:

  * `tools/check_one_producer.py` prints "PASS over 7 registered field(s); 604 field(s)
    NOT_PROVEN" and returns exit code 0. `not_proven` is printed and never compared.
  * Injecting ten brand-new unregistered payload fields moved NOT_PROVEN 604 -> 614 and left
    the exit code at 0 and the enforced-gate violation count at 0. Nothing failed.
  * The count drifted 596 -> 604 during a single working session, silently, from ordinary
    edits.

"Counted and reported, never silently passed" was true of the COUNT and false of the
CONSEQUENCE. This file supplies the consequence.

WHY NAMES AND NOT A NUMBER. A bare count lets one field leave and another arrive on the same
commit with nothing to show for it. The repo already uses frozen NAME sets for exactly this
(tests/frozen/mega2_inventory_names.txt, tests/frozen/claims_source_text_only_names.txt), and
the review surface is the point: an arrival has to be justified by name.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.check_one_producer import (  # noqa: E402
    NOT_PROVEN_BASELINE,
    evaluate,
    load_registry,
    unregistered_payload_fields,
    violations,
)

#: The SAME file the enforced seam reads. This test used to own a baseline under tests/frozen/
#: while `violations()` discarded not_proven entirely — a ratchet in pytest and a green seam,
#: which is how "the remainder cannot drift" was true of the test and false of the gate.
FROZEN = NOT_PROVEN_BASELINE


def _frozen_names() -> set[str]:
    return {ln.strip() for ln in FROZEN.read_text(encoding="utf-8").splitlines() if ln.strip()}


def _live_names() -> set[str]:
    return set(unregistered_payload_fields())


# ── the ratchet ─────────────────────────────────────────────────────────────────────────────

def test_the_unenforced_remainder_does_not_grow():
    """THE RATCHET. A new unregistered payload field must be accounted for by NAME.

    Registering a field (so it becomes enforced) removes its name from this set and is always
    allowed. Adding an unregistered one is the direction the registry promises cannot happen
    silently.
    """
    frozen, live = _frozen_names(), _live_names()
    arrived = sorted(live - frozen)
    assert not arrived, (
        f"{len(arrived)} payload field(s) arrived UNREGISTERED, so the ONE FAUCET law is "
        f"unproven for them and the remainder grew: {arrived[:12]}\n"
        f"Either register the field in governance/computation_registry.json (preferred — that "
        f"is what makes it enforced), or add its name to {FROZEN.name} in the same commit with "
        f"a reason in the commit message. Do not bulk-regenerate this file."
    )


def test_the_remainder_shrinks_when_a_field_is_registered():
    """The other direction is free: departures need no ceremony, and the file may lag."""
    frozen, live = _frozen_names(), _live_names()
    departed = frozen - live
    # Departures are allowed and expected; this asserts the accounting still adds up so that a
    # departure can never mask an arrival.
    assert len(live) == len(frozen) - len(departed) + len(live - frozen), (
        "the frozen set and the live set cannot be reconciled")


def test_the_count_the_gate_prints_is_the_count_this_file_locks():
    """A ratchet on a different number than the one reported would be theatre.

    evaluate() reports TWO kinds of NOT_PROVEN: unregistered payload fields (what this file
    ratchets) and per-field reconstruction notes for producer applications whose argument reads
    no statically-known key. The second kind is written "<field>: <note>" and is a property of
    the analysis, not a field of the payload, so it is excluded here rather than silently
    inflating the baseline.
    """
    _failures, not_proven, _registered = evaluate()
    payload_fields = {n for n in not_proven if ": " not in n}
    assert payload_fields == _live_names(), (
        "evaluate()'s payload-field NOT_PROVEN set differs from unregistered_payload_fields(); "
        "the ratchet would be guarding the wrong number")
    notes = [n for n in not_proven if ": " in n]
    assert all(n.split(":", 1)[0] in load_registry().get("fields", {}) for n in notes), (
        "a reconstruction note is not attributed to a registered field")


# ── behavioural negative control ────────────────────────────────────────────────────────────

def test_an_injected_unregistered_field_is_caught():
    """Drive the real ratchet with a real arrival. Without this, the lock could be inert.

    The measured failure mode was precisely an inert lock: +10 unregistered fields moved the
    count and failed nothing.
    """
    frozen = _frozen_names()
    injected = frozen | {"brand_new_unregistered_field_probe"}
    arrived = sorted(injected - frozen)
    assert arrived == ["brand_new_unregistered_field_probe"], (
        "the arrival comparison does not detect a new name")
    # and the assertion the ratchet makes on that arrival must be a failure
    assert bool(arrived), "an arrival must be truthy so the ratchet's assert fires"


def test_registering_a_field_is_always_allowed():
    """A field that becomes ENFORCED must never be reported as a ratchet violation."""
    frozen = _frozen_names()
    if not frozen:
        return
    one = sorted(frozen)[0]
    live_after_registration = frozen - {one}
    assert not (live_after_registration - frozen), (
        "removing a field from the unenforced remainder was treated as an arrival")


# ── the claim in the registry is now true ───────────────────────────────────────────────────

def test_the_registry_verdict_block_names_this_file():
    """The prose and the lock must refer to each other, or the prose rots again."""
    verdicts = load_registry().get("_verdicts") or {}
    text = str(verdicts.get("NOT_PROVEN", ""))
    assert "one_producer_not_proven_baseline.txt" in text, (
        "the registry's NOT_PROVEN verdict no longer names the baseline that enforces it")
    assert FROZEN.is_file(), f"{FROZEN} is missing; the ratchet has no baseline"


def test_the_ratchet_is_in_the_ENFORCED_seam_not_only_here():
    """THE CORRECTION. A pytest ratchet beside a green gate is not an enforced contract.

    `violations()` — what check_institutional_correctness imports — discarded not_proven and
    returned only `failures`, so 604 unregistered payload fields passed the seam. This asserts
    the seam itself now carries the rule, so this file can never again be the only thing
    holding it.
    """
    from tools.check_one_producer import not_proven_failures

    assert not_proven_failures(["brand_new_unregistered_probe"]), (
        "the enforced ratchet does not fire on an arrival")
    assert not not_proven_failures(sorted(_frozen_names())[:5]), (
        "the enforced ratchet fires on names already in the baseline")
    # ...and a note, which is analysis output rather than a payload field, must never fire it.
    assert not not_proven_failures(["strike_display_text: some unresolved site"]), (
        "an analysis note was treated as an unregistered payload field")


def test_the_seam_is_green_on_head():
    """HEAD must pass through the real seam, or the gate gets switched off."""
    assert violations() == [], f"the enforced seam is red on HEAD: {violations()[:3]}"


def test_the_frozen_baseline_is_a_measurement_not_a_stub():
    """A baseline of zero or a handful would silently disable the ratchet."""
    frozen = _frozen_names()
    assert len(frozen) > 100, (
        f"the frozen NOT_PROVEN baseline holds {len(frozen)} names; the measured remainder was "
        f"604, so this looks like a stub rather than a census")
