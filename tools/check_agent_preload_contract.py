#!/usr/bin/env python3
"""Verify agent preload surfaces exist and contain required enforceable markers.

Canonical contract: governance/docs/AGENT_OPERATING_CONTRACT.md
Wired into: run_repo_wide_static_audit() → enforce_all_rules.py --objective-audit

Usage:
  python tools/check_agent_preload_contract.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

CANONICAL_CONTRACT = "governance/docs/AGENT_OPERATING_CONTRACT.md"
MATURITY_REGISTER = "governance/artifacts/SEVERITY_1_CONTROL_VALIDATION_REGISTER.json"

OPENING_INSTRUCTION = (
    "Before editing code, read and obey governance/docs/AGENT_OPERATING_CONTRACT.md"
)

PATCH_GENERATOR_RULE = "not a patch generator"

CURSOR_RULE_FILES: tuple[str, ...] = (
    "000-agent-operating-contract.mdc",
    "010-definition-of-done.mdc",
    "020-governance-maturity.mdc",
    "030-repo-neatness.mdc",
    "040-testing-and-artifacts.mdc",
    "050-proof-label-taxonomy.mdc",
)

PROOF_LABEL_LADDER_MARKERS: tuple[str, ...] = (
    "Proof-label ladder",
    "REPORTED_PROVEN_NOT_INDEPENDENTLY_VERIFIED",
    "LOCAL_GIT_VERIFIED",
    "PRE_PUSH_VERIFIED",
    "PUSHED_PROVEN",
    "REMOTE_CI_PROVEN",
    "CLOSED_WITH_EVIDENCE",
    "evidence inputs, not absolute proof",
    "downgrade immediately",
)

CONTRACT_MARKERS: tuple[str, ...] = (
    OPENING_INSTRUCTION,
    PATCH_GENERATOR_RULE,
    MATURITY_REGISTER,
    "SEVERITY_1_CONTROL_VALIDATION_REGISTER.json",
    "No maturity upgrade from implementation alone",
    "L5 requires adversarial proof",
    "Exact failing test status:",
    "Remaining Known Gaps:",
    "Maturity changes rejected:",
    "Preload improves",
    "not institutional enforcement by itself",
    "RERUN EXACT",
    "fix incomplete because X",
) + PROOF_LABEL_LADDER_MARKERS

AGENTS_MARKERS: tuple[str, ...] = (
    CANONICAL_CONTRACT,
    "Definition of Done for Fixes",
    "exact failing test",
    "Proof-label ladder",
    "REPORTED_PROVEN_NOT_INDEPENDENTLY_VERIFIED",
    "evidence inputs, not absolute proof",
)

CLAUDE_MARKERS: tuple[str, ...] = (
    CANONICAL_CONTRACT,
    OPENING_INSTRUCTION,
)

CURSOR_RULE_MARKERS: dict[str, tuple[str, ...]] = {
    "000-agent-operating-contract.mdc": (
        CANONICAL_CONTRACT,
        OPENING_INSTRUCTION,
        PATCH_GENERATOR_RULE,
        "SEVERITY_1_CONTROL_VALIDATION_REGISTER.json",
    ),
    "010-definition-of-done.mdc": (
        CANONICAL_CONTRACT,
        "exact failing test",
        "Rerun exact",
        PATCH_GENERATOR_RULE,
    ),
    "020-governance-maturity.mdc": (
        CANONICAL_CONTRACT,
        "No maturity upgrade from implementation alone",
        "L5 requires adversarial proof",
    ),
    "030-repo-neatness.mdc": (
        CANONICAL_CONTRACT,
        "No duplicate truth sources",
        "_build_institutional_audit_phase2.py",
    ),
    "040-testing-and-artifacts.mdc": (
        CANONICAL_CONTRACT,
        "check_agent_preload_contract.py",
        "objective-audit",
        "Exact failing test status:",
    ),
    "050-proof-label-taxonomy.mdc": (
        CANONICAL_CONTRACT,
        "Proof-label ladder",
        "REPORTED_PROVEN_NOT_INDEPENDENTLY_VERIFIED",
        "evidence inputs, not absolute proof",
    ),
}

FORBIDDEN_L5_CLAIMS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\ball controls (?:are )?at L5\b", re.I),
    re.compile(r"\bL5 institutional enforcement (?:is )?(?:complete|achieved|landed)\b", re.I),
    re.compile(r"\bvalidated_maturity[\"']?\s*:\s*[\"']L5[\"']", re.I),
)


def _read(rel: str) -> str:
    path = REPO_ROOT / rel.replace("/", "\\") if "\\" in rel else REPO_ROOT / rel
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _require_markers(text: str, markers: tuple[str, ...], *, label: str) -> list[str]:
    errors: list[str] = []
    for marker in markers:
        if marker not in text:
            errors.append(f"{label}: missing required marker {marker!r}")
    return errors


def _cursor_rule_always_apply(rel: str) -> list[str]:
    text = _read(rel)
    if not text:
        return [f"{rel}: missing"]
    if "alwaysApply: true" not in text:
        return [f"{rel}: must set alwaysApply: true for session preload"]
    return []


def _scan_forbidden_l5_claims(surfaces: list[tuple[str, str]]) -> list[str]:
    errors: list[str] = []
    for label, text in surfaces:
        for pat in FORBIDDEN_L5_CLAIMS:
            if pat.search(text):
                errors.append(
                    f"{label}: forbidden L5 claim without adversarial proof context — "
                    f"matched {pat.pattern!r}"
                )
    return errors


def run_agent_preload_contract_check() -> list[str]:
    """Return error strings; empty list means PASS."""
    errors: list[str] = []

    for rel in ("AGENTS.md", "CLAUDE.md", CANONICAL_CONTRACT):
        if not (REPO_ROOT / rel).is_file():
            errors.append(f"{rel}: missing (agent preload contract)")

    rules_dir = REPO_ROOT / ".cursor" / "rules"
    if not rules_dir.is_dir():
        errors.append(".cursor/rules/: missing directory")
    else:
        for name in CURSOR_RULE_FILES:
            rel = f".cursor/rules/{name}"
            if not (REPO_ROOT / rel).is_file():
                errors.append(f"{rel}: missing (required Cursor preload rule)")

    contract_text = _read(CANONICAL_CONTRACT)
    errors.extend(_require_markers(contract_text, CONTRACT_MARKERS, label=CANONICAL_CONTRACT))

    agents_text = _read("AGENTS.md")
    errors.extend(_require_markers(agents_text, AGENTS_MARKERS, label="AGENTS.md"))

    claude_text = _read("CLAUDE.md")
    errors.extend(_require_markers(claude_text, CLAUDE_MARKERS, label="CLAUDE.md"))

    always_mdc = _read(".cursor/rules/00-always.mdc")
    if always_mdc and CANONICAL_CONTRACT not in always_mdc:
        errors.append(".cursor/rules/00-always.mdc: must reference canonical AGENT_OPERATING_CONTRACT.md")

    for name in CURSOR_RULE_FILES:
        rel = f".cursor/rules/{name}"
        text = _read(rel)
        errors.extend(_cursor_rule_always_apply(rel))
        errors.extend(
            _require_markers(
                text,
                CURSOR_RULE_MARKERS.get(name, (CANONICAL_CONTRACT,)),
                label=rel,
            )
        )

    preload_surfaces: list[tuple[str, str]] = [
        (CANONICAL_CONTRACT, contract_text),
        ("AGENTS.md", agents_text),
        ("CLAUDE.md", claude_text),
    ]
    for name in CURSOR_RULE_FILES:
        preload_surfaces.append((f".cursor/rules/{name}", _read(f".cursor/rules/{name}")))
    errors.extend(_scan_forbidden_l5_claims(preload_surfaces))

    checker_self = REPO_ROOT / "tools" / "check_agent_preload_contract.py"
    if checker_self.is_file():
        ct = checker_self.read_text(encoding="utf-8", errors="replace")
        if "run_agent_preload_contract_check" not in ct:
            errors.append("tools/check_agent_preload_contract.py: missing run_agent_preload_contract_check()")
    else:
        errors.append("tools/check_agent_preload_contract.py: missing")

    test_path = REPO_ROOT / "tests" / "test_agent_preload_contract.py"
    if not test_path.is_file():
        errors.append("tests/test_agent_preload_contract.py: missing (paired test)")

    cft = _read("tools/check_fix_everything_we_touch.py")
    if "check_agent_preload_contract" not in cft:
        errors.append(
            "tools/check_fix_everything_we_touch.py: must wire check_agent_preload_contract "
            "into repo-wide static audit"
        )

    return errors


def main(argv: list[str] | None = None) -> int:
    _ = argv
    errors = run_agent_preload_contract_check()
    if errors:
        print("check_agent_preload_contract: FAIL\n- " + "\n- ".join(errors), file=sys.stderr)
        return 1
    print("check_agent_preload_contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
