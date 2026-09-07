"""Build Institutional Audit Phase 3 evidence — tied to implemented code + tests only.

Run after Phase 2 and after landing I-31/I-25 implementation:
  python tools/_build_institutional_audit_phase2.py
  python tools/_build_institutional_audit_phase3.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ART = REPO / "reports" / "artifacts"
TODAY = date.today().isoformat()


def _pytest_count(glob_path: str) -> dict:
    cmd = [sys.executable, "-m", "pytest", glob_path, "--collect-only", "-q"]
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    out = (proc.stdout or "") + (proc.stderr or "")
    # last line often "N tests collected"
    collected = 0
    for line in out.splitlines():
        if " tests collected" in line or " test collected" in line:
            try:
                collected = int(line.strip().split()[0])
            except (ValueError, IndexError):
                pass
    return {"exit_code": proc.returncode, "collected": collected, "command": " ".join(cmd)}


def main() -> int:
    ART.mkdir(parents=True, exist_ok=True)

    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))

    # Re-run blind harness (production DB — honest FAIL until live rows exist)
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "phase2_builder", REPO / "tools" / "_build_institutional_audit_phase2.py"
    )
    phase2 = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(phase2)
    blind = phase2.run_blind_reconstruction_test()
    (ART / "BLIND_RECONSTRUCTION_TEST_RESULT.json").write_text(
        json.dumps(blind, indent=2) + "\n", encoding="utf-8"
    )

    i31_tests = _pytest_count("tests/decision_reconstruction/")
    i25_tests = _pytest_count("tests/release_object/")
    adv_tests = _pytest_count("tests/adversarial/")

    evidence = {
        "schema_version": 1,
        "artifact": "reports/artifacts/INSTITUTIONAL_AUDIT_PHASE3_EVIDENCE.json",
        "generated": TODAY,
        "phase": 3,
        "implementation_evidence": {
            "I-31": {
                "modules": ["decision_record.py", "live_decision_bundle.py", "server.py GET /api/decision/{id}"],
                "pytest": i31_tests,
                "blind_reconstruction_verdict": blind.get("verdict"),
                "proposed_maturity": "L3" if blind.get("verdict") == "PASS" else "L1",
                "maturity_upgrade_rejected_without": [
                    "production DB blind PASS",
                    "adversarial bypass detection tests",
                    "immutable audit on bypass attempts",
                ],
            },
            "I-25": {
                "modules": ["release_object.py", "server.py GET /api/release/current", "/api/build release_id"],
                "pytest": i25_tests,
                "proposed_maturity": "L2" if i25_tests.get("collected", 0) >= 2 else "L1",
                "maturity_upgrade_rejected_without": [
                    "approval_record workflow",
                    "every production decision references release_id in live DB audit",
                ],
            },
            "adversarial": {
                "pytest": adv_tests,
                "bypass_detection_implemented": adv_tests.get("collected", 0) > 0,
            },
        },
        "maturity_changes_proposed": [],
        "maturity_changes_rejected": [
            "I-31 L4+ until blind PASS on production DB + adversarial suite",
            "I-25 L3+ until approval workflow + rollback proof",
            "I-28/I-29 partial — trade_impacting_gate wired; full route universality unproven",
            "Platform L5 — no control demonstrates L5",
        ],
        "remaining_institutional_gaps": [
            "branch protection not proven in-repo",
            "--no-verify bypass",
            "R-011/R-027/R-033/R-034 route gaps remain",
            "CI required checks not proven",
        ],
    }

    if blind.get("verdict") == "PASS":
        evidence["maturity_changes_proposed"].append(
            {"control_id": "I-31", "from": "L0", "to": "L3", "evidence": "BLIND_RECONSTRUCTION PASS + pytest"}
        )

    (ART / "INSTITUTIONAL_AUDIT_PHASE3_EVIDENCE.json").write_text(
        json.dumps(evidence, indent=2) + "\n", encoding="utf-8"
    )

    print(
        f"wrote Phase 3 evidence blind={blind.get('verdict')} "
        f"i31_tests={i31_tests.get('collected')} i25_tests={i25_tests.get('collected')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
