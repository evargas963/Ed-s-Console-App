"""COH-SA direction triplet: no inline max(up,down,flat) outside numeric_contract."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

from numeric_contract import direction_from_normalized_triplet

_SKIP_PY_TREE_DIRS = frozenset(
    {".claude", ".git", ".venv", "venv", "node_modules", "__pycache__"}
)
_INLINE_TRIPLET_MAX = re.compile(
    r"""max\s*\(\s*(\[["\']up["\']\s*,\s*["\']down["\']\s*,\s*["\']flat["\']\]|"""
    r"""["\']up["\']\s*,\s*["\']down["\']\s*,\s*["\']flat["\'])"""
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _iter_production_py(root: Path):
    for path in root.rglob("*.py"):
        rel = path.relative_to(root)
        if rel.parts and rel.parts[0] == "tests":
            continue
        if any(part in _SKIP_PY_TREE_DIRS for part in rel.parts):
            continue
        yield path, rel


def test_stack_model_stage_ignores_dominant_class_uses_triplet():
    """FIND-STACK-DIR1: stack display direction = triplet argmax only."""
    from signals import _build_stack_decision_path
    from tests.test_action11_8_signals_mc_fusion_fail_closed import _call

    xgb = SimpleNamespace(
        available=True,
        dominant_class="up",
        prob_up=0.1,
        prob_down=0.7,
        prob_flat=0.2,
        confidence_label="medium",
    )
    inactive = SimpleNamespace(available=False)
    path = _build_stack_decision_path(xgb, inactive, inactive, inactive, None, _call())
    assert path.xgboost.direction == "down"


def test_no_inline_triplet_max_outside_numeric_contract():
    root = _repo_root()
    allowed = {"numeric_contract.py"}
    offenders: list[str] = []
    for path, rel in _iter_production_py(root):
        if rel.name in allowed:
            continue
        src = path.read_text(encoding="utf-8")
        if _INLINE_TRIPLET_MAX.search(src):
            offenders.append(str(rel).replace("\\", "/"))
    assert not offenders, offenders


def test_direction_from_normalized_triplet_tie_up_first():
    assert direction_from_normalized_triplet(1 / 3, 1 / 3, 1 / 3) == "up"
