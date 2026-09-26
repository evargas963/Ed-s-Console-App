"""COH-SA fusion-predicates: fusion_is_authoritative and is_canonical_tradable."""

from __future__ import annotations

import re
from pathlib import Path


_SKIP_PY_TREE_DIRS = frozenset(
    {".claude", ".git", ".venv", "venv", "node_modules", "__pycache__"}
)
_FUSION_AVAILABLE_GETATTR = re.compile(
    r"""getattr\s*\(\s*_?fusion\w*\s*,\s*['"]available['"]\s*""",
    re.IGNORECASE,
)
_NON_TRADABLE_MEMBERSHIP = re.compile(
    r"""in\s+NON_TRADABLE_CANONICAL_PROVENANCE"""
)
_TRADABLE_MEMBERSHIP = re.compile(
    r"""in\s+TRADABLE_CANONICAL_PROVENANCE"""
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


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














def test_no_inline_fusion_available_getattr_outside_fusion_contract(repo_index):
    offenders: list[str] = []
    for rel, src in _iter_production_py(repo_index):
        if rel.name in ("fusion_contract.py",):
            continue
        if _FUSION_AVAILABLE_GETATTR.search(src):
            offenders.append(str(rel).replace("\\", "/"))
    assert not offenders, offenders


def test_no_inline_non_tradable_membership_outside_authority(repo_index):
    allowed = {"fusion_contract.py", "signal_types.py"}
    offenders: list[str] = []
    for rel, src in _iter_production_py(repo_index):
        if rel.name in allowed:
            continue
        if _NON_TRADABLE_MEMBERSHIP.search(src):
            offenders.append(str(rel).replace("\\", "/"))
    assert not offenders, offenders

    st_src = (_repo_root() / "signal_types.py").read_text(encoding="utf-8")
    idx = st_src.index("NON_TRADABLE_CANONICAL_PROVENANCE")
    doc = st_src[:idx]
    assert "Diagnostic" in doc
    assert "do not use this set as a gate" in doc.lower()


def test_no_inline_tradable_membership_outside_authority(repo_index):
    allowed = {"fusion_contract.py", "signal_types.py"}
    offenders: list[str] = []
    for rel, src in _iter_production_py(repo_index):
        if rel.name in allowed:
            continue
        if _TRADABLE_MEMBERSHIP.search(src):
            offenders.append(str(rel).replace("\\", "/"))
    assert not offenders, offenders
