"""RC-321 — negative control for the `five_why_reaches_bedrock` enforced check.

THE DEFECT IT GUARDS. Operator law 2026-08-09: "we do 5 whys to bedrock." RC-315's chain was
five levels deep, ended `ROOT: TERMINAL` with a real justification, and passed
`five_why_recursive_lock` — while its level (4) blamed the operator's instruction. Shape was
enforced; ownership of the cause was not. An explanation and a defect both answer "why", and
only one of them names something this repository can repair.

THE CONTROL IS BUILT FROM THE REAL DEFECT. RC-317 records what happens when a control is
written from the author's memory of a failure instead of the failure itself: RC-298's control
tested a reconstructed fixture and its gate never caught the file it was named for. So the
first case here recovers RC-315's actual prior wording with `git show e1bc6793:...` and
requires the rule to fire on it, and the second requires it to stay silent on the corrected
row that quotes the same blame-shift in order to reject it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import check_five_why_reaches_bedrock as C  # noqa: E402

#: The commit carrying RC-315's first wording, before Cursor's audit rejected it.
BLAME_SHIFT_SHA = "e1bc6793"


def _row(why: str, opened: str = "2026-08-10") -> str:
    return f"| RC-999 | OPEN | {opened} | {opened} | defect | {why} | FIXED: something. |"


def _hits(why: str, tmp_path: Path, opened: str = "2026-08-10") -> list:
    p = tmp_path / "root_cause_log.md"
    p.write_text("| id | status | opened | due | defect | why | fix |\n"
                 "|---|---|---|---|---|---|---|\n" + _row(why, opened) + "\n",
                 encoding="utf-8")
    return C.violations(p)


def _rc315_why(sha: str) -> str:
    blob = subprocess.run(["git", "show", f"{sha}:governance/root_cause_log.md"],
                          cwd=REPO, capture_output=True, encoding="utf-8", errors="replace")
    if blob.returncode != 0:
        pytest.fail(f"cannot recover {sha}: {(blob.stderr or '')[:200]}")
    for line in (blob.stdout or "").splitlines():
        if line.startswith("| RC-315 "):
            return [c.strip() for c in line.strip("|").split("|")][5]
    pytest.fail(f"RC-315 is not present at {sha} — this control has lost its subject")


def test_it_fires_on_the_actual_chain_that_was_rejected():
    """The real stop-short, recovered from git — not a reconstruction of it (RC-317)."""
    why = _rc315_why(BLAME_SHIFT_SHA)
    assert C._BLAME_RE.search(why), (
        "the detector does not recognise RC-315's original level (4) as handing causation "
        "to another actor, so it would not have caught the chain that prompted this rule")
    assert not C._REJECTION_RE.search(why), (
        "the original wording appears to reject its own blame-shift; if so this control is "
        "comparing against the corrected text and is testing nothing")


def test_it_stays_silent_on_the_corrected_row_that_rejects_the_blame_shift(tmp_path):
    """A corrected row MUST be able to quote the blame-shift in order to disown it.

    The first version of this control asserted that RC-315's live `why` cell matches
    `_BLAME_RE` and `_REJECTION_RE` — the checker's two internal patterns, restated. That
    is a rendering of the rule, not the rule: recombining those patterns so that a quoted
    blame-shift fires anyway would have left both assertions true and the row flagged. The
    silence is a VERDICT, so the verdict is what is taken here — the live cell is run
    through `violations()` under a post-cutover date, where grandfathering cannot mask it.
    """
    live = (REPO / "governance" / "root_cause_log.md").read_text(encoding="utf-8")
    why = next(([c.strip() for c in ln.strip("|").split("|")][5]
                for ln in live.splitlines() if ln.startswith("| RC-315 ")), None)
    assert why, "RC-315 is gone from the live log"
    # Precondition: the cell must still QUOTE a blame-shift, or the silence proves nothing.
    assert C._BLAME_RE.search(why), "the corrected row no longer quotes what it rejects"
    assert _hits(why, tmp_path) == [], (
        "the checker flags RC-315's corrected wording — a row can no longer quote a "
        "blame-shift in order to disown it, which forces rows to hide what they reject")


def test_an_actor_blaming_chain_is_flagged(tmp_path):
    """The injected violation. If this passes silently the gate is inert."""
    why = ("(1) x -> (2) y -> (3) z -> (4) because the operator's instruction removed the "
           "review step -> (5) ROOT: TERMINAL — nothing else could have caught it.")
    assert _hits(why, tmp_path), "a chain terminating on an actor's instruction survived"


def test_an_owned_chain_is_accepted(tmp_path):
    why = ("(1) x -> (2) y -> (3) z -> (4) because I treated the removal of a reviewer as "
           "the removal of a requirement -> (5) ROOT: TERMINAL — the requirement was mine "
           "to keep and no mechanism required it.")
    assert _hits(why, tmp_path) == []


def test_symptom_root_missing_validation_is_rejected(tmp_path):
    """RC-432: ROOT: TERMINAL on 'missing validation' is a stop-short, not bedrock."""
    why = ("(1) x -> (2) y -> (3) z -> (4) no one checked -> "
           "(5) ROOT: TERMINAL — missing validation allowed the bad write.")
    assert _hits(why, tmp_path), "a chain ending on missing validation survived"


def test_symptom_root_human_error_is_rejected(tmp_path):
    why = ("(1) x -> (2) y -> (3) z -> (4) the author mistyped -> "
           "(5) ROOT: TERMINAL — human error.")
    assert _hits(why, tmp_path), "a chain ending on human error survived"


def test_legitimate_authority_boundary_root_is_accepted(tmp_path):
    why = ("(1) density labeled clear -> (2) walls never entered the dict -> "
           "(3) locals()._cgw assigned after density -> (4) selected-expiry flip mixed "
           "with terrain pin -> (5) ROOT: TERMINAL — density must consume the same "
           "terrain-bound walls and flip authority as the KL table.")
    assert _hits(why, tmp_path) == []


def test_describing_an_incentive_is_not_blaming_a_person(tmp_path):
    """The narrowing that made this affordable, locked so it cannot widen back.

    A first pattern matched bare "time pressure" and flagged RC-290 — whose root correctly
    names my own defect and which uses pressure to describe the mechanism by which a cheap
    wrong option beats an expensive right one. The rule was narrowed rather than the row
    exempted.
    """
    why = ("(1) x -> (2) y -> (3) z -> (4) because writing a reason is free and checking it "
           "requires tracing every consumer, so under time pressure the cheap one wins -> "
           "(5) ROOT: TERMINAL — I built an escape hatch that depends on my own diligence.")
    assert _hits(why, tmp_path) == []


def test_rows_predating_the_cutover_are_grandfathered(tmp_path):
    why = ("(1) x -> (2) y -> (3) z -> (4) because the operator asked for it -> "
           "(5) ROOT: TERMINAL — nothing more.")
    assert _hits(why, tmp_path, opened="2026-07-01") == []
    assert _hits(why, tmp_path, opened="2026-08-10"), "the cutover date is not binding"


def test_the_live_repository_passes_on_merit():
    assert C.violations() == [], f"chains stopping at an explanation: {C.violations()}"


def test_the_gate_is_registered_as_enforced():
    src = (REPO / "tools" / "check_institutional_correctness.py").read_text(
        encoding="utf-8", errors="replace")
    assert ('("five_why_reaches_bedrock", check_five_why_reaches_bedrock, True)') in src, (
        "the check is not registered ENFORCED in the institutional gate")
