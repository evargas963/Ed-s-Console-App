#!/usr/bin/env python3
"""Build current limitations index — Phase 3F honest gap surface."""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ART = REPO / "governance" / "artifacts"
JSON_PATH = ART / "CURRENT_LIMITATIONS.json"
MD_PATH = REPO / "governance" / "CURRENT_LIMITATIONS.md"
TODAY = date.today().isoformat()

REQUIRED_LIMITATION_IDS: frozenset[str] = frozenset(
    {
        "live_schwab_proof",
        "github_branch_protection",
        "required_status_checks",
        "no_verify_external",
        "manual_mutation_detection_only",
        "r012_route_gap",
        "l5_not_claimed",
    }
)

LIMITATIONS: tuple[dict, ...] = (
    {
        "limitation_id": "live_schwab_proof",
        "title": "Live Schwab traffic proof missing",
        "status": "unproven",
        "honest_label": "live_schwab",
        "detail": "Decision proof uses live_path_simulation and production_like_harness — not live Schwab wire _fetch_state traffic.",
        "evidence_artifact": "governance/artifacts/INSTITUTIONAL_AUDIT_PHASE3E_EVIDENCE.json",
        "next_action": "Operator host with Schwab auth: capture production decision from live _fetch_state and blind-reconstruct.",
    },
    {
        "limitation_id": "github_branch_protection",
        "title": "GitHub branch protection not API-verified",
        "status": "required_not_proven",
        "honest_label": "external_enforcement",
        "detail": "CI workflow objective-audit exists locally; branch_protection.verified=false in REMOTE_ENFORCEMENT_EVIDENCE.json.",
        "evidence_artifact": "governance/artifacts/REMOTE_ENFORCEMENT_EVIDENCE.json",
        "next_action": "Configure GitHub protection on main OR run python tools/verify_remote_enforcement.py --fetch-github on authenticated machine.",
    },
    {
        "limitation_id": "required_status_checks",
        "title": "Required GitHub status check not enforced until protection configured",
        "status": "required_not_proven",
        "honest_label": "objective-audit check name locked in repo only",
        "detail": "Job name objective-audit must appear in GitHub branch protection after workflow runs once on main.",
        "evidence_artifact": "governance/artifacts/REQUIRED_STATUS_CHECKS.json",
        "next_action": "Push workflow, run on main, add objective-audit as required check in GitHub Settings.",
    },
    {
        "limitation_id": "no_verify_external",
        "title": "git commit --no-verify bypass",
        "status": "external_required",
        "honest_label": "no_verify open",
        "detail": "Pre-commit can be bypassed locally; mitigation requires GitHub required checks + PR review.",
        "evidence_artifact": "governance/artifacts/NO_VERIFY_RESISTANCE.json",
        "next_action": "GitHub branch protection with required check objective-audit.",
    },
    {
        "limitation_id": "manual_mutation_detection_only",
        "title": "Manual DB/filesystem mutation detected not prevented",
        "status": "detected_not_prevented",
        "honest_label": "mutation visibility only",
        "detail": "Governance artifact manifest and decision-record integrity scan detect tampering; no immutability gate on sqlite/filesystem.",
        "evidence_artifact": "governance/artifacts/GOVERNANCE_ARTIFACT_MANIFEST.json",
        "next_action": "Phase beyond 3F if prevention required (external storage, append-only audit).",
    },
    {
        "limitation_id": "r012_route_gap",
        "title": "R-012 GET /api/live/state Tier A still gapped",
        "status": "unproven",
        "honest_label": "route gap",
        "detail": "Tier A live state path does not invoke full build_market_state / mandatory controls.",
        "evidence_artifact": "governance/artifacts/DECISION_PATH_REGISTRY.json",
        "next_action": "Dedicated R-012 adversarial proof or non-production classification with evidence.",
    },
    {
        "limitation_id": "l5_not_claimed",
        "title": "L5 institutional enforcement not claimed",
        "status": "explicitly_rejected",
        "honest_label": "no L5",
        "detail": "No control demonstrates L5 (four-eyes + immutable audit + adversarial bypass survival + external proof).",
        "evidence_artifact": "governance/artifacts/SEVERITY_1_CONTROL_VALIDATION_REGISTER.json",
        "next_action": "Do not promote maturity without MATURITY_PROMOTION_RULES.json criteria met.",
    },
    {
        "limitation_id": "universal_enforcement",
        "title": "Universal route enforcement not claimed",
        "status": "explicitly_rejected",
        "honest_label": "partial priority-route enforcement",
        "detail": "69 bypass paths still open in UNIVERSAL_BYPASS_REGISTER.json; route universality proven=false.",
        "evidence_artifact": "governance/artifacts/UNIVERSAL_BYPASS_REGISTER.json",
        "next_action": "Evidence-backed bypass reduction only — no cosmetic count changes.",
    },
)


def build_current_limitations(*, generated: str | None = None) -> dict:
    return {
        "schema_version": 1,
        "artifact": "governance/artifacts/CURRENT_LIMITATIONS.json",
        "generated": generated or TODAY,
        "limitation_count": len(LIMITATIONS),
        "required_limitation_ids": sorted(REQUIRED_LIMITATION_IDS),
        "limitations": list(LIMITATIONS),
        "maturity_changes_proposed": [],
        "maturity_changes_rejected": [
            "L5 institutional enforcement",
            "Universal enforcement",
            "Remote GitHub enforcement verified without API evidence",
            "Live Schwab proof from simulation harness",
        ],
    }


def render_limitations_md(data: dict) -> str:
    lines = [
        "> **Classification:** Operational Ledger | **Scope:** Phase 3F honest limitations — open gaps only.",
        "",
        "# Current limitations (honest gaps)",
        "",
        f"**Generated:** {data.get('generated')}  ",
        "This file lists what is **not** proven. Do not infer maturity from green local CI alone.",
        "",
        "| ID | Title | Status | Next action |",
        "|----|-------|--------|-------------|",
    ]
    for lim in data.get("limitations") or []:
        lines.append(
            f"| `{lim['limitation_id']}` | {lim['title']} | `{lim['status']}` | {lim['next_action']} |"
        )
    lines.extend(
        [
            "",
            "## Required gaps (checker-enforced)",
            "",
            ", ".join(f"`{x}`" for x in sorted(REQUIRED_LIMITATION_IDS)),
            "",
            "Regenerate: `python tools/_build_current_limitations.py`",
            "",
        ]
    )
    return "\n".join(lines)


def write_current_limitations(*, generated: str | None = None) -> dict:
    ART.mkdir(parents=True, exist_ok=True)
    data = build_current_limitations(generated=generated)
    JSON_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    MD_PATH.write_text(render_limitations_md(data), encoding="utf-8")
    return data


def main() -> int:
    data = write_current_limitations()
    print(f"wrote CURRENT_LIMITATIONS.json ({data['limitation_count']} items) + CURRENT_LIMITATIONS.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
