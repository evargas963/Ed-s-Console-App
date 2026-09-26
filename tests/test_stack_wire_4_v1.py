"""STACK-WIRE-4 — contract + consumer-cone verification (FIND-WIRE4-1..4)."""

from __future__ import annotations

import re
from pathlib import Path


_CONSUMER_CONE = (
    "signals.py",
    "market_state.py",
    "call_engine.py",
    "prediction_engine.py",
    "mc_fusion_adjustment.py",
    "multi_horizon_decision.py",
    "multi_horizon_ml_bundle.py",
    "features/fusion_policy_contract.py",
    "v2_decision/a1_raw_probability.py",
    "v2_decision/module_a_adapter.py",
)

_BANNED_PROVENANCE = (
    r'provenance\s*==\s*["\']bayesian_fusion["\']',
    r'provenance\s*!=\s*["\']fusion_unavailable["\']',
)
# Fusion availability must use fusion_is_authoritative (same rule as test_fusion_contract).
_FUSION_AVAILABLE_GETATTR = re.compile(
    r"""getattr\s*\(\s*_?fusion\w*\s*,\s*['"]available['"]\s*""",
    re.IGNORECASE,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]










def test_classify_stack_health_single_producer(repo_index):
    """TEST_SYSTEM_REHAB_V2: sources from the shared `repo_index` corpus instead of an
    independent root.rglob("*.py")."""
    # scratchpad/ holds the RC-210 wipe-recovery copies (e.g. _server_RELANDED_20260802.py)
    # — preserved evidence, never production; counting them breaks single-producer scans.
    skip_dirs = {".git", ".venv", "venv", "node_modules", "__pycache__", "tests", ".claude",
                 "scratchpad"}
    call_sites: list[str] = []
    for rel, src, _tree in repo_index.items():
        if rel.parts and rel.parts[0] in skip_dirs:
            continue
        if any(part in skip_dirs for part in rel.parts):
            continue
        for i, line in enumerate(src.splitlines(), 1):
            if "classify_stack_health(" not in line:
                continue
            if "def classify_stack_health" in line:
                continue
            call_sites.append(f"{rel}:{i}")
    # Single-producer contract: exactly ONE production call site, and it lives in
    # server.py. The exact line is not pinned — line-number pins rot every time
    # server.py grows above the call site (2026-06-10: pin said 2084, site at 2614).
    assert len(call_sites) == 1, call_sites
    assert call_sites[0].startswith("server.py:"), call_sites
