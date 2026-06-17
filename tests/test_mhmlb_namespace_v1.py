"""AUDIT-MHMLB-NAMESPACE: horizon_fusion_available rename guard (OBS-MHMLB-NS1)."""

from __future__ import annotations

import re
from pathlib import Path

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


def _iter_production_py(root: Path):
    for path in root.rglob("*.py"):
        rel = path.relative_to(root)
        if rel.parts and rel.parts[0] == "tests":
            continue
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        yield path, rel.as_posix()


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


def test_no_inline_horizon_snapshot_fusion_available_leak():
    root = Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    for path, rel in _iter_production_py(root):
        if rel == _MHMLB_FILE:
            src = path.read_text(encoding="utf-8", errors="replace")
            if "horizon_fusion_available" not in src:
                offenders.append(f"{rel}: missing horizon_fusion_available field")
            if re.search(r"\bfusion_available\s*:", src):
                offenders.append(f"{rel}: legacy fusion_available field name")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), start=1):
            if _PER_HORIZON_FUSION_AVAILABLE_LEAK.search(line):
                offenders.append(f"{rel}:{i}:{line.strip()}")
    assert offenders == []
