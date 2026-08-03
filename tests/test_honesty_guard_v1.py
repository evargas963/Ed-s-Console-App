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


def test_honesty_guard_wired_blocks_missing_cursor_hook():
    from tools.check_institutional_correctness import check_honesty_guard_wired

    hooks = REPO / ".cursor" / "hooks.json"
    orig = hooks.read_text(encoding="utf-8")
    broken = orig.replace("honesty_guard.py", "honesty_guard_MISSING.py")
    try:
        hooks.write_text(broken, encoding="utf-8")
        v = check_honesty_guard_wired()
        assert v and any("hooks.json" in str(x.path).replace("\\", "/") for x in v)
        assert any("honesty_guard.py" in x.msg for x in v)
    finally:
        hooks.write_text(orig, encoding="utf-8")
    assert check_honesty_guard_wired() == []


def test_honesty_guard_wired_blocks_missing_claude_hook():
    from tools.check_institutional_correctness import check_honesty_guard_wired

    settings = REPO / ".claude" / "settings.json"
    orig = settings.read_text(encoding="utf-8")
    broken = orig.replace("honesty_guard.py", "honesty_guard_MISSING.py")
    try:
        settings.write_text(broken, encoding="utf-8")
        v = check_honesty_guard_wired()
        assert v and any("settings.json" in str(x.path).replace("\\", "/") for x in v)
        assert any("honesty_guard.py" in x.msg for x in v)
    finally:
        settings.write_text(orig, encoding="utf-8")
    assert check_honesty_guard_wired() == []


def test_cursor_hooks_require_honesty():
    from tools.check_institutional_correctness import plus_player_cursor_hooks_violations

    assert plus_player_cursor_hooks_violations('{"hooks":{}}')
    assert "honesty_guard.py" in (
        (REPO / ".cursor" / "hooks.json").read_text(encoding="utf-8")
    )
    assert plus_player_cursor_hooks_violations() == []


def test_catalog_bans_soft_partial():
    from tools.plus_player_locks import catalog_completeness_violations

    bad = {
        "attributes": [{
            "id": "RES-01",
            "pillar": "res",
            "enforcement": "soft_partial",
            "enforcer": "soft:operator_review",
            "soft_reason": "theater",
        }],
    }
    v = catalog_completeness_violations(bad)
    assert any("soft_partial forbidden" in x for x in v)
