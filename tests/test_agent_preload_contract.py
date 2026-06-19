"""Agent preload contract — mechanical verification of cross-agent operating surfaces."""
from __future__ import annotations

from pathlib import Path


from tools.check_agent_preload_contract import (
    CANONICAL_CONTRACT,
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
