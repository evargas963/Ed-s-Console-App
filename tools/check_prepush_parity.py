#!/usr/bin/env python3
"""GOV-GATE-PARITY-01 — local/remote fast-fail parity gate (pre-push).

Root-cause evidence (five documented local-green→CI-red escapes on 2026-07-11):
stale check-stack inventory (89ebaca), mega4 def coverage (5f860fa), ruff F401
×2 (5846a20, e02a367-chain), CSV-first ×2 (f478208, c19ecb4). Each escaped
because the remote check had no mandatory local twin.

Parity BY CONSTRUCTION: the ruff and enforce-static commands are PARSED FROM
THE CANONICAL WORKFLOW FILES at runtime (.github/workflows/hardening.yml), so
a remote configuration change cannot silently diverge from this gate — if the
workflow line moves or changes, this gate runs the new command or fails loud.

Stages (all mandatory; any child failure → nonzero final exit):
  1. ruff        — exact Hardening command (parsed from hardening.yml)
  2. static      — exact enforce-static command (parsed from hardening.yml)
  3. csv_first   — canonical guard against the OUTGOING diff
                   (origin/main...HEAD), same checker CI runs on the PR diff;
                   applicability is decided by the guard itself (canonical
                   scope source), never re-derived here
  4. owner_tests — tools/gate_test_ownership.select_owner_suites over the
                   outgoing changed files; KNOWN_NARROW → union of owner
                   suites; ANY full-bundle class (unknown/ambiguous/hook/
                   governance/shared-core/empty) → the FULL SAFE BUNDLE below

No stage result is cached by this wrapper: ruff/csv are fast and repo-scoped;
owner tests must always execute; enforce-static internally benefits from the
success-only governance gate cache (tools/governance_gate_cache.py) whose keys
cover checker sources, manifest content, DB stat triple, python and invocation
identity — failures are never cached there either.

Remote CI (Objective Audit, Pytest Full Suite, Hardening Gates, Schwab CSV
First Guard) remains mandatory and unchanged: this gate only moves the
fast-fail earlier; it is not a substitute for the remote authority.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HARDENING_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "hardening.yml"

# Phase 2B safe bundle (governance consolidation suites) — the FULL fallback
# when ownership is unknown/ambiguous. Runtime is accepted cost of unknown
# scope; narrowing it would weaken the gate (mission: never trade protection
# for a timing target).
FULL_SAFE_BUNDLE: tuple[str, ...] = (
    "tests/test_governance_consolidation.py",
    "tests/test_check_fix_everything_we_touch.py",
    "tests/test_ml_feature_schema_parity.py",
    "tests/test_check_schwab_csv_first.py",
    "tests/test_forbidden_phrases.py",
    "tests/test_money_path_roster.py",
    "tests/test_check_no_deferral_language.py",
)


def parse_workflow_run_command(workflow_path: Path, step_name_fragment: str) -> str:
    """Extract the exact `run:` command of the named step from a workflow file.

    Fails LOUD (raises) when the step or its run line cannot be found — a
    silently-missing remote step must never downgrade the local gate."""
    text = workflow_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if step_name_fragment in line and "name:" in line:
            for j in range(i + 1, min(i + 6, len(lines))):
                m = re.match(r"\s*run:\s*(.+?)\s*$", lines[j])
                if m:
                    return m.group(1)
    raise RuntimeError(
        f"parity gate: step {step_name_fragment!r} not found in {workflow_path.name} — "
        "remote workflow changed; update the parity gate in the same diff"
    )


def ruff_remote_command() -> str:
    return parse_workflow_run_command(HARDENING_WORKFLOW, "ruff (correctness rules")


def enforce_static_remote_command() -> str:
    return parse_workflow_run_command(HARDENING_WORKFLOW, "enforce-static")


def outgoing_changed_files(base_ref: str = "origin/main") -> list[str]:
    r = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
    )
    files = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
    # staged-but-uncommitted work must also be covered at push time
    r2 = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
    )
    files += [ln.strip() for ln in r2.stdout.splitlines() if ln.strip()]
    return sorted(set(files))


def write_outgoing_diff(base_ref: str = "origin/main") -> Path:
    # Binary-safe: an outgoing diff containing binary artifacts (e.g. governed
    # model replacements under models/active/**) is not valid text in the
    # locale codec — text=True made stdout undecodable/None and crashed the
    # gate at push time. Capture bytes and decode with replacement; the
    # CSV-first guard only inspects text hunks.
    raw = subprocess.run(
        ["git", "diff", f"{base_ref}...HEAD"],
        cwd=REPO_ROOT, capture_output=True, timeout=120,
    ).stdout or b""
    tmp = Path(tempfile.gettempdir()) / "prepush_parity_csv_first.diff"
    tmp.write_text(raw.decode("utf-8", errors="replace"), encoding="utf-8")
    return tmp


# pre-commit exports GIT_DIR / GIT_INDEX_FILE etc. into pre-push hook children.
# Inherited by grandchildren (pytest tests that spawn nested `git init` repos,
# any tool shelling to git), those vars redirect git AT THE PARENT REPO — the
# proven mechanism behind the push-time-only test failure AND the shared-config
# core.bare corruption observed 2026-07-11. Every parity child runs with the
# GIT context stripped; children discover the repo from cwd=REPO_ROOT.
_GIT_CONTEXT_ENV_KEYS = (
    "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
    "GIT_PREFIX", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
)


def _sanitized_env() -> dict:
    import os as _os

    env = dict(_os.environ)
    for k in _GIT_CONTEXT_ENV_KEYS:
        env.pop(k, None)
    return env


def _run(cmd: list[str] | str, *, shell: bool = False) -> tuple[int, str]:
    r = subprocess.run(
        cmd, cwd=REPO_ROOT, capture_output=True, text=True, shell=shell,
        timeout=3600, env=_sanitized_env(),
    )
    return r.returncode, (r.stdout + r.stderr)[-4000:]


def aggregate_exit(stage_results: dict[str, int]) -> int:
    """Final exit: nonzero iff ANY stage is nonzero. A wrapper bug returning 0
    after a child failure is the masked-failure class — this function is the
    single authority and is adversarially tested."""
    return 0 if all(rc == 0 for rc in stage_results.values()) else 1


def run_parity_gate(*, base_ref: str = "origin/main", emit=print) -> int:
    started = time.time()
    stage_results: dict[str, int] = {}
    provenance: dict[str, object] = {"base_ref": base_ref}

    ruff_cmd = ruff_remote_command()
    provenance["ruff_command"] = ruff_cmd
    rc, out = _run(ruff_cmd, shell=True)
    stage_results["ruff"] = rc
    if rc != 0:
        emit(f"[parity:ruff] FAIL\n{out}")

    static_cmd = enforce_static_remote_command()
    provenance["static_command"] = static_cmd
    rc, out = _run(static_cmd, shell=True)
    stage_results["static"] = rc
    if rc != 0:
        emit(f"[parity:static] FAIL\n{out}")

    diff_file = write_outgoing_diff(base_ref)
    rc, out = _run(
        [sys.executable, "tools/check_schwab_csv_first.py", "--diff-file", str(diff_file)]
    )
    stage_results["csv_first"] = rc
    if rc != 0:
        emit(f"[parity:csv_first] FAIL\n{out}")

    changed = outgoing_changed_files(base_ref)
    provenance["changed_files"] = changed
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from tools.gate_test_ownership import FULL_BUNDLE, select_owner_suites

    selection = select_owner_suites(changed)
    provenance["selector"] = selection
    if selection["selection"] == FULL_BUNDLE:
        suites = [s for s in FULL_SAFE_BUNDLE if (REPO_ROOT / s).is_file()]
        provenance["owner_mode"] = f"FULL_SAFE_BUNDLE({selection['reason']})"
    else:
        suites = list(selection["selection"])
        provenance["owner_mode"] = "KNOWN_NARROW_UNION"
    if not suites:
        # An empty suite list can never be a pass — treat as gate defect.
        emit("[parity:owner_tests] FAIL: empty suite list (fail-closed)")
        stage_results["owner_tests"] = 1
    else:
        rc, out = _run([sys.executable, "-m", "pytest", *suites, "-q", "-x"])
        stage_results["owner_tests"] = rc
        if rc != 0:
            emit(f"[parity:owner_tests] FAIL\n{out[-2500:]}")

    provenance["stage_results"] = stage_results
    provenance["elapsed_sec"] = round(time.time() - started, 1)
    emit("[parity] " + json.dumps(provenance, default=str)[:1500])
    return aggregate_exit(stage_results)


def main() -> int:
    return run_parity_gate()


if __name__ == "__main__":
    raise SystemExit(main())
