"""Governance + decision artifact mutation detection — Phase 3E.

Detection only — does not prevent local filesystem/DB mutation.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
ART = REPO_ROOT / "governance" / "artifacts"
MANIFEST_PATH = ART / "GOVERNANCE_ARTIFACT_MANIFEST.json"

GOVERNANCE_ARTIFACT_PATHS: tuple[str, ...] = (
    "governance/artifacts/UNIVERSAL_BYPASS_REGISTER.json",
    "governance/artifacts/DECISION_PATH_REGISTRY.json",
    "governance/artifacts/REMOTE_ENFORCEMENT_EVIDENCE.json",
    "governance/artifacts/INSTITUTIONAL_AUDIT_PHASE3D_EVIDENCE.json",
    "governance/artifacts/INSTITUTIONAL_AUDIT_PHASE3C_EVIDENCE.json",
    "governance/artifacts/GOVERNANCE_MUTATION_AUDIT.json",
    "governance/artifacts/RUNTIME_MUTATION_REGISTER.json",
)

# Manifest pins use LF-normalized bytes for governance/artifacts/*.json so Windows
# working-tree CRLF and Linux CI checkout (git eol=lf) produce identical SHA256.
_GOVERNANCE_JSON_PREFIX = "governance/artifacts/"


def _governance_artifact_bytes(path: Path) -> bytes:
    data = path.read_bytes()
    rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    if rel.startswith(_GOVERNANCE_JSON_PREFIX) and path.suffix == ".json":
        data = data.replace(b"\r\n", b"\n")
    return data


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(_governance_artifact_bytes(path)).hexdigest()


def build_governance_manifest(*, generated_by: str = "tools/governance_mutation_detection.py") -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for rel in GOVERNANCE_ARTIFACT_PATHS:
        p = REPO_ROOT / rel
        if not p.is_file():
            entries.append({"path": rel, "present": False, "sha256": None})
            continue
        norm = _governance_artifact_bytes(p)
        entries.append(
            {
                "path": rel,
                "present": True,
                "sha256": hashlib.sha256(norm).hexdigest(),
                "size_bytes": len(norm),
            }
        )
    return {
        "schema_version": 1,
        "artifact": str(MANIFEST_PATH.relative_to(REPO_ROOT)).replace("\\", "/"),
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "generated_by": generated_by,
        "entries": entries,
    }


def verify_governance_manifest(manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compare on-disk governance artifacts to stored manifest; report tampering."""
    if manifest is None:
        if not MANIFEST_PATH.is_file():
            return {"ok": False, "reason": "manifest_missing", "tampered": [], "missing": []}
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    stored = {e["path"]: e for e in manifest.get("entries") or [] if isinstance(e, dict)}
    tampered: list[str] = []
    missing: list[str] = []
    for rel in GOVERNANCE_ARTIFACT_PATHS:
        p = REPO_ROOT / rel
        rec = stored.get(rel)
        if not p.is_file():
            if rec and rec.get("present"):
                missing.append(rel)
            continue
        current = _sha256_file(p)
        if not rec or not rec.get("present"):
            tampered.append(rel)
            continue
        if str(rec.get("sha256") or "") != current:
            tampered.append(rel)
    return {
        "ok": not tampered and not missing,
        "tampered": tampered,
        "missing": missing,
        "checked_count": len(GOVERNANCE_ARTIFACT_PATHS),
    }


def verify_decision_record_integrity(db_path: Path | str) -> dict[str, Any]:
    """Detect decision rows whose reconstruction_json fails schema completeness."""
    from decision_record import ensure_production_decision_schema, reconstruction_complete

    path = Path(db_path)
    if not path.is_file():
        return {"ok": True, "rows_checked": 0, "incomplete": []}
    conn = sqlite3.connect(str(path), timeout=30.0)
    try:
        ensure_production_decision_schema(conn)
        rows = conn.execute(
            "SELECT decision_id, reconstruction_json FROM production_decision_records"
        ).fetchall()
    finally:
        conn.close()
    incomplete: list[str] = []
    for did, raw in rows:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            incomplete.append(f"{did}:invalid_json")
            continue
        ok, missing = reconstruction_complete(payload)
        if not ok:
            incomplete.append(f"{did}:{','.join(missing)}")
    return {
        "ok": not incomplete,
        "rows_checked": len(rows),
        "incomplete": incomplete,
    }


def write_governance_manifest() -> dict[str, Any]:
    ART.mkdir(parents=True, exist_ok=True)
    manifest = build_governance_manifest()
    MANIFEST_PATH.write_bytes(
        (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Governance artifact manifest verify/write.")
    p.add_argument(
        "--write",
        action="store_true",
        help="Regenerate GOVERNANCE_ARTIFACT_MANIFEST.json from on-disk artifacts.",
    )
    args = p.parse_args(argv)
    if args.write:
        write_governance_manifest()
        return 0
    result = verify_governance_manifest()
    if not result.get("ok"):
        import sys

        sys.stderr.write(json.dumps(result, indent=2) + "\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
