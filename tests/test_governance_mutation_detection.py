"""Governance artifact manifest integrity — cross-platform hash + non-mutation."""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.governance_mutation_detection import (  # noqa: E402
    GOVERNANCE_ARTIFACT_PATHS,
    _governance_artifact_bytes,
    verify_governance_manifest,
)


def test_governance_manifest_verifies_on_current_repo():
    result = verify_governance_manifest()
    assert result["ok"] is True, result
    assert result["tampered"] == []
    assert result["missing"] == []


def test_write_governance_manifest_refreshes_pins(tmp_path, monkeypatch):
    """Refresh pins in an isolated manifest — must not touch tracked GOVERNANCE_ARTIFACT_MANIFEST.json."""
    from tools import governance_mutation_detection as gmd

    real_manifest = REPO / "governance/artifacts/GOVERNANCE_ARTIFACT_MANIFEST.json"
    before_bytes = real_manifest.read_bytes()

    art = tmp_path / "governance" / "artifacts"
    art.mkdir(parents=True)
    for rel in gmd.GOVERNANCE_ARTIFACT_PATHS:
        sample = tmp_path / rel
        sample.parent.mkdir(parents=True, exist_ok=True)
        sample.write_bytes(b"{}\n")

    monkeypatch.setattr(gmd, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(gmd, "ART", art)
    monkeypatch.setattr(gmd, "MANIFEST_PATH", art / "GOVERNANCE_ARTIFACT_MANIFEST.json")

    manifest = gmd.write_governance_manifest()
    assert len(manifest.get("entries") or []) == len(gmd.GOVERNANCE_ARTIFACT_PATHS)
    assert gmd.verify_governance_manifest(manifest)["ok"] is True
    assert gmd.MANIFEST_PATH.is_file()
    assert real_manifest.read_bytes() == before_bytes


def test_manifest_hashes_match_git_head_lf_blobs():
    """Pins must match committed LF bytes (Linux CI checkout), not CRLF working tree."""
    import json

    manifest = json.loads(
        (REPO / "governance/artifacts/GOVERNANCE_ARTIFACT_MANIFEST.json").read_text(
            encoding="utf-8"
        )
    )
    stored = {e["path"]: e for e in manifest.get("entries") or [] if e.get("present")}
    for rel in GOVERNANCE_ARTIFACT_PATHS:
        git_bytes = subprocess.check_output(["git", "show", f"HEAD:{rel}"])
        git_sha = hashlib.sha256(git_bytes).hexdigest()
        assert stored[rel]["sha256"] == git_sha, rel


def test_crlf_working_tree_normalizes_to_git_head_hash(tmp_path, monkeypatch):
    from tools import governance_mutation_detection as gmd

    art = tmp_path / "governance" / "artifacts"
    art.mkdir(parents=True)
    rel = "governance/artifacts/UNIVERSAL_BYPASS_REGISTER.json"
    sample = art / "UNIVERSAL_BYPASS_REGISTER.json"
    sample.write_bytes(b'{"x": 1}\r\n')

    monkeypatch.setattr(gmd, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(gmd, "ART", art)
    monkeypatch.setattr(gmd, "MANIFEST_PATH", art / "GOVERNANCE_ARTIFACT_MANIFEST.json")
    monkeypatch.setattr(gmd, "GOVERNANCE_ARTIFACT_PATHS", (rel,))

    lf_sha = hashlib.sha256(b'{"x": 1}\n').hexdigest()
    manifest = gmd.build_governance_manifest()
    assert manifest["entries"][0]["sha256"] == lf_sha
    gmd.MANIFEST_PATH.write_bytes(
        (__import__("json").dumps(manifest, indent=2) + "\n").encode("utf-8")
    )
    assert gmd.verify_governance_manifest()["ok"] is True


def test_governance_artifact_bytes_helper_lf_only():
    p = REPO / GOVERNANCE_ARTIFACT_PATHS[0]
    git_bytes = subprocess.check_output(["git", "show", f"HEAD:{GOVERNANCE_ARTIFACT_PATHS[0]}"])
    assert _governance_artifact_bytes(p) == git_bytes


def test_objective_audit_bootstraps_empty_console_db(tmp_path, monkeypatch):
    """FIX_NOW: empty ED_CONSOLE_DB is in-scope for --objective-audit (schema bootstrap)."""
    import sqlite3

    from db import ensure_console_db_training_schema

    db = tmp_path / "empty_console.db"
    db.write_bytes(b"")
    monkeypatch.setenv("ED_CONSOLE_DB", str(db))
    monkeypatch.setenv("ED_CONSOLE_ALLOW_NONCANONICAL_DB", "1")
    ensure_console_db_training_schema(db)
    with sqlite3.connect(str(db)) as conn:
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='snapshots_1m_normalized'"
        ).fetchone()


# test_objective_audit_does_not_mutate_governance_artifacts was removed under the
# ED CONSOLE SLIMMING charter: it invoked the retired tools/enforce_all_rules.py
# (--objective-audit). The governance-manifest verify library exercised by the tests
# above still stands; the manifest subsystem's full retirement is Wave 2c (its only
# remaining referrers are the dead _build_evidence_index / _build_institutional_audit
# tools, not any live gate).
