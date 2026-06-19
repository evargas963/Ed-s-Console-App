#!/usr/bin/env python3
"""Build governance evidence index — Phase 3F reviewer traceability."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ART = REPO / "governance" / "artifacts"
JSON_PATH = ART / "EVIDENCE_INDEX.json"
MD_PATH = REPO / "governance" / "artifacts" / "EVIDENCE_INDEX.md"
TODAY = date.today().isoformat()

# claim_id → row (verdict must stay honest — no L5 without external + adversarial proof)
EVIDENCE_CLAIMS: tuple[dict, ...] = (
    {
        "claim_id": "agent_preload",
        "claim": "Agent preload contract exists and is mechanically checked",
        "verdict": "proven",
        "evidence_artifact": "governance/docs/AGENT_OPERATING_CONTRACT.md",
        "code_path": "tools/check_agent_preload_contract.py",
        "test_path": "tests/test_agent_preload_contract.py",
        "regenerate_command": "python tools/check_agent_preload_contract.py",
        "phase": "3A",
    },
    {
        "claim_id": "definition_of_done",
        "claim": "Closed-loop Definition of Done for fixes exists",
        "verdict": "proven",
        "evidence_artifact": "AGENTS.md (Definition of Done for Fixes)",
        "code_path": "tools/check_fix_everything_we_touch.py::check_definition_of_done_for_fixes_contract",
        "test_path": "tests/test_governance_consolidation.py::test_agents_closure_and_no_new_files_sections",
        "regenerate_command": "python tools/enforce_all_rules.py --objective-audit",
        "phase": "3A",
    },
    {
        "claim_id": "wrong_price_quarantine",
        "claim": "Wrong-but-finite spot prices are quarantined (I-28)",
        "verdict": "proven",
        "evidence_artifact": "governance/artifacts/INSTITUTIONAL_AUDIT_PHASE3B_EVIDENCE.json",
        "code_path": "trade_impacting_gate.py::assess_spot_price",
        "test_path": "tests/adversarial/test_wrong_price_quarantine.py",
        "regenerate_command": "python -m pytest tests/adversarial/test_wrong_price_quarantine.py -q",
        "phase": "3B",
    },
    {
        "claim_id": "r004_gated",
        "claim": "R-004 server._fetch_state production route is gated",
        "verdict": "proven",
        "evidence_artifact": "governance/artifacts/INSTITUTIONAL_AUDIT_PHASE3E_EVIDENCE.json",
        "code_path": "server.py::_finalize_production_decision",
        "test_path": "tests/adversarial/test_r004_live_path_gate.py",
        "regenerate_command": "python -m pytest tests/adversarial/test_r004_live_path_gate.py -q",
        "phase": "3E",
    },
    {
        "claim_id": "r005_blocked",
        "claim": "R-005 no_valid_expiry synthetic route blocked from production decision",
        "verdict": "proven",
        "evidence_artifact": "governance/artifacts/DECISION_PATH_REGISTRY.json",
        "code_path": "trade_impacting_gate.py::SYNTHETIC_NON_PRODUCTION_ROUTES",
        "test_path": "tests/adversarial/test_route_universality.py",
        "regenerate_command": "python -m pytest tests/adversarial/test_route_universality.py -q",
        "phase": "3B",
    },
    {
        "claim_id": "r010_cache_revalidated",
        "claim": "R-010 stale Tier C cache revalidated before serve",
        "verdict": "proven",
        "evidence_artifact": "governance/artifacts/DECISION_PATH_REGISTRY.json",
        "code_path": "trade_impacting_gate.py::revalidate_cached_decision",
        "test_path": "tests/adversarial/test_stale_cache_revalidation.py",
        "regenerate_command": "python -m pytest tests/adversarial/test_stale_cache_revalidation.py -q",
        "phase": "3B",
    },
    {
        "claim_id": "r017_override_registry",
        "claim": "R-017 prediction override requires registry when env allows",
        "verdict": "proven",
        "evidence_artifact": "governance/artifacts/DECISION_PATH_REGISTRY.json",
        "code_path": "override_registry.py",
        "test_path": "tests/adversarial/test_override_registry.py",
        "regenerate_command": "python -m pytest tests/adversarial/test_override_registry.py -q",
        "phase": "3B",
    },
    {
        "claim_id": "r031_non_production",
        "claim": "R-031 verify_model_outputs classified diagnostic_only — no production decision",
        "verdict": "proven",
        "evidence_artifact": "governance/artifacts/INSTITUTIONAL_AUDIT_PHASE3E_EVIDENCE.json",
        "code_path": "verify_model_outputs.py + trade_impacting_gate.py::resolve_fetch_state_decision_route",
        "test_path": "tests/adversarial/test_r031_cli_classification.py",
        "regenerate_command": "python -m pytest tests/adversarial/test_r031_cli_classification.py -q",
        "phase": "3E",
    },
    {
        "claim_id": "decision_reconstruction_live_path",
        "claim": "Decision reconstruction works for live-path simulation (not live Schwab)",
        "verdict": "partially_proven",
        "evidence_artifact": "governance/artifacts/INSTITUTIONAL_AUDIT_PHASE3E_EVIDENCE.json",
        "code_path": "decision_record.py::live_path_simulation_emission",
        "test_path": "tests/runtime_proof/test_live_path_decision_reconstruction.py",
        "regenerate_command": "python -m pytest tests/runtime_proof/test_live_path_decision_reconstruction.py -q",
        "phase": "3E",
        "limitation": "live_path_simulation — no live Schwab wire traffic",
    },
    {
        "claim_id": "decision_reconstruction_production_like",
        "claim": "Decision reconstruction works for production-like harness",
        "verdict": "partially_proven",
        "evidence_artifact": "governance/artifacts/INSTITUTIONAL_AUDIT_PHASE3C_EVIDENCE.json",
        "code_path": "decision_record.py::production_like_decision_emission",
        "test_path": "tests/adversarial/test_live_decision_record_reconstruction.py",
        "regenerate_command": "python -m pytest tests/adversarial/test_live_decision_record_reconstruction.py -q",
        "phase": "3C",
        "limitation": "production_like_harness — post-pipeline ms_dict only",
    },
    {
        "claim_id": "manual_mutation_detection",
        "claim": "Manual governance/decision artifact mutation is detectable (not prevented)",
        "verdict": "detected_not_prevented",
        "evidence_artifact": "governance/artifacts/GOVERNANCE_ARTIFACT_MANIFEST.json",
        "code_path": "tools/governance_mutation_detection.py",
        "test_path": "tests/governance_mutation/test_manual_mutation_detection.py",
        "regenerate_command": "python tools/_build_institutional_audit_phase3e.py",
        "phase": "3E",
    },
    {
        "claim_id": "env_override_inventory",
        "claim": "High-impact ED_* env overrides inventoried and gated in production serving context",
        "verdict": "proven",
        "evidence_artifact": "governance/artifacts/ENV_OVERRIDE_INVENTORY.json",
        "code_path": "tools/check_env_override_hardening.py",
        "test_path": "tests/runtime_proof/test_env_override_hardening.py",
        "regenerate_command": "python tools/_build_institutional_audit_phase3e.py",
        "phase": "3E",
    },
    {
        "claim_id": "github_external_enforcement",
        "claim": "GitHub branch protection + required check objective-audit",
        "verdict": "required_not_proven",
        "evidence_artifact": "governance/artifacts/REMOTE_ENFORCEMENT_EVIDENCE.json",
        "code_path": ".github/workflows/objective-audit.yml + tools/verify_remote_enforcement.py",
        "test_path": "tests/test_remote_enforcement_evidence.py",
        "regenerate_command": "python tools/verify_remote_enforcement.py --fetch-github",
        "phase": "3D",
        "limitation": "verified=false until GitHub API/CLI evidence",
    },
    {
        "claim_id": "no_l5_claim",
        "claim": "No L5 institutional enforcement claim is made",
        "verdict": "explicitly_rejected",
        "evidence_artifact": "governance/artifacts/SEVERITY_1_CONTROL_VALIDATION_REGISTER.json",
        "code_path": "governance/artifacts/MATURITY_PROMOTION_RULES.json",
        "test_path": "tests/test_reviewer_evidence_index.py::test_no_l5_claims_in_evidence_index",
        "regenerate_command": "python tools/_build_evidence_index.py",
        "phase": "3F",
    },
    {
        "claim_id": "universal_enforcement",
        "claim": "Universal route enforcement across all trade-impacting paths",
        "verdict": "explicitly_rejected",
        "evidence_artifact": "governance/artifacts/DECISION_PATH_REGISTRY.json",
        "code_path": "trade_impacting_gate.py (partial priority routes only)",
        "test_path": "tests/adversarial/test_bypass_register_reconciliation.py",
        "regenerate_command": "python tools/_build_institutional_audit_phase3c.py",
        "phase": "3C",
    },
    {
        "claim_id": "live_schwab_traffic",
        "claim": "Live Schwab _fetch_state traffic emits reconstructable production decisions",
        "verdict": "unproven",
        "evidence_artifact": "governance/artifacts/CURRENT_LIMITATIONS.json",
        "code_path": "server.py::_fetch_state (requires Schwab credentials)",
        "test_path": None,
        "regenerate_command": "python tools/live_diag_compare.py SPY (operator host with Schwab auth)",
        "phase": "3E",
        "limitation": "Requires live Schwab credentials and serving host",
    },
)

PROVEN_VERDICTS = frozenset({"proven", "partially_proven", "detected_not_prevented"})
REJECTED_VERDICTS = frozenset({"explicitly_rejected", "required_not_proven", "unproven"})


def build_evidence_index(*, generated: str | None = None) -> dict:
    gen = generated or TODAY
    return {
        "schema_version": 1,
        "artifact": "governance/artifacts/EVIDENCE_INDEX.json",
        "generated": gen,
        "maturity_truth_source": "governance/artifacts/SEVERITY_1_CONTROL_VALIDATION_REGISTER.json",
        "reviewer_entry_point": "governance/REVIEWER_README.md",
        "claim_count": len(EVIDENCE_CLAIMS),
        "claims": list(EVIDENCE_CLAIMS),
    }


def render_evidence_index_md(data: dict) -> str:
    lines = [
        "> **Classification:** Operational Ledger | **Scope:** Phase 3F generated evidence index — claim traceability, not maturity proof.",
        "",
        "# Governance evidence index",
        "",
        f"**Generated:** {data.get('generated')}  ",
        "**Purpose:** Map claims → artifacts → code → tests → reproduction commands.",
        "",
        "| Claim | Verdict | Evidence | Code | Test | Reproduce |",
        "|-------|---------|----------|------|------|-----------|",
    ]
    for c in data.get("claims") or []:
        test = c.get("test_path") or "—"
        lim = c.get("limitation")
        claim = c["claim"]
        if lim:
            claim = f"{claim} (*{lim}*)"
        lines.append(
            f"| {claim} | `{c['verdict']}` | `{c['evidence_artifact']}` | "
            f"`{c['code_path']}` | `{test}` | `{c['regenerate_command']}` |"
        )
    lines.extend(
        [
            "",
            "## Verdict vocabulary",
            "",
            "- **proven** — code + test evidence; reproducible",
            "- **partially_proven** — honest limitation labeled",
            "- **detected_not_prevented** — visibility only",
            "- **required_not_proven** — spec/CI exists; external proof missing",
            "- **unproven** — gap acknowledged",
            "- **explicitly_rejected** — claim must not be made",
            "",
            "Regenerate: `python tools/_build_evidence_index.py`",
            "",
        ]
    )
    return "\n".join(lines)


def write_evidence_index(*, generated: str | None = None) -> dict:
    ART.mkdir(parents=True, exist_ok=True)
    data = build_evidence_index(generated=generated)
    JSON_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    MD_PATH.write_text(render_evidence_index_md(data), encoding="utf-8")
    return data


def main() -> int:
    data = write_evidence_index()
    print(f"wrote {JSON_PATH.name} ({data['claim_count']} claims) + EVIDENCE_INDEX.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
