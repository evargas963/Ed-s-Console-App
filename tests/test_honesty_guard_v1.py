"""RC-209: honesty_guard BLOCKS dodge / MD-as-lock / Soft-theater 10/10 claims."""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_honesty_violations_require_yes_no():
    from tools.honesty_guard import honesty_violations

    bad = honesty_violations(
        "is there a mechanical lock against lying?",
        "We should think carefully about institutional standards and research papers.",
    )
    assert bad and any("yes/no" in b for b in bad)
    assert honesty_violations(
        "is there a mechanical lock against lying?",
        "No. There is no such lock yet.",
    ) == []


def test_honesty_violations_require_score():
    from tools.honesty_guard import honesty_violations

    assert honesty_violations("what is the score of the locks?", "Looking good overall.")
    assert honesty_violations("what is the score of the locks?", "Score: 4/10.") == []


def test_lock7_lock_claim_must_name_mechanism():
    """LOCK-7 (RC-232): 'locked via mandate/rule' without a CHECK id or guard .py BLOCKS;
    naming the mechanism passes."""
    from tools.honesty_guard import honesty_violations

    bad = honesty_violations(None, "This is now locked via the mandate we wrote today.")
    assert any("without naming a CHECK id" in m for m in bad), bad
    ok = honesty_violations(
        None, "This is now locked via the mandate, enforced by check_writer_no_drift "
              "and process_lock_guard.py at PreToolUse.")
    assert not any("without naming a CHECK id" in m for m in ok)


def test_honesty_blocks_md_as_lock_claim():
    from tools.honesty_guard import honesty_violations

    assert honesty_violations(
        "are we locked?",
        "Yes. The mechanical lock is reports/plus_player_lock_strength_v1.md",
    )


def test_honesty_deliverable_scores_required():
    from tools.honesty_guard import honesty_violations

    u = "Return ONLY plain scores for every surface at 10/10 with evidence."
    assert honesty_violations(u, "We should consider improvements going forward.")
    ok = "Surface 1 honesty: 10/10. Files changed: tools/find_prove_locks.py"
    assert honesty_violations(u, ok) == []


# RC-470: the wired/catalog controls (honesty_guard_wired x2, cursor_hooks_require_
# honesty, catalog_bans_soft_partial) left with their retired checks -
# governance/retired_checks.md. Hook-wiring changes are operator-reviewed at merge
# (RC-475); the wiring FACT stays pinned directly below. The guard's own behavioral
# controls above are untouched.
def test_cursor_hooks_still_name_honesty_guard():
    """The wiring FACT the retired checks watched, pinned directly: both hook files
    name honesty_guard.py. (Parity's five-guard assertion covers this too; this keeps
    a local, obvious statement of the fact beside the guard's own tests.)"""
    assert "honesty_guard.py" in (
        (REPO / ".cursor" / "hooks.json").read_text(encoding="utf-8"))
    assert "honesty_guard.py" in (
        (REPO / ".claude" / "settings.json").read_text(encoding="utf-8"))
