"""RC-257 — an unrecognised RC status must FAIL the run, never skip it.

WHAT WAS MEASURED (2026-08-05, reproduced and widened 2026-08-06). One
deliberately deficient RC row -- no END-TO-END declaration, no observed
evidence -- pushed through `_five_why_lock_violations` and `_rc_row_violations`
with only the status token changed:

    CLOSED                -> 1 + 1 violations   BLOCKED
    CLOSED_WITH_EVIDENCE  -> 0 + 0 violations   passes freely
    DONE                  -> 0 + 0 violations   passes freely
    FINISHED              -> 0 + 0 violations   passes freely
    totally_closed        -> 0 + 0 violations   passes freely

Six clauses rest on one string equality, so a single character defeats all of
them -- and the token that defeats them reads STRONGER to a human than the one
that triggers them. A typo does it silently.

These tests fail against the pre-fix tree: before `check_rc_status_vocabulary`
existed there was nothing to reject an unknown token at all.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import check_institutional_correctness as K  # noqa: E402

LOG = REPO / "governance" / "root_cause_log.md"
PIPE = chr(124)


def _row(status: str, rc_id: str = "RC-999") -> str:
    """A row that is deficient on purpose: no END-TO-END, no observed evidence."""
    cells = [rc_id, status, "2026-08-01", "2026-08-09", "d",
             "a -> b -> c -> d -> e ROOT: r", "FIXED: nothing. no code change"]
    return PIPE + PIPE.join(f" {c} " for c in cells) + PIPE


# ------------------------------------------------------- the vocabulary ----

def test_declared_vocabulary_is_explicit_and_non_empty():
    assert K.DECLARED_RC_STATUSES, "the permitted set must be declared, not emergent"
    assert "OPEN" in K.DECLARED_RC_STATUSES
    assert "CLOSED" in K.DECLARED_RC_STATUSES


def test_closed_class_is_a_subset_of_the_declared_set():
    """A closed-class token nobody declared would be unreachable."""
    assert K.CLOSED_CLASS_RC_STATUSES <= K.DECLARED_RC_STATUSES


def test_every_status_in_the_live_ledger_is_declared():
    """The declared set must cover reality, or the check fails the whole log."""
    emergent = set(re.findall(r"^\| RC-\d+ \|\s*(\w+)\s*\|", LOG.read_text(encoding="utf-8"), re.M))
    undeclared = emergent - K.DECLARED_RC_STATUSES
    assert undeclared == set(), (
        f"live ledger uses undeclared statuses {sorted(undeclared)} -- either "
        "they are wrong, or DECLARED_RC_STATUSES is stale")


def test_the_live_ledger_passes_its_own_vocabulary_check():
    assert K.check_rc_status_vocabulary() == []


# --------------------------------------------------- negative controls -----

@pytest.mark.parametrize("token", [
    "CLOSED_WITH_EVIDENCE", "DONE", "FINISHED", "totally_closed",
    "CLOSE", "Closed", "RESOLVED", "FIXED",
])
def test_negative_control_undeclared_status_is_refused(tmp_path, monkeypatch, token):
    """The exact bypass: any token but the declared ones must be REFUSED.

    'Closed' and 'CLOSE' are included deliberately -- a case slip and a typo
    defeat a string equality just as thoroughly as an invented word does.
    """
    log = tmp_path / "governance" / "root_cause_log.md"
    log.parent.mkdir(parents=True)
    log.write_text(_row(token) + "\n", encoding="utf-8")
    monkeypatch.setattr(K, "REPO", tmp_path, raising=True)
    violations = K.check_rc_status_vocabulary()
    assert len(violations) == 1, f"{token!r} slipped through the vocabulary lock"
    assert token in violations[0].msg


def test_cell_padding_is_stripped_not_treated_as_a_new_token(tmp_path, monkeypatch):
    """Markdown pads every cell with spaces; that is formatting, not a status.

    Refusing ' CLOSED ' would fail all 227 existing rows, so stripping is
    correct -- but it must be a deliberate decision with a test, not an
    accident of implementation.
    """
    log = tmp_path / "governance" / "root_cause_log.md"
    log.parent.mkdir(parents=True)
    log.write_text(_row("CLOSED") + "\n", encoding="utf-8")
    monkeypatch.setattr(K, "REPO", tmp_path, raising=True)
    assert K.check_rc_status_vocabulary() == []


@pytest.mark.parametrize("token", ["OPEN", "CLOSED", "REMEDIATED"])
def test_negative_control_declared_status_is_allowed(tmp_path, monkeypatch, token):
    """The check must be able to pass, or it is noise rather than a signal."""
    log = tmp_path / "governance" / "root_cause_log.md"
    log.parent.mkdir(parents=True)
    log.write_text(_row(token) + "\n", encoding="utf-8")
    monkeypatch.setattr(K, "REPO", tmp_path, raising=True)
    assert K.check_rc_status_vocabulary() == []


def test_negative_control_non_rc_lines_are_ignored(tmp_path, monkeypatch):
    """Table headers and prose must not be read as rows."""
    log = tmp_path / "governance" / "root_cause_log.md"
    log.parent.mkdir(parents=True)
    log.write_text(
        "| id | status | opened | due | defect | why | fix |\n"
        "|---|---|---|---|---|---|---|\n"
        "some prose about CLOSED_WITH_EVIDENCE tokens\n"
        + _row("CLOSED") + "\n",
        encoding="utf-8")
    monkeypatch.setattr(K, "REPO", tmp_path, raising=True)
    assert K.check_rc_status_vocabulary() == []


def test_negative_control_the_original_bypass_is_now_two_sided(tmp_path, monkeypatch):
    """Reproduce RC-257's measurement and prove the hole is closed.

    Pre-fix, CLOSED gave 2 violations and CLOSED_WITH_EVIDENCE gave 0, so the
    richer token was strictly better for getting a deficient row past the gate.
    Post-fix the richer token must be caught by SOMETHING -- the close-contract
    clauses still skip it, which is why the vocabulary lock has to exist.
    """
    strict = _row("CLOSED")
    bypass = _row("CLOSED_WITH_EVIDENCE")
    cells_strict = [c.strip() for c in strict.strip().strip(PIPE).split(PIPE)]
    cells_bypass = [c.strip() for c in bypass.strip().strip(PIPE).split(PIPE)]

    # RC-470: the five-why grammar validator is retired (governance/retired_checks.md);
    # _rc_row_violations is the surviving row-content authority and it alone still
    # exhibits RC-257's asymmetry - the literal-CLOSED evidence clause catches the
    # deficient strict row and skips the unknown richer token.
    strict_hits = len(K._rc_row_violations(K.REPO, 1, cells_strict[0],
                                           cells_strict[1], cells_strict))
    bypass_hits = len(K._rc_row_violations(K.REPO, 1, cells_bypass[0],
                                           cells_bypass[1], cells_bypass))
    assert strict_hits > 0, "the deficient CLOSED row must still be caught"
    assert bypass_hits == 0, (
        "documenting the surviving hole: the close-contract clauses still key "
        "on literal CLOSED and still skip an unknown token -- which is exactly "
        "why the vocabulary lock must refuse the token upstream")

    log = tmp_path / "governance" / "root_cause_log.md"
    log.parent.mkdir(parents=True)
    log.write_text(bypass + "\n", encoding="utf-8")
    monkeypatch.setattr(K, "REPO", tmp_path, raising=True)
    assert len(K.check_rc_status_vocabulary()) == 1, (
        "the bypass token must now be refused by the vocabulary lock")


def test_check_is_registered_and_enforced():
    """A check nobody runs is a comment.

    Consolidated 2026-08-24 (governance/retired_checks.md): the vocabulary validation now
    runs INSIDE root_cause_log, so the survivor must be registered ENFORCED and its fold
    table must still name this validator's helper. The injection controls above keep
    driving the real logic through the check_rc_status_vocabulary wrapper."""
    import inspect

    registered = {name: enforced for name, fn, enforced in K.CHECKS}
    assert "root_cause_log" in registered, "the surviving ledger check is not registered"
    assert registered["root_cause_log"] is True, "the surviving ledger check must be ENFORCED"
    assert "_rc_status_vocabulary_violations" in inspect.getsource(
        K._root_cause_ledger_folded_violations), (
        "rc_status_vocabulary's validation is no longer folded into root_cause_log — "
        "the substance was dropped, not consolidated")
