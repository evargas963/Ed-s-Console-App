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
    _sha256_file,
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


def test_objective_audit_does_not_mutate_governance_artifacts():
    """enforce_all_rules --objective-audit is check-only for manifest-tracked JSON."""
    before = {rel: _sha256_file(REPO / rel) for rel in GOVERNANCE_ARTIFACT_PATHS}
    proc = subprocess.run(
        [sys.executable, "tools/enforce_all_rules.py", "--objective-audit"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    after = {rel: _sha256_file(REPO / rel) for rel in GOVERNANCE_ARTIFACT_PATHS}
    assert before == after
