#!/usr/bin/env python3
"""Pre-push fast gate — fail in seconds on dirty tree before expensive hooks.

Policy-only checks (hook order, docs) run in repo-wide static audit.
Working-tree cleanliness runs only when invoked as the pre-push hook entry.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
AUDIT_PATH = REPO / "governance" / "artifacts" / "PREPUSH_FAST_FAIL_AUDIT.json"
POLICY_MD = REPO / "governance" / "docs" / "PREPUSH_FAST_FAIL_POLICY.md"
PRE_COMMIT_CFG = REPO / ".pre-commit-config.yaml"

# Pre-push hooks must run in this order (YAML declaration order among pre-push stages).
# Repo-wide --full-static is NOT local pre-push — required CI objective-audit owns it.
EXPECTED_PREPUSH_HOOK_ORDER: tuple[str, ...] = (
    "prepush-fast-gate",
    "generated-artifacts-clean-check",
    "governance-consolidation-tests",
)

_FORBIDDEN_PREPUSH_HOOK_IDS: tuple[str, ...] = ("fix-everything-we-touch-full-static",)

# Consolidation hook must be pytest verification only — no artifact writers.
_CONSOLIDATION_FORBIDDEN_SUBSTRINGS: tuple[str, ...] = (
    "--write",
    "build_repo_hygiene_inventory.py",
    "build_check_stack_inventory.py",
    "audit_persistence_consumers.py",
    "audit_precommit_performance.py --write",
    "check_governance_generated_artifacts_clean.py --write",
)

_DIRTY_TREE_BUDGET_SEC = 5.0


def _parse_prepush_hook_ids(cfg_text: str) -> list[str]:
    """Return pre-push hook ids in YAML declaration order."""
    hooks: list[tuple[list[str], str]] = []
    current_stages: list[str] = ["pre-commit"]
    current_id: str | None = None
    for line in cfg_text.splitlines():
        m_id = re.match(r"\s*-\s*id:\s*(\S+)", line)
        if m_id:
            if current_id:
                hooks.append((current_stages, current_id))
            current_id = m_id.group(1)
            current_stages = ["pre-commit"]
            continue
        if current_id is None:
            continue
        m_stages = re.match(r"\s*stages:\s*\[(.+)\]", line)
        if m_stages:
            current_stages = [s.strip() for s in m_stages.group(1).split(",")]
    if current_id:
        hooks.append((current_stages, current_id))
    return [hid for stages, hid in hooks if "pre-push" in stages]


def _consolidation_hook_entry(cfg_text: str) -> str | None:
    idx = cfg_text.find("id: governance-consolidation-tests")
    if idx < 0:
        return None
    rest = cfg_text[idx:]
    next_hook = rest.find("\n      - id:", len("id: governance-consolidation-tests"))
    block = rest if next_hook < 0 else rest[:next_hook]
    m = re.search(r"entry:\s*(.+)", block)
    return m.group(1).strip() if m else None


def check_prepush_no_full_static_hook() -> list[str]:
    """Local pre-push must not run repo-wide --full-static (CI objective-audit owns it)."""
    errors: list[str] = []
    if not PRE_COMMIT_CFG.is_file():
        return errors
    cfg = PRE_COMMIT_CFG.read_text(encoding="utf-8", errors="replace")
    order = _parse_prepush_hook_ids(cfg)
    for forbidden in _FORBIDDEN_PREPUSH_HOOK_IDS:
        if forbidden in order:
            errors.append(
                f".pre-commit-config.yaml: {forbidden!r} must not run on pre-push "
                f"(repo-wide static → required CI objective-audit)"
            )
    wf = REPO / ".github" / "workflows" / "objective-audit.yml"
    if wf.is_file():
        wf_text = wf.read_text(encoding="utf-8", errors="replace")
        if "--objective-audit" not in wf_text:
            errors.append(
                ".github/workflows/objective-audit.yml: missing --objective-audit "
                "(required CI full-repo static authority)"
            )
    else:
        errors.append(".github/workflows/objective-audit.yml: missing")
    return errors


def check_prepush_hook_order() -> list[str]:
    errors: list[str] = []
    if not PRE_COMMIT_CFG.is_file():
        return [".pre-commit-config.yaml: missing"]
    cfg = PRE_COMMIT_CFG.read_text(encoding="utf-8", errors="replace")
    order = _parse_prepush_hook_ids(cfg)
    if not order:
        errors.append(".pre-commit-config.yaml: no pre-push hooks declared")
        return errors
    expected = list(EXPECTED_PREPUSH_HOOK_ORDER)
    if order[: len(expected)] != expected:
        errors.append(
            "pre-push hook order must be "
            f"{expected!r} first — got {order!r}"
        )
    errors.extend(check_prepush_no_full_static_hook())
    return errors


def check_consolidation_entry_check_only() -> list[str]:
    """Governance consolidation pre-push entry must be pytest-only (no writers)."""
    errors: list[str] = []
    if not PRE_COMMIT_CFG.is_file():
        return errors
    cfg = PRE_COMMIT_CFG.read_text(encoding="utf-8", errors="replace")
    entry = _consolidation_hook_entry(cfg)
    if not entry:
        errors.append(".pre-commit-config.yaml: governance-consolidation-tests entry missing")
        return errors
    if "pytest" not in entry:
        errors.append(
            "governance-consolidation-tests: entry must invoke pytest (check-only verification)"
        )
    for bad in _CONSOLIDATION_FORBIDDEN_SUBSTRINGS:
        if bad in entry:
            errors.append(
                f"governance-consolidation-tests: forbidden mutating token {bad!r} in entry"
            )
    return errors


def check_prepush_fast_fail_policy_artifacts() -> list[str]:
    errors: list[str] = []
    if not POLICY_MD.is_file():
        errors.append(f"{POLICY_MD.relative_to(REPO).as_posix()}: missing")
    if not AUDIT_PATH.is_file():
        errors.append(f"{AUDIT_PATH.relative_to(REPO).as_posix()}: missing")
        return errors
    try:
        audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"PREPUSH_FAST_FAIL_AUDIT.json: unreadable ({exc})")
        return errors
    if audit.get("schema_version") != 1:
        errors.append("PREPUSH_FAST_FAIL_AUDIT.json: schema_version must be 1")
    if list(audit.get("expected_prepush_hook_order") or []) != list(EXPECTED_PREPUSH_HOOK_ORDER):
        errors.append("PREPUSH_FAST_FAIL_AUDIT.json: expected_prepush_hook_order mismatch")
    return errors


def check_prepush_fast_gate_policy() -> list[str]:
    """Static policy wiring — safe for objective-audit (no dirty-tree probe)."""
    errors: list[str] = []
    errors.extend(check_prepush_hook_order())
    errors.extend(check_consolidation_entry_check_only())
    errors.extend(check_prepush_fast_fail_policy_artifacts())
    return errors


def check_working_tree_clean_for_push(*, repo: Path | None = None) -> list[str]:
    """Fail fast when tracked or untracked (non-ignored) changes exist."""
    root = repo or REPO
    start = time.perf_counter()
    errors: list[str] = []
    try:
        # Tracked modifications (staged + unstaged)
        idx = subprocess.run(
            ["git", "diff-index", "--quiet", "HEAD", "--"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        cached = subprocess.run(
            ["git", "diff-index", "--quiet", "--cached", "HEAD", "--"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if idx.returncode != 0 or cached.returncode != 0:
            status = subprocess.run(
                ["git", "status", "--short"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )
            sample = (status.stdout or "").strip().splitlines()[:8]
            errors.append(
                "pre-push fast gate: working tree is dirty — commit or stash before push. "
                f"Sample: {sample!r}"
            )
        # Non-ignored untracked files (gitignore respected)
        untracked = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=normal"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if untracked.returncode == 0:
            extra = [
                ln[3:].strip()
                for ln in (untracked.stdout or "").splitlines()
                if ln.startswith("??")
            ]
            if extra:
                errors.append(
                    "pre-push fast gate: untracked non-ignored files present — "
                    f"commit, gitignore, or remove before push. Sample: {extra[:8]!r}"
                )
    except OSError as exc:
        errors.append(f"pre-push fast gate: git unavailable ({exc})")
    elapsed = time.perf_counter() - start
    if elapsed > _DIRTY_TREE_BUDGET_SEC and not errors:
        errors.append(
            f"pre-push fast gate: dirty-tree probe exceeded {_DIRTY_TREE_BUDGET_SEC}s budget "
            f"({elapsed:.2f}s)"
        )
    return errors


def check_prepush_fast_gate(*, enforce_clean_tree: bool = False) -> list[str]:
    errors = check_prepush_fast_gate_policy()
    if enforce_clean_tree:
        errors.extend(check_working_tree_clean_for_push())
    return errors


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    enforce_clean = True
    if args and args[0] == "--policy-only":
        enforce_clean = False
        args = args[1:]
    if args:
        print(f"check_prepush_fast_gate: unknown args {args!r}", file=sys.stderr)
        return 2
    errs = check_prepush_fast_gate(enforce_clean_tree=enforce_clean)
    if errs:
        print("check_prepush_fast_gate: FAIL\n- " + "\n- ".join(errs))
        return 1
    label = "PASS (clean tree)" if enforce_clean else "PASS (policy)"
    print(f"check_prepush_fast_gate: {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
