"""Agent preload contract — mechanical verification of cross-agent operating surfaces."""
from __future__ import annotations

from pathlib import Path


from tools.check_agent_preload_contract import (
    CANONICAL_CONTRACT,
    PROOF_LABEL_LADDER_MARKERS,
    run_agent_preload_contract_check,
)


def test_agent_preload_contract_passes_on_current_repo() -> None:
    errors = run_agent_preload_contract_check()
    assert errors == [], f"preload contract: {errors}"


def test_agent_preload_contract_fails_when_opening_instruction_removed(tmp_path: Path) -> None:
    contract = tmp_path / "governance" / "docs" / "AGENT_OPERATING_CONTRACT.md"
    contract.parent.mkdir(parents=True)
    contract.write_text("# stub\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text(CANONICAL_CONTRACT + "\nDefinition of Done for Fixes\nexact failing test\n", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text(CANONICAL_CONTRACT + "\nBefore editing code, read and obey\n", encoding="utf-8")
    rules = tmp_path / ".cursor" / "rules"
    rules.mkdir(parents=True)
    for name in (
        "000-agent-operating-contract.mdc",
        "010-definition-of-done.mdc",
        "020-governance-maturity.mdc",
        "030-repo-neatness.mdc",
        "040-testing-and-artifacts.mdc",
        "050-proof-label-taxonomy.mdc",
    ):
        (rules / name).write_text("---\nalwaysApply: true\n---\n" + CANONICAL_CONTRACT + "\n", encoding="utf-8")
    (rules / "00-always.mdc").write_text(CANONICAL_CONTRACT, encoding="utf-8")
    import tools.check_agent_preload_contract as mod

    orig = mod.REPO_ROOT
    mod.REPO_ROOT = tmp_path
    try:
        errors = run_agent_preload_contract_check()
    finally:
        mod.REPO_ROOT = orig
    assert any("missing required marker" in e for e in errors)


def test_check_agent_preload_contract_cli_exit_zero() -> None:
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, "tools/check_agent_preload_contract.py"],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout


def test_proof_label_ladder_markers_required_in_contract(tmp_path: Path) -> None:
    contract = tmp_path / "governance" / "docs" / "AGENT_OPERATING_CONTRACT.md"
    contract.parent.mkdir(parents=True)
    contract.write_text(
        "# stub\nBefore editing code, read and obey governance/docs/AGENT_OPERATING_CONTRACT.md\n"
        "not a patch generator\nSEVERITY_1_CONTROL_VALIDATION_REGISTER.json\n"
        "No maturity upgrade from implementation alone\nL5 requires adversarial proof\n"
        "Exact failing test status:\nRemaining Known Gaps:\nMaturity changes rejected:\n"
        "Preload improves\nnot institutional enforcement by itself\nRERUN EXACT\n"
        "fix incomplete because X\n",
        encoding="utf-8",
    )
    (tmp_path / "AGENTS.md").write_text(
        CANONICAL_CONTRACT + "\nDefinition of Done for Fixes\nexact failing test\n"
        "Proof-label ladder\nREPORTED_PROVEN_NOT_INDEPENDENTLY_VERIFIED\n"
        "evidence inputs, not absolute proof\n",
        encoding="utf-8",
    )
    (tmp_path / "CLAUDE.md").write_text(CANONICAL_CONTRACT + "\nBefore editing code, read and obey\n", encoding="utf-8")
    rules = tmp_path / ".cursor" / "rules"
    rules.mkdir(parents=True)
    for name in (
        "000-agent-operating-contract.mdc",
        "010-definition-of-done.mdc",
        "020-governance-maturity.mdc",
        "030-repo-neatness.mdc",
        "040-testing-and-artifacts.mdc",
        "050-proof-label-taxonomy.mdc",
    ):
        body = CANONICAL_CONTRACT + "\n"
        if name == "050-proof-label-taxonomy.mdc":
            body += "Proof-label ladder\nREPORTED_PROVEN_NOT_INDEPENDENTLY_VERIFIED\n"
            body += "evidence inputs, not absolute proof\n"
        (rules / name).write_text("---\nalwaysApply: true\n---\n" + body, encoding="utf-8")
    (rules / "00-always.mdc").write_text(CANONICAL_CONTRACT, encoding="utf-8")
    import tools.check_agent_preload_contract as mod

    orig = mod.REPO_ROOT
    mod.REPO_ROOT = tmp_path
    try:
        errors = run_agent_preload_contract_check()
    finally:
        mod.REPO_ROOT = orig
    assert any("Proof-label ladder" in e for e in errors)


def test_proof_label_ladder_markers_present_on_current_contract() -> None:
    contract = Path(__file__).resolve().parent.parent / CANONICAL_CONTRACT
    text = contract.read_text(encoding="utf-8")
    missing = [m for m in PROOF_LABEL_LADDER_MARKERS if m not in text]
    assert missing == [], f"missing proof-label markers: {missing}"
