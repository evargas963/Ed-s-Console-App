"""Build Institutional Audit Phase 3D — external enforcement evidence.

Preserves REMOTE_ENFORCEMENT_EVIDENCE.json — does not wipe API verification on rebuild.

Run:
  python tools/verify_remote_enforcement.py --write-pending   # initial unverified state
  python tools/verify_remote_enforcement.py --fetch-github    # after operator configures GitHub
  python tools/_build_institutional_audit_phase3d.py
  python tools/enforce_all_rules.py --objective-audit
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ART = REPO / "governance" / "artifacts"
TODAY = date.today().isoformat()


def _run_pytest(paths: list[str]) -> dict:
    cmd = [sys.executable, "-m", "pytest", *paths, "-q"]
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    tail = (proc.stdout or proc.stderr or "").strip().splitlines()
    return {"exit_code": proc.returncode, "summary": tail[-1] if tail else "", "command": " ".join(cmd)}


def main() -> int:
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))

    from tools.check_governance_critical_files import (
        GOVERNANCE_CRITICAL_GLOBS,
        GOVERNANCE_CRITICAL_PATHS,
        _expand_glob_paths,
    )
    from tools.remote_enforcement_evidence import (
        build_phase3d_evidence_artifact,
        load_remote_evidence,
        write_all_artifacts,
    )

    ART.mkdir(parents=True, exist_ok=True)
    evidence = load_remote_evidence()

    p3d_tests = _run_pytest(
        [
            "tests/test_branch_protection_proof.py",
            "tests/test_required_status_checks.py",
            "tests/test_governance_critical_files.py",
            "tests/test_no_verify_resistance.py",
            "tests/test_governance_self_protection.py",
            "tests/test_remote_enforcement_evidence.py",
        ]
    )

    write_all_artifacts(evidence, generated=TODAY)

    crit = {
        "schema_version": 1,
        "artifact": "governance/artifacts/GOVERNANCE_CRITICAL_FILES.json",
        "generated": TODAY,
        "paths": list(GOVERNANCE_CRITICAL_PATHS),
        "globs": list(GOVERNANCE_CRITICAL_GLOBS),
        "expanded_glob_paths": _expand_glob_paths(),
        "count": len(GOVERNANCE_CRITICAL_PATHS) + len(_expand_glob_paths()),
    }
    (ART / "GOVERNANCE_CRITICAL_FILES.json").write_text(json.dumps(crit, indent=2) + "\n", encoding="utf-8")

    phase3d = build_phase3d_evidence_artifact(evidence, checker_tests=p3d_tests)
    phase3d["generated"] = TODAY
    (ART / "INSTITUTIONAL_AUDIT_PHASE3D_EVIDENCE.json").write_text(
        json.dumps(phase3d, indent=2) + "\n", encoding="utf-8"
    )

    print(
        f"wrote Phase 3D external={phase3d.get('external_enforcement_status')} "
        f"bp_verified={phase3d.get('branch_protection_verified')} "
        f"no_verify={phase3d.get('no_verify_status')} checker_tests={p3d_tests.get('exit_code')}"
    )
    return 0 if p3d_tests.get("exit_code") == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
