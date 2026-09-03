"""RC-509: governance/ holds ACTIVE SPECIFICATION and ACTIVE ENFORCEMENT — nothing else.

WHAT WAS MEASURED (2026-09-03, before the disposition). 106 tracked files, 23.7 MB, in which
the active governance core was under 2 MB. The rest was four other things filed at one
address: generated VENDOR DATA (the four Schwab CSV crosswalks alone were 17.1 MB), generated
EVIDENCE (governance/artifacts/**, governance/audits/**), PRODUCT ARCHITECTURE (the console
rebuild plan, the decision-engine framework, the stack-wiring map, the derived-analytics
registry, the route inventory, and the A1/A2/PILOT product contracts consumed by v2_decision),
and RESEARCH material. Eleven files were read by nothing at all.

A directory where the authority is 8% of the bytes cannot be reviewed as an authority: a
reader cannot tell what still governs from what was merely filed here.

THIS IS A CONTROL, NOT A NEW MECHANISM. It adds no gate, no hook, no registry and no
checker — it is a test, in the suite that already runs, asserting a property of a directory
that already exists. It is deliberately CATEGORICAL rather than a count: a file-count ceiling
would be the ratchet this repository has removed twice (RC-19, RC-280). What it forbids is a
KIND of thing returning, and every rule below names the owner that thing has instead.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _governance_files() -> list[str]:
    """Tracked governance/ paths, excluding archive/ (history, never authority)."""
    out = subprocess.run(["git", "ls-files", "governance"], cwd=str(ROOT),
                         capture_output=True, text=True, encoding="utf-8",
                         errors="replace").stdout.split()
    assert len(out) > 5, "governance/ discovery returned too little to be a real check"
    return [f for f in out if not f.startswith("governance/archive/")]


def test_no_generated_evidence_lives_in_the_governance_core():
    """Generated audit output and provenance dumps belong to reports/, the existing owner."""
    stray = [f for f in _governance_files()
             if f.startswith(("governance/artifacts/", "governance/audits/"))]
    assert stray == [], (
        "generated evidence is back in the governance core — it belongs under reports/: "
        + ", ".join(stray[:8]))


def test_no_research_material_lives_in_the_governance_core():
    """Experiments and their contracts belong to research/."""
    stray = [f for f in _governance_files() if f.startswith("governance/research/")]
    assert stray == [], (
        "research material is back in the governance core — it belongs under research/: "
        + ", ".join(stray[:8]))


def test_no_bulk_vendor_data_lives_in_the_governance_core():
    """The Schwab crosswalks are generated vendor DATA; schwab_field_inventory/ owns them.

    Guarded by SIZE and extension rather than by name, so the rule is about the KIND of
    artifact rather than about the specific files that were moved.
    """
    stray = []
    for f in _governance_files():
        p = ROOT / f
        if p.suffix.lower() in (".csv", ".tsv") and p.exists():
            stray.append(f)
        elif p.exists() and p.stat().st_size > 1_000_000 and p.name != "root_cause_log.md":
            stray.append(f"{f} ({p.stat().st_size // 1024} KB)")
    assert stray == [], (
        "bulk data is back in the governance core — vendor data belongs under "
        "schwab_field_inventory/, generated output under reports/: " + ", ".join(stray[:8]))


def test_every_governance_file_is_specification_or_enforcement():
    """The positive form: each surviving file is named, with what it IS.

    An allowlist here is honest where a count would not be — it forces a NEW file to declare
    which of the two kinds it is, and it fails loudly when something is added with neither.
    The entries are the active ledgers and registers, the active process specs, and the
    executable census that required-CI actually runs.
    """
    active_specification = {
        "governance/AGENT_OPERATING_PROCESS_V1.md",
        "governance/README.md",
        "governance/REHAB_PROGRAM.md",
        "governance/OPERATOR_DECISION_REGISTER.md",
        "governance/host_scheduled_jobs.md",
        "governance/agent_error_log.md",
    }
    active_ledgers_and_registers = {
        "governance/root_cause_log.md",
        "governance/unproven_register.md",
        "governance/retired_checks.md",
        "governance/decision_path_admissions.json",
        "governance/guard_applicability.json",
        "governance/computation_registry.json",
        "governance/level_faucets.json",
        "governance/ui_mockup_approvals.json",
        "governance/advisory_debt_baseline.json",
        "governance/INSTITUTIONAL_CLOSURE_SCHEMA.json",
        "governance/ML_CORRECTNESS_NOT_PROVEN_MATRIX_V2.json",
        "governance/ML_ITEM4_MIGRATION_POLICY.json",
        "governance/universal_fix_impact_manifest.json",
    }
    # The traceable-inventory census: 3,063 lines of executable enforcement driven by
    # tests/test_mega{1..4}_traceable_audit.py in required CI. PROVEN live 2026-09-02 by
    # injecting an uninventoried function, which failed the gate with "missing 1 def(s)".
    active_enforcement = {
        "governance/mega1_traceable_inventory.py",
        "governance/mega2_traceable_inventory.py",
        "governance/mega3_traceable_inventory.py",
        "governance/mega4_traceable_inventory.py",
        "governance/mega_chain_of_trust.py",
        "governance/CHAIN_OF_TRUST_ALLOWLIST.py",
        "governance/section_inventory_gate.py",
        "governance/traceable_derivation.py",
    }
    declared = active_specification | active_ledgers_and_registers | active_enforcement
    undeclared = sorted(set(_governance_files()) - declared)
    assert undeclared == [], (
        "a file arrived in the governance core without declaring which kind it is. If it is "
        "specification or enforcement, add it above; otherwise it belongs to reports/ "
        "(generated evidence), research/ (experiments), docs/ (product architecture and "
        "contracts) or its architectural owner: " + ", ".join(undeclared))
