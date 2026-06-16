"""Governance artifact manifest integrity — current repo + tamper regression."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.governance_mutation_detection import (  # noqa: E402
    GOVERNANCE_ARTIFACT_PATHS,
    verify_governance_manifest,
    write_governance_manifest,
)


def test_governance_manifest_verifies_on_current_repo():
    result = verify_governance_manifest()
    assert result["ok"] is True, result
    assert result["tampered"] == []
    assert result["missing"] == []


def test_write_governance_manifest_refreshes_pins():
    manifest = write_governance_manifest()
    assert len(manifest.get("entries") or []) == len(GOVERNANCE_ARTIFACT_PATHS)
    assert verify_governance_manifest(manifest)["ok"] is True
