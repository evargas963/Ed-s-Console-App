"""COH-SA-1: local float parsers delegate to numeric_contract (finite / positive)."""

from __future__ import annotations

import re


_SKIP_PY_TREE_DIRS = frozenset(
    {".claude", ".git", ".venv", "venv", "node_modules", "__pycache__"}
)

# COH-SA-1 redirect sites.


_INLINE_FLOAT_TRY_EXCEPT = re.compile(
    r"def\s+_float_or_none\s*\([^)]*\)[^:]*:\s*\n\s+try:",
    re.MULTILINE,
)
_INLINE_F_TRY_EXCEPT = re.compile(
    r"def\s+_f\s*\([^)]*\)[^:]*:\s*\n\s+try:",
    re.MULTILINE,
)
_INLINE_NUM_TRY_EXCEPT = re.compile(
    r"def\s+_num\s*\([^)]*\)[^:]*:\s*\n\s+try:",
    re.MULTILINE,
)


#: TEST_SYSTEM_REHAB_V2: was an independent root.rglob("*.py") + per-file read_text --
#: now sources from the shared tests/conftest.py `repo_index` corpus. Filter semantics
#: unchanged (skip tests/ and the same build-tool dirs).
def _iter_repo_py_files(repo_index):
    for rel, text, _tree in repo_index.items():
        if rel.parts and rel.parts[0] == "tests":
            continue
        if any(part in _SKIP_PY_TREE_DIRS for part in rel.parts):
            continue
        yield rel, text








def test_all_float_or_none_helpers_delegate_to_numeric_contract(repo_index):
    offenders: list[str] = []
    for rel, src in _iter_repo_py_files(repo_index):
        if "def _float_or_none" not in src:
            continue
        if "float_finite_or_none" not in src:
            offenders.append(f"{rel}: missing float_finite_or_none delegation")
        elif _INLINE_FLOAT_TRY_EXCEPT.search(src):
            offenders.append(f"{rel}: inline try/except _float_or_none body")
    assert not offenders, offenders


def test_all_positive_float_helpers_delegate_to_numeric_contract(repo_index):
    offenders: list[str] = []
    for rel, src in _iter_repo_py_files(repo_index):
        if "def _positive_float_or_none" not in src:
            continue
        if "float_positive_or_none" not in src:
            offenders.append(str(rel))
    assert not offenders, offenders








_MODULE_LEVEL_F = re.compile(r"^def _f\s*\(", re.MULTILINE)
_MODULE_LEVEL_NUM = re.compile(r"^def _num\s*\(", re.MULTILINE)


def test_all_module_level_f_helpers_delegate_to_numeric_contract(repo_index):
    """Module-level ``def _f`` parsers (not nested locals in ml_train / adapters)."""
    offenders: list[str] = []
    for rel, src in _iter_repo_py_files(repo_index):
        if not _MODULE_LEVEL_F.search(src):
            continue
        if "float_finite_or_none" not in src:
            offenders.append(f"{rel}: missing float_finite_or_none delegation")
        elif _INLINE_F_TRY_EXCEPT.search(src):
            offenders.append(f"{rel}: inline try/except _f body")
    assert not offenders, offenders


def test_all_module_level_num_helpers_delegate_to_numeric_contract(repo_index):
    offenders: list[str] = []
    for rel, src in _iter_repo_py_files(repo_index):
        if not _MODULE_LEVEL_NUM.search(src):
            continue
        if "float_finite_or_none" not in src:
            offenders.append(f"{rel}: missing float_finite_or_none delegation")
        elif _INLINE_NUM_TRY_EXCEPT.search(src):
            offenders.append(f"{rel}: inline try/except _num body")
    assert not offenders, offenders


def test_no_legacy_inline_float_or_none_try_body(repo_index):
    """_float_or_none helpers must delegate; no inline try/return float bodies."""
    offenders: list[str] = []
    for rel, src in _iter_repo_py_files(repo_index):
        if "def _float_or_none" not in src:
            continue
        if "float_finite_or_none" not in src:
            offenders.append(f"{rel}: missing delegation")
        elif _INLINE_FLOAT_TRY_EXCEPT.search(src):
            offenders.append(f"{rel}: legacy inline try body")
    assert not offenders, offenders
