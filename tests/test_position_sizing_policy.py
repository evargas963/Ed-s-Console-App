"""COH-SA regime multipliers single authority (position_sizing_policy.py)."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from position_sizing_policy import (
    REGIME_SIZE_MULTIPLIER_DEFAULT,
    REGIME_SIZE_MULTIPLIERS,
    regime_size_multiplier,
)

_SKIP_PY_TREE_DIRS = frozenset(
    {".claude", ".git", ".venv", "venv", "node_modules", "__pycache__"}
)
_REGIME_MULT_INLINE = re.compile(r"""REGIME_MULT\s*=\s*\{""")
_REGIME_MULT_DEF = re.compile(r"""def\s+regime_size_multiplier\s*\(""")


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


def test_regime_size_multiplier_known_labels():
    assert regime_size_multiplier("trend_continuation") == 1.00
    assert regime_size_multiplier("trend_continuation", "low") == 0.90
    assert regime_size_multiplier("reversal_prone", "low") == 0.40
    assert regime_size_multiplier("pinning", "high") == 0.70
    assert regime_size_multiplier("breakout", "high") == 1.00


def test_regime_size_multiplier_unknown_and_typo_use_default(caplog):
    caplog.set_level(logging.DEBUG)
    assert regime_size_multiplier("unknown") == REGIME_SIZE_MULTIPLIER_DEFAULT
    assert regime_size_multiplier("not_a_regime") == REGIME_SIZE_MULTIPLIER_DEFAULT
    assert regime_size_multiplier(None) == REGIME_SIZE_MULTIPLIER_DEFAULT
    assert any("unmapped regime_label" in r.message for r in caplog.records)


def test_regime_size_multiplier_confidence_nudge():
    base = REGIME_SIZE_MULTIPLIERS["vol_compression"]
    assert regime_size_multiplier("vol_compression", "medium") == base
    assert regime_size_multiplier("vol_compression", "high") == min(1.0, base + 0.10)
    assert regime_size_multiplier("vol_compression", "low") == max(0.40, base - 0.10)


def test_no_inline_regime_mult_dict_outside_authority():
    root = _repo_root()
    offenders: list[str] = []
    for path, rel in _iter_production_py(root):
        if rel.name == "position_sizing_policy.py":
            continue
        src = path.read_text(encoding="utf-8")
        if _REGIME_MULT_INLINE.search(src):
            offenders.append(str(rel).replace("\\", "/"))
    assert not offenders, offenders


def test_no_regime_size_multiplier_defs_outside_authority():
    root = _repo_root()
    offenders: list[str] = []
    for path, rel in _iter_production_py(root):
        if rel.name == "position_sizing_policy.py":
            continue
        src = path.read_text(encoding="utf-8")
        if _REGIME_MULT_DEF.search(src):
            offenders.append(str(rel).replace("\\", "/"))
    assert not offenders, offenders
