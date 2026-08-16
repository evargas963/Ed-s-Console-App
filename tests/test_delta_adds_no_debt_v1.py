"""RC-387 — the delta gate must FAIL a regression, or it is decoration.

The tool exists because tests an author writes only encode failure modes that author
already imagined. It would be self-refuting to ship it without a lock, and it was: the
Stop supervisor's ownership resolution found no owning suite for
tools/check_delta_adds_no_debt.py, which is what these controls repair.

The load-bearing property is asymmetry. A comparison that cannot fail is a rubber stamp —
the exact defect that produced four bad ledger closes earlier in the same session — so the
first control plants a regression and demands a FAIL.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# RC-368: declared direct owner of the tool under test.
TURN_AUDIT_OWNS = ["tools/check_delta_adds_no_debt.py"]


def _load():
    spec = importlib.util.spec_from_file_location(
        "delta_gate", REPO / "tools" / "check_delta_adds_no_debt.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GATE = _load()

BASE = {"root_cause_log": 71, "open_item_cap": 1}


def test_a_new_violation_fails_and_is_named():
    """THE PROPERTY: a check that appears on HEAD and not on base must fail, by name."""
    head = dict(BASE, checks_are_justified=1)
    added, improved = GATE.compare(BASE, head)
    assert added, "a brand-new enforced violation did not fail the delta gate"
    assert any("checks_are_justified" in a for a in added), added
    assert "0 -> 1" in added[0], added


def test_a_rise_in_an_existing_violation_also_fails():
    """Regressions arrive as +1 on an existing check as often as a new one."""
    added, _ = GATE.compare(BASE, dict(BASE, root_cause_log=72))
    assert added and "71 -> 72" in added[0], added


def test_unchanged_passes_and_improvement_passes():
    """It must not block ordinary work, or it gets switched off."""
    assert GATE.compare(BASE, dict(BASE)) == ([], [])
    added, improved = GATE.compare(BASE, dict(BASE, root_cause_log=27))
    assert added == []
    assert improved and "71 -> 27" in improved[0]


def test_a_preexisting_backlog_never_masks_a_fresh_regression():
    """The design decision that decides whether this tool survives contact.

    Base carries 72 violations; HEAD pays 44 of them AND adds one new check. A
    whole-number comparison would report a big net improvement and wave the regression
    through. Added must be reported on its own terms.
    """
    head = {"root_cause_log": 27, "open_item_cap": 1, "checks_are_justified": 1}
    added, improved = GATE.compare(BASE, head)
    assert sum(head.values()) < sum(BASE.values()), "precondition: HEAD is numerically better"
    assert added, "a regression was masked by a net-improved total"
    assert any("checks_are_justified" in a for a in added), added


def test_parser_reads_the_real_gate_output_shape():
    """Parsed from --enforced-only stdout; the separator glyph varies by console encoding."""
    for dash in ("-", "—"):
        text = (f"FAIL [root_cause_log] (ENFORCED) {dash} 71 violation(s):\n"
                f"FAIL [open_item_cap] (ENFORCED) {dash} 1 violation(s):\n"
                f"INSTITUTIONAL CORRECTNESS GATE: FAIL (72 enforced violation(s))")
        assert GATE.parse_counts(text) == {"root_cause_log": 71, "open_item_cap": 1}


def test_parser_ignores_passing_checks_and_summary_lines():
    text = ("PASS [venv_parity] (ENFORCED)\n"
            "INSTITUTIONAL CORRECTNESS GATE: FAIL (5 enforced violation(s))")
    assert GATE.parse_counts(text) == {}


def test_the_tool_measures_in_a_clean_worktree_not_the_dirty_tree():
    """A dirty tree carries scratch that is not the change — the source of the
    filtered-count error this tool exists to prevent."""
    src = (REPO / "tools" / "check_delta_adds_no_debt.py").read_text(encoding="utf-8")
    assert "worktree" in src and "--detach" in src, (
        "the gate must materialise both sides in clean detached worktrees")
    assert "worktree\", \"remove\"" in src or "'worktree', 'remove'" in src, (
        "the temporary worktree must be removed again")
