"""REPO_SWEEP magic-thresholds: named constants + banned -999.0 literal guard."""

from __future__ import annotations

import re

import pytest

from lifecycle_rule_core import (
    T1_FALLBACK_R_MULTIPLE,
    T2_OFFSET_R_MULTIPLE,
    derive_target_levels,
)
from math_exposure import MISSING_GREEK_SENTINEL
from math_exposure_core import MISSING_GREEK_SENTINEL as CORE_SENTINEL

_SKIP_PY_TREE_DIRS = frozenset(
    {
        ".claude",
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        "tests",
        "tools",
        "governance",
    }
)
_MISSING_GREEK_SENTINEL_LITERAL = re.compile(r"-999\.0")
_AUTHORITY_FILE = "math_exposure_core.py"


#: TEST_SYSTEM_REHAB_V2: was an independent root.rglob("*.py") + per-file read_text --
#: now sources from the shared tests/conftest.py `repo_index` corpus. Filter semantics
#: unchanged (skip tests/tools/governance and the same build-tool dirs).
def _iter_production_py(repo_index):
    for rel, text, _tree in repo_index.items():
        if rel.parts and rel.parts[0] == "tests":
            continue
        if any(part in _SKIP_PY_TREE_DIRS for part in rel.parts):
            continue
        yield rel, text


def _offending_literal_lines(src: str, rel_name: str) -> list[str]:
    offenders: list[str] = []
    for i, line in enumerate(src.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if _MISSING_GREEK_SENTINEL_LITERAL.search(line) is None:
            continue
        if rel_name == _AUTHORITY_FILE and "MISSING_GREEK_SENTINEL" in line:
            continue
        if "(-999)" in line:
            continue
        offenders.append(f"{rel_name}:{i}")
    return offenders


def test_missing_greek_sentinel_constant_value_is_negative_999_point_0():
    assert CORE_SENTINEL == pytest.approx(-999.0)
    assert MISSING_GREEK_SENTINEL == pytest.approx(-999.0)


def test_t1_fallback_and_t2_offset_constants_pin_expected_r_multiples():
    assert T1_FALLBACK_R_MULTIPLE == pytest.approx(2.0)
    assert T2_OFFSET_R_MULTIPLE == pytest.approx(1.0)
    levels = derive_target_levels(
        direction="long",
        entry=100.0,
        risk=1.0,
        avg5=None,
        avg15=None,
        avg60=None,
        structural_levels=[],
    )
    assert levels.target_source == "2r_fallback"
    assert levels.target == pytest.approx(102.0)
    assert levels.target2_source == "1r_offset_from_t1"
    assert levels.target2 == pytest.approx(103.0)


def test_no_inline_missing_greek_sentinel_literal_in_production_outside_authority(repo_index):
    """Repo-wide guard (sweep-3 shape): only math_exposure_core may define -999.0."""
    offenders: list[str] = []
    for rel, src in _iter_production_py(repo_index):
        rel_s = str(rel).replace("\\", "/")
        offenders.extend(_offending_literal_lines(src, rel_s))
    assert not offenders, offenders
