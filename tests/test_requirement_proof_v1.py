# institutional-synthetic-ok: inject parent/child proof trees.
"""Parent/child requirement proof — child PASS never closes a parent (RC-459)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.requirement_proof import (  # noqa: E402
    compute_item_proof,
    compute_proof_state,
    requirement_proof_violations,
)
from tools.check_institutional_correctness import check_requirement_proof  # noqa: E402


def _tree(items):
    return {
        "authority": "governance/requirement_tree.json",
        "items": items,
    }


def test_child_pass_does_not_close_unfinished_parent():
    tree = _tree([
        {"id": "PARENT", "proof": "NOT_PROVEN", "closable": True,
         "children": ["C1", "C2"]},
        {"id": "C1", "proof": "PASS", "closable": True},
        {"id": "C2", "proof": "NOT_PROVEN", "closable": True},
    ])
    by = {i["id"]: i for i in tree["items"]}
    assert compute_item_proof(by["PARENT"], by) == "NOT_PROVEN"


def test_all_children_pass_makes_closable_parent_pass():
    tree = _tree([
        {"id": "PARENT", "proof": "NOT_PROVEN", "closable": True,
         "children": ["C1", "C2"]},
        {"id": "C1", "proof": "PASS"},
        {"id": "C2", "proof": "PASS"},
    ])
    by = {i["id"]: i for i in tree["items"]}
    assert compute_item_proof(by["PARENT"], by) == "PASS"


def test_one_child_fail_makes_parent_fail():
    tree = _tree([
        {"id": "PARENT", "proof": "NOT_PROVEN", "closable": True,
         "children": ["C1", "C2"]},
        {"id": "C1", "proof": "PASS"},
        {"id": "C2", "proof": "FAIL"},
    ])
    by = {i["id"]: i for i in tree["items"]}
    assert compute_item_proof(by["PARENT"], by) == "FAIL"


def test_nonclosable_parent_stays_not_proven_when_children_pass():
    tree = _tree([
        {"id": "OF_PARENT", "proof": "NOT_PROVEN", "closable": False,
         "children": ["C1"]},
        {"id": "C1", "proof": "PASS"},
    ])
    by = {i["id"]: i for i in tree["items"]}
    assert compute_item_proof(by["OF_PARENT"], by) == "NOT_PROVEN"
    v = requirement_proof_violations(
        tree=tree,
        derived={"items": [
            {"id": "OF_PARENT", "proof": "PASS"},
            {"id": "C1", "proof": "PASS"},
        ]},
    )
    assert v and any("child PASS never closes" in m or "non-closable" in m or "derived" in m for m in v)


def test_hand_set_parent_pass_blocks():
    tree = _tree([
        {"id": "PARENT", "proof": "PASS", "closable": True,
         "children": ["C1"]},
        {"id": "C1", "proof": "NOT_PROVEN"},
    ])
    v = requirement_proof_violations(tree=tree, derived={"items": []})
    assert any("declared PASS but computed NOT_PROVEN" in m for m in v)


def test_live_tree_parents_not_closed_by_children():
    state = compute_proof_state()
    by = {i["id"]: i for i in state["items"]}
    assert by["OF_PARENT"]["proof"] == "NOT_PROVEN"
    assert by["P2_PARENT"]["proof"] == "NOT_PROVEN"
    assert by["LP01_PARENT"]["proof"] == "NOT_PROVEN"
    assert by["OF_COMPOSITE_RETIRED"]["proof"] == "PASS"
    assert by["IDENTITY_SPLIT_REMOVED"]["proof"] == "PASS"
    assert check_requirement_proof() == []
