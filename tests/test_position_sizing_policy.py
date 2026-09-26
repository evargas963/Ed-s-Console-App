"""COH-SA regime multipliers single authority (position_sizing_policy.py)."""

from __future__ import annotations

import re


_SKIP_PY_TREE_DIRS = frozenset(
    {".claude", ".git", ".venv", "venv", "node_modules", "__pycache__"}
)
_REGIME_MULT_INLINE = re.compile(r"""REGIME_MULT\s*=\s*\{""")
_REGIME_MULT_DEF = re.compile(r"""def\s+regime_size_multiplier\s*\(""")


#: TEST_SYSTEM_REHAB_V2: was an independent root.rglob("*.py") + per-file read_text --
#: now sources from the shared tests/conftest.py `repo_index` corpus. Filter semantics
#: unchanged (skip tests/ and the same build-tool dirs).
def _iter_production_py(repo_index):
    for rel, text, _tree in repo_index.items():
        if rel.parts and rel.parts[0] == "tests":
            continue
        if any(part in _SKIP_PY_TREE_DIRS for part in rel.parts):
            continue
        yield rel, text








def test_no_inline_regime_mult_dict_outside_authority(repo_index):
    offenders: list[str] = []
    for rel, src in _iter_production_py(repo_index):
        if rel.name == "position_sizing_policy.py":
            continue
        if _REGIME_MULT_INLINE.search(src):
            offenders.append(str(rel).replace("\\", "/"))
    assert not offenders, offenders


def test_no_regime_size_multiplier_defs_outside_authority(repo_index):
    offenders: list[str] = []
    for rel, src in _iter_production_py(repo_index):
        if rel.name == "position_sizing_policy.py":
            continue
        if _REGIME_MULT_DEF.search(src):
            offenders.append(str(rel).replace("\\", "/"))
    assert not offenders, offenders
