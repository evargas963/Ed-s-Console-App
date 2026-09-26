"""AUDIT-MHMLB-NAMESPACE: horizon_fusion_available rename guard (OBS-MHMLB-NS1)."""

from __future__ import annotations

import re


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
