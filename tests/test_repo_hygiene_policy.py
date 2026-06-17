"""Tests for Phase 3I repo hygiene policy."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.check_repo_hygiene_policy import (  # noqa: E402
    ACTIONABLE_BACKLOG_CATEGORIES,
    check_hygiene_touch_disposition,
    check_repo_hygiene_policy,
    staged_intersects_actionable_candidate,
)

SAMPLE_BACKLOG = {
    "actionable_only": True,
    "items": [
        {
            "candidate": "arch_competition/numeric_safe.py",
            "category": "orphan_candidate",
            "status": "open",
        },
        {
            "candidate": ".claude/agents/rules-auditor.md",
            "category": "manual_review_required",
            "status": "open",
        },
        {
            "candidate": "governance/docs/OLD_PHASE.md",
            "category": "manual_review_required",
            "status": "open",
        },
    ],
}


@pytest.fixture
def patch_backlog(monkeypatch, tmp_path):
    path = tmp_path / "REPO_HYGIENE_BACKLOG.json"
    path.write_text(json.dumps(SAMPLE_BACKLOG), encoding="utf-8")
    monkeypatch.setattr("tools.check_repo_hygiene_policy.BACKLOG_PATH", path)
    return path


def test_repo_hygiene_policy_passes_on_current_repo():
    errs = check_repo_hygiene_policy()
    assert errs == [], errs


def test_inventory_has_required_categories():
    inv = json.loads(
        (REPO / "governance/artifacts/REPO_HYGIENE_INVENTORY.json").read_text(encoding="utf-8")
    )
    cats = inv["summary"]["by_category"]
    assert cats.get("active_runtime", 0) > 0
    assert cats.get("generated_artifact", 0) > 0
    assert "manual_review_required" in cats


def test_backlog_is_actionable_only():
    backlog = json.loads(
        (REPO / "governance/artifacts/REPO_HYGIENE_BACKLOG.json").read_text(encoding="utf-8")
    )
    assert backlog.get("actionable_only") is True
    for item in backlog.get("items") or []:
        assert item.get("category") in ACTIONABLE_BACKLOG_CATEGORIES


def test_gate_triggers_on_actionable_candidate_in_staged_cone(patch_backlog):
    errs = check_hygiene_touch_disposition(
        staged={"arch_competition/numeric_safe.py"},
        commit_text="fix: touch orphan directly",
    )
    assert errs, "expected HYGIENE requirement when editing actionable candidate"


def test_gate_does_not_trigger_for_sibling_in_broad_tools_dir(patch_backlog, monkeypatch):
    backlog = {
        "actionable_only": True,
        "items": [
            {
                "candidate": "tools/__init__.py",
                "category": "orphan_candidate",
                "status": "open",
            },
        ],
    }
    import json
    import tools.check_repo_hygiene_policy as mod

    path = REPO / ".git" / "COMMIT_MSG_TMP_HYGIENE_TEST.json"
    path.write_text(json.dumps(backlog), encoding="utf-8")
    monkeypatch.setattr(mod, "BACKLOG_PATH", path)
    errs = check_hygiene_touch_disposition(
        staged={"tools/check_repo_hygiene_policy.py"},
        commit_text="Add repo hygiene governance",
    )
    assert errs == []


def test_gate_does_not_trigger_on_manual_review_outside_staged_cone(patch_backlog):
    errs = check_hygiene_touch_disposition(
        staged={"market_state.py"},
        commit_text="fix: unrelated production edit",
    )
    assert errs == []


def test_gate_does_not_trigger_for_unrelated_edit_even_with_manual_review_in_repo(patch_backlog):
    errs = check_hygiene_touch_disposition(
        staged={"ml_train.py"},
        commit_text="train: anchor roster tweak",
    )
    assert errs == []


def test_gate_requires_hygiene_when_touching_actionable_candidate_file(patch_backlog):
    errs = check_hygiene_touch_disposition(
        staged={"arch_competition/numeric_safe.py"},
        commit_text="chore: touch orphan module",
    )
    assert any("actionable backlog" in e for e in errs)


@pytest.mark.parametrize(
    "marker",
    [
        "HYGIENE: cleaned",
        "HYGIENE: deferred_with_reason",
        "HYGIENE: manual_review_required",
    ],
)
def test_gate_accepts_exact_disposition_markers(patch_backlog, marker):
    errs = check_hygiene_touch_disposition(
        staged={"arch_competition/numeric_safe.py"},
        commit_text=f"fix: orphan\n\n{marker}",
    )
    assert errs == []


def test_gate_rejects_vague_hygiene_language(patch_backlog):
    errs = check_hygiene_touch_disposition(
        staged={"market_state.py"},
        commit_text="HYGIENE: cleaned up the module",
    )
    assert any("exact disposition" in e for e in errs)


def test_gate_rejects_vague_hygiene_when_actionable_hit_without_exact_marker(patch_backlog):
    errs = check_hygiene_touch_disposition(
        staged={"arch_competition/numeric_safe.py"},
        commit_text="hygiene pass on arch_competition",
    )
    assert errs


def test_staged_intersection_same_directory():
    assert staged_intersects_actionable_candidate(
        "arch_competition/foo.py",
        "arch_competition/numeric_safe.py",
    )


def test_staged_intersection_not_cross_package():
    assert not staged_intersects_actionable_candidate(
        "market_state.py",
        "arch_competition/numeric_safe.py",
    )
