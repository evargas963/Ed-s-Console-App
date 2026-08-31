"""AUDIT-MHMLB-NAMESPACE: horizon_fusion_available rename guard (OBS-MHMLB-NS1)."""

from __future__ import annotations

import re

from multi_horizon_ml_bundle import (
    HorizonMLFusionSnapshot,
    MultiHorizonMLFusionBundle,
    fusion_payload_to_horizon_snapshot,
)

_SKIP_DIRS = frozenset(
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
_PER_HORIZON_FUSION_AVAILABLE_LEAK = re.compile(
    r"\bsnap\.fusion_available\b|"
    r"getattr\(\s*snap\s*,\s*['\"]fusion_available['\"]|"
    r"HorizonMLFusionSnapshot\([^)]*\bfusion_available\s*="
)
_MHMLB_FILE = "multi_horizon_ml_bundle.py"


#: TEST_SYSTEM_REHAB_V2: was an independent root.rglob("*.py") + per-file read_text --
#: now sources from the shared tests/conftest.py `repo_index` corpus. Filter semantics
#: unchanged (skip tests/tools/governance and the same build-tool dirs).
def _iter_production_py(repo_index):
    for rel, text, _tree in repo_index.items():
        if rel.parts and rel.parts[0] == "tests":
            continue
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        yield rel.as_posix(), text


def test_horizon_fusion_available_attribute_exists():
    snap = HorizonMLFusionSnapshot(
        horizon_slug="1m",
        horizon_fusion_available=True,
        prob_up=0.5,
        prob_down=0.3,
        prob_flat=0.2,
        dominant_direction="up",
        top_probability=0.5,
        fusion_confidence_label="medium",
        fusion_confidence_score=0.5,
        mc_available=False,
    )
    assert hasattr(snap, "horizon_fusion_available")
    assert not hasattr(snap, "fusion_available")


def test_bundle_method_renamed_to_horizon_fusion_available():
    snap = fusion_payload_to_horizon_snapshot("1m", None)
    bundle = MultiHorizonMLFusionBundle(by_horizon={"1m": snap}, live_canonical_horizon_slug="1m")
    assert callable(bundle.horizon_fusion_available)
    assert bundle.horizon_fusion_available("1m") is False
    assert not hasattr(bundle, "fusion_available")


def test_no_inline_horizon_snapshot_fusion_available_leak(repo_index):
    offenders: list[str] = []
    for rel, src in _iter_production_py(repo_index):
        if rel == _MHMLB_FILE:
            if "horizon_fusion_available" not in src:
                offenders.append(f"{rel}: missing horizon_fusion_available field")
            if re.search(r"\bfusion_available\s*:", src):
                offenders.append(f"{rel}: legacy fusion_available field name")
            continue
        for i, line in enumerate(src.splitlines(), start=1):
            if _PER_HORIZON_FUSION_AVAILABLE_LEAK.search(line):
                offenders.append(f"{rel}:{i}:{line.strip()}")
    assert offenders == []
