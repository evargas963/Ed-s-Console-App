"""COH-SA fusion-predicates: fusion_is_authoritative and is_canonical_tradable."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

from fusion_contract import (
    canonical_provenance_is_tradable,
    fusion_is_authoritative,
    is_canonical_tradable,
    is_ms_dict_fusion_authoritative,
)
from signal_types import (
    NON_TRADABLE_CANONICAL_PROVENANCE,
    TRADABLE_CANONICAL_PROVENANCE,
    CanonicalForecast,
)

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


def test_fusion_is_authoritative_none_and_false():
    assert fusion_is_authoritative(None) is False
    assert fusion_is_authoritative(SimpleNamespace(available=False)) is False
    assert fusion_is_authoritative(SimpleNamespace(available=True)) is True
    assert fusion_is_authoritative(SimpleNamespace()) is False


def test_is_ms_dict_fusion_authoritative_provenance_gate():
    assert is_ms_dict_fusion_authoritative({"fusion_available": False}) is False
    assert is_ms_dict_fusion_authoritative({"fusion_available": True}) is False
    prov = next(iter(NON_TRADABLE_CANONICAL_PROVENANCE))
    assert (
        is_ms_dict_fusion_authoritative(
            {"fusion_available": True, "canonical_provenance": prov}
        )
        is False
    )
    assert (
        is_ms_dict_fusion_authoritative(
            {
                "fusion_available": True,
                "canonical_provenance": next(iter(TRADABLE_CANONICAL_PROVENANCE)),
            }
        )
        is True
    )


def test_gate_rejects_empty_canonical_provenance_when_fusion_available():
    ms = {"fusion_available": True, "canonical_provenance": ""}
    assert canonical_provenance_is_tradable("") is False
    assert is_ms_dict_fusion_authoritative(ms) is False


def test_gate_rejects_debug_override_canonical_provenance_when_fusion_available():
    prov = "debug_override:api"
    ms = {"fusion_available": True, "canonical_provenance": prov}
    assert canonical_provenance_is_tradable(prov) is False
    assert is_ms_dict_fusion_authoritative(ms) is False


def test_gate_admits_bayesian_fusion_provenance_when_fusion_available():
    prov = "bayesian_fusion"
    ms = {"fusion_available": True, "canonical_provenance": prov}
    assert canonical_provenance_is_tradable(prov) is True
    assert is_ms_dict_fusion_authoritative(ms) is True


def test_is_canonical_tradable_placeholders():
    for prov in NON_TRADABLE_CANONICAL_PROVENANCE:
        c = CanonicalForecast(
            direction="flat",
            probability_up=1 / 3,
            probability_down=1 / 3,
            probability_flat=1 / 3,
            confidence="low",
            provenance=prov,
        )
        assert is_canonical_tradable(c) is False
        assert canonical_provenance_is_tradable(prov) is False

    ok = CanonicalForecast(
        direction="up",
        probability_up=0.6,
        probability_down=0.2,
        probability_flat=0.2,
        confidence="high",
        provenance="bayesian_fusion",
    )
    assert is_canonical_tradable(ok) is True


def test_no_inline_fusion_available_getattr_outside_fusion_contract():
    root = _repo_root()
    offenders: list[str] = []
    for path, rel in _iter_production_py(root):
        if rel.name in ("fusion_contract.py",):
            continue
        src = path.read_text(encoding="utf-8")
        if _FUSION_AVAILABLE_GETATTR.search(src):
            offenders.append(str(rel).replace("\\", "/"))
    assert not offenders, offenders


def test_no_inline_non_tradable_membership_outside_authority():
    root = _repo_root()
    allowed = {"fusion_contract.py", "signal_types.py"}
    offenders: list[str] = []
    for path, rel in _iter_production_py(root):
        if rel.name in allowed:
            continue
        src = path.read_text(encoding="utf-8")
        if _NON_TRADABLE_MEMBERSHIP.search(src):
            offenders.append(str(rel).replace("\\", "/"))
    assert not offenders, offenders
