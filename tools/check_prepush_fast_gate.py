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

# Local pre-push is LIGHTWEIGHT-ONLY (Phase 2B, 2026-06-26): fast gates only.
# Repo-wide --full-static is NOT local pre-push — required CI objective-audit owns it.
# The repo-wide governance consolidation pytest suite is NOT local pre-push either —
# required CI "pytest-full" (.github/workflows/pytest.yml) owns it. Measured: that
# suite is ~18-26 min (each candidate file 54-64s; bodies do repo-wide/app-importing
# scans), so it cannot live under the local pre-push budget below.
EXPECTED_PREPUSH_HOOK_ORDER: tuple[str, ...] = (
    "prepush-fast-gate",
    "generated-artifacts-clean-check",
)

# These hook ids must NOT appear on local pre-push — they are required-CI-owned.
_FORBIDDEN_PREPUSH_HOOK_IDS: tuple[str, ...] = (
    "fix-everything-we-touch-full-static",
    "governance-consolidation-tests",
)

# Local pre-push budget (hard ceiling / desired target). The lightweight gates above
# measure ~0.1-0.2s each plus a <5s dirty-tree probe — well inside these bounds.
PREPUSH_LOCAL_BUDGET_HARD_SEC = 60.0
PREPUSH_LOCAL_BUDGET_TARGET_SEC = 30.0

# Any pre-push hook entry token matching these means a heavy / repo-wide / app-importing
# selection leaked back onto local pre-push (must be required-CI-owned instead).
_PREPUSH_FORBIDDEN_ENTRY_SUBSTRINGS: tuple[str, ...] = (
    "pytest",
    "tests/test_",
    "--full-static",
    "run_objective_code_audit",
    "passes_on_current_repo",
    "full_stack_ablation_coverage",
    "universal_code_quality_audit",
    "ablation_integrity_audit",
    "ablation_score_path_bias",
)

# Required-CI checks that back the heavy coverage moved off local pre-push.
_REQUIRED_CI_BACKING_CHECKS: tuple[str, ...] = (
    "objective-audit",
    "pytest-full",
    "hardening",
    "schwab-csv-first",
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


def _prepush_hook_entries(cfg_text: str) -> list[tuple[str, str]]:
    """Return (id, entry) for every pre-push-staged hook, declaration order."""
    rows: list[tuple[str, str]] = []
    current_id: str | None = None
    current_entry: str = ""
    current_stages: list[str] = ["pre-commit"]

    def _flush() -> None:
        if current_id and "pre-push" in current_stages:
            rows.append((current_id, current_entry))

    for line in cfg_text.splitlines():
        m_id = re.match(r"\s*-\s*id:\s*(\S+)", line)
        if m_id:
            _flush()
            current_id = m_id.group(1)
            current_entry = ""
            current_stages = ["pre-commit"]
            continue
        if current_id is None:
            continue
        m_entry = re.match(r"\s*entry:\s*(.+)", line)
        if m_entry:
            current_entry = m_entry.group(1).strip()
            continue
        m_stages = re.match(r"\s*stages:\s*\[(.+)\]", line)
        if m_stages:
            current_stages = [s.strip() for s in m_stages.group(1).split(",")]
    _flush()
    return rows


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


def check_prepush_lightweight_only() -> list[str]:
    """Local pre-push hooks must be lightweight only — no pytest / repo-wide selections.

    Phase 2B: the repo-wide governance consolidation pytest suite is required-CI-owned
    ("pytest-full"), not a local pre-push hook. Any pytest / test-file / repo-wide audit
    token on a pre-push entry means heavy coverage leaked back below the local budget.
    """
    errors: list[str] = []
    if not PRE_COMMIT_CFG.is_file():
        return errors
    cfg = PRE_COMMIT_CFG.read_text(encoding="utf-8", errors="replace")
    for hid, entry in _prepush_hook_entries(cfg):
        for bad in _PREPUSH_FORBIDDEN_ENTRY_SUBSTRINGS:
            if bad in entry:
                errors.append(
                    f"{hid}: pre-push entry contains heavy/repo-wide token {bad!r} — "
                    "local pre-push is lightweight-only; move it to required CI "
                    "(pytest-full / objective-audit)"
                )
    return errors


def check_required_ci_backing() -> list[str]:
    """The heavy coverage moved off local pre-push must be backed by required CI.

    pytest-full (.github/workflows/pytest.yml) owns the governance consolidation suite;
    objective-audit owns repo-wide static. Both workflow files must exist and declare
    their job so the required-status-check stack on main keeps catching what local
    pre-push no longer runs.
    """
    errors: list[str] = []
    wf_dir = REPO / ".github" / "workflows"
    pytest_wf = wf_dir / "pytest.yml"
    if not pytest_wf.is_file():
        errors.append(".github/workflows/pytest.yml: missing (required-CI pytest-full backing)")
    else:
        text = pytest_wf.read_text(encoding="utf-8", errors="replace")
        if "pytest" not in text:
            errors.append(".github/workflows/pytest.yml: does not invoke pytest")
    objective_wf = wf_dir / "objective-audit.yml"
    if not objective_wf.is_file():
        errors.append(".github/workflows/objective-audit.yml: missing (required-CI static backing)")
    elif "--objective-audit" not in objective_wf.read_text(encoding="utf-8", errors="replace"):
        errors.append(".github/workflows/objective-audit.yml: missing --objective-audit")
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
    errors.extend(check_prepush_lightweight_only())
    errors.extend(check_required_ci_backing())
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
