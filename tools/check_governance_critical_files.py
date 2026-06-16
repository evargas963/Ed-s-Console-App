#!/usr/bin/env python3
"""Verify governance-critical paths exist and are covered by CODEOWNERS.

Wired into run_repo_wide_static_audit() → enforce_all_rules.py --objective-audit
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

GOVERNANCE_CRITICAL_DOC = "governance/docs/GOVERNANCE_CRITICAL_FILES.md"
GOVERNANCE_CRITICAL_ARTIFACT = "governance/artifacts/GOVERNANCE_CRITICAL_FILES.json"

# Canonical protection model — every entry must exist on disk and have CODEOWNERS coverage.
GOVERNANCE_CRITICAL_PATHS: tuple[str, ...] = (
    "AGENTS.md",
    "CLAUDE.md",
    ".cursor/rules",
    ".github/workflows",
    ".github/CODEOWNERS",
    "tools/enforce_all_rules.py",
    "governance",
    "tests/adversarial",
    "tests/decision_reconstruction",
    "tests/release_object",
    "tests/test_governance_consolidation.py",
    "tests/test_agent_preload_contract.py",
    "trade_impacting_gate.py",
    "live_decision_bundle.py",
    "decision_record.py",
    "override_registry.py",
    "server.py",
    "signals.py",
)

GOVERNANCE_CRITICAL_GLOBS: tuple[str, ...] = (
    "tools/check_*.py",
    "tools/_build_institutional_audit_*.py",
)


def _parse_codeowners_patterns() -> list[str]:
    path = REPO_ROOT / ".github" / "CODEOWNERS"
    if not path.is_file():
        return []
    patterns: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(line.split()[0])
    return patterns


def _codeowners_covers(rel_path: str, patterns: list[str]) -> bool:
    rel = rel_path.replace("\\", "/").lstrip("/")
    best_match = ""
    for pat in patterns:
        p = pat.lstrip("/")
        if p.endswith("/"):
            prefix = p.rstrip("/")
            if rel == prefix or rel.startswith(prefix + "/"):
                if len(p) > len(best_match):
                    best_match = p
        elif rel == p or rel.startswith(p + "/"):
            if len(p) > len(best_match):
                best_match = p
    return bool(best_match)


def _expand_glob_paths() -> list[str]:
    out: list[str] = []
    for pattern in GOVERNANCE_CRITICAL_GLOBS:
        for p in REPO_ROOT.glob(pattern):
            out.append(str(p.relative_to(REPO_ROOT)).replace("\\", "/"))
    return sorted(out)


def run_governance_critical_files_check() -> list[str]:
    errors: list[str] = []
    doc = REPO_ROOT / GOVERNANCE_CRITICAL_DOC
    if not doc.is_file():
        errors.append(f"{GOVERNANCE_CRITICAL_DOC}: missing")
    artifact = REPO_ROOT / GOVERNANCE_CRITICAL_ARTIFACT
    if not artifact.is_file():
        errors.append(f"{GOVERNANCE_CRITICAL_ARTIFACT}: missing — run tools/_build_institutional_audit_phase3d.py")

    patterns = _parse_codeowners_patterns()
    if not patterns:
        errors.append(".github/CODEOWNERS: missing or empty")

    all_paths = list(GOVERNANCE_CRITICAL_PATHS) + _expand_glob_paths()
    missing: list[str] = []
    uncovered: list[str] = []
    for rel in all_paths:
        full = REPO_ROOT / rel
        if not full.exists():
            missing.append(rel)
            continue
        if patterns and not _codeowners_covers(rel, patterns):
            uncovered.append(rel)

    if missing:
        errors.append(f"governance-critical paths missing on disk: {', '.join(missing[:8])}")
    if uncovered:
        errors.append(
            f"governance-critical paths without CODEOWNERS coverage: {', '.join(uncovered[:8])}"
        )
    if not any(
        p.lstrip("/").startswith("tools/check_") or p.startswith("/tools/")
        for p in patterns
    ):
        errors.append("CODEOWNERS: no tools/check_*.py pattern (governance checker surface)")
    return errors


def main() -> int:
    errors = run_governance_critical_files_check()
    if errors:
        for e in errors:
            print(f"check_governance_critical_files: {e}", file=sys.stderr)
        return 1
    print("check_governance_critical_files: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
