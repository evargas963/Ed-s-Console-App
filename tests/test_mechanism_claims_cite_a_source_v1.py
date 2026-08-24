"""RC-319 — negative control for the `rc_mechanism_claims_cite_a_source` enforced check.

THE DEFECT IT GUARDS. I wrote "Hedging MAGNITUDE pins price regardless of net sign" into
governance/mega2_traceable_inventory.py and built RC-313's decision on it. Magnitude sets
the SIZE of the re-hedging flow at a strike; the SIGN of the dealer position sets whether
that flow stabilises or repels, and the sign is not even observable from public open
interest. An independent audit overturned it the next day. Depth was enforced — the chain
was five deep with a clean terminal root — and checkability was not.

THE CONTROL IS BUILT FROM THE REAL DEFECT. RC-317 records what happens when a negative
control is written from the author's memory of a failure instead of the failure: RC-298's
control tested a reconstructed fixture and its gate never caught the file it was named for.
So the first case here recovers the actual sentence with `git show 6f95a237:<path>` and
requires the rule to fire on it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import check_rc_mechanism_claims_cite_a_source as C  # noqa: E402

#: The commit that carried the false sentence, before RC-315 replaced it.
FALSE_CLAIM_SHA = "6f95a237"


def _row(opened: str, why: str, fix: str = "FIXED: something.") -> str:
    return f"| RC-999 | OPEN | {opened} | {opened} | defect text | {why} | {fix} |"


def _hits(text: str, tmp_path: Path) -> list:
    p = tmp_path / "root_cause_log.md"
    p.write_text("| id | status | opened | due | defect | why | fix |\n"
                 "|---|---|---|---|---|---|---|\n" + text + "\n", encoding="utf-8")
    return C.violations(p)


def test_it_fires_on_the_actual_sentence_that_was_refuted():
    """The real defect, recovered from git — not a reconstruction of it (RC-317)."""
    blob = subprocess.run(
        ["git", "show", f"{FALSE_CLAIM_SHA}:governance/mega2_traceable_inventory.py"],
        cwd=REPO, capture_output=True, text=True)
    if blob.returncode != 0:
        pytest.fail(f"cannot recover {FALSE_CLAIM_SHA}: {blob.stderr.strip()[:200]}")
    line = [ln for ln in blob.stdout.splitlines() if "MAGNITUDE pins" in ln]
    assert line, (
        f"the false sentence is not in {FALSE_CLAIM_SHA} — this control has lost its "
        "subject and is testing nothing")
    claim = line[0]
    assert C._MECHANISM_RE.search(claim), (
        "the detector does not recognise 'hedging MAGNITUDE pins price' as a market "
        "mechanism claim, so it would not have caught RC-315")
    assert not C._CITATION_RE.search(claim), (
        "the historical line appears to cite a source; if so this control is comparing "
        "against the wrong text")


def test_an_uncited_mechanism_claim_in_a_new_row_is_flagged(tmp_path):
    """The injected violation. If this passes silently the gate is inert."""
    why = ("(1) x -> (2) y -> (3) z -> (4) w -> (5) ROOT: TERMINAL — dealer hedging "
           "stabilises price around the strike, so the level holds.")
    assert _hits(_row("2026-08-10", why), tmp_path), "an uncited mechanism claim survived"


def test_the_same_claim_with_a_doi_is_accepted(tmp_path):
    why = ("(1) x -> (2) y -> (3) z -> (4) w -> (5) ROOT: TERMINAL — dealer hedging "
           "stabilises price around the strike (doi:10.1016/j.jfineco.2004.08.005).")
    assert _hits(_row("2026-08-10", why), tmp_path) == []


def test_a_reproducible_command_also_satisfies_it(tmp_path):
    why = ("(1) x -> (2) y -> (3) z -> (4) w -> (5) ROOT: TERMINAL — the flow destabilises "
           "the book, measured by `python tools/repo_scoreboard.py`.")
    assert _hits(_row("2026-08-10", why), tmp_path) == []


def test_naming_a_field_is_not_a_causal_claim(tmp_path):
    """The narrowing that made this affordable, locked so it cannot widen back.

    A first pass matched bare `pins?|magnet|hedging flow` and produced six register hits of
    which five were the NOUN — "Pin strength vs neighbors", "the gamma pin row". Matching
    the noun teaches rewording, not citing.
    """
    why = ("(1) x -> (2) y -> (3) z -> (4) w -> (5) ROOT: TERMINAL — the gamma pin row and "
           "the pin strength field are two names for one metric.")
    assert _hits(_row("2026-08-10", why), tmp_path) == []


def test_rows_predating_the_cutover_are_grandfathered(tmp_path):
    """A lock binds new work; rewriting history is not enforcement (the numeric rule's own
    design, reused deliberately)."""
    why = ("(1) x -> (2) y -> (3) z -> (4) w -> (5) ROOT: TERMINAL — dealer hedging "
           "stabilises price around the strike.")
    assert _hits(_row("2026-07-01", why), tmp_path) == []
    assert _hits(_row("2026-08-10", why), tmp_path), "the cutover date is not binding"


def test_the_live_repository_passes_on_merit():
    """Zero because the one real hit was REPAIRED by citing, not exempted."""
    assert C.violations() == [], f"uncited mechanism claims present: {C.violations()}"


def test_the_registers_are_in_scope():
    """RC-315's claim lived in a derivation justification, not in the log."""
    assert C.register_violations() == []
    assert "_REGISTER_GLOB" in Path(C.__file__).read_text(encoding="utf-8")


def test_the_gate_is_registered_as_enforced():
    """Consolidated 2026-08-24 (governance/retired_checks.md): the mechanism-claims
    validation now runs INSIDE root_cause_log, so the survivor must be registered
    ENFORCED and its fold table must still run this validator's helper."""
    src = (REPO / "tools" / "check_institutional_correctness.py").read_text(
        encoding="utf-8", errors="replace")
    assert '("root_cause_log", check_root_cause_log, True)' in src, (
        "the surviving ledger check is not registered ENFORCED in the institutional gate")
    assert ('("rc_mechanism_claims_cite_a_source", '
            '_rc_mechanism_claims_cite_a_source_violations)') in src, (
        "rc_mechanism_claims_cite_a_source's validation is no longer folded into "
        "root_cause_log — the substance was dropped, not consolidated")
