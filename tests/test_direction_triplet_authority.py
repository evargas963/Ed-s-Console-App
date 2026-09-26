"""COH-SA direction triplet: no inline max(up,down,flat) outside numeric_contract."""

from __future__ import annotations

import re

from numeric_contract import direction_from_normalized_triplet

_SKIP_PY_TREE_DIRS = frozenset(
    {".claude", ".git", ".venv", "venv", "node_modules", "__pycache__"}
)
_INLINE_TRIPLET_MAX = re.compile(
    r"""max\s*\(\s*(\[["\']up["\']\s*,\s*["\']down["\']\s*,\s*["\']flat["\']\]|"""
    r"""["\']up["\']\s*,\s*["\']down["\']\s*,\s*["\']flat["\'])"""
)


#: TEST_SYSTEM_REHAB_V2: was an independent root.rglob("*.py") + per-file read_text --
#: now sources from the shared tests/conftest.py `repo_index` corpus (one read of the
#: whole tree per run, not a private re-walk per file). Filter semantics unchanged
#: (skip tests/ and the same build-tool dirs); repo_index's own skip set is a strict
#: superset (also excludes build/dist/.pytest_cache/.mypy_cache/.ruff_cache, none of
#: which ever hold tracked production source).
def _iter_production_py(repo_index):
    for rel, text, _tree in repo_index.items():
        if rel.parts and rel.parts[0] == "tests":
            continue
        if any(part in _SKIP_PY_TREE_DIRS for part in rel.parts):
            continue
        yield rel, text




def test_no_inline_triplet_max_outside_numeric_contract(repo_index):
    allowed = {"numeric_contract.py"}
    offenders: list[str] = []
    for rel, src in _iter_production_py(repo_index):
        if rel.name in allowed:
            continue
        if _INLINE_TRIPLET_MAX.search(src):
            offenders.append(str(rel).replace("\\", "/"))
    assert not offenders, offenders


def test_direction_from_normalized_triplet_tie_up_first():
    assert direction_from_normalized_triplet(1 / 3, 1 / 3, 1 / 3) == "up"
