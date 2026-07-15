#!/usr/bin/env python3
"""Fail-closed privacy guard: no operator-home absolute paths in tracked evidence.

PR41_OPERATOR_PATH_PRIVACY_SCRUB_V1 + PR41 root-cause fix: mission contracts are
path-free (worktree_lease_sha256 + authorized_remote), and evidence must use
stable abstractions (<WORKTREE_ROOT>, <TEMP_WORKTREE_ROOT>, <PYTEST_TMP>, <TEMP>,
<USER_HOME>, <EXTERNAL_EVIDENCE_ROOT>) or repository-relative paths.

Enforcement layers: pre-commit hook (early lock, this CLI) + required-CI
pytest-full (tests/test_operator_path_privacy.py imports this module — single
pattern source, no duplicated regex list).

Scope: git-tracked files under reports/scoreboard_forensic/ and
governance/mission_authorization/, plus the two Schwab V4 pin artifacts.
Base-era reports/** outside scoreboard_forensic carry pre-existing machine
paths (1016 lines measured 2026-07-14) not attributable to Lane-A; widening
the scope is a separate normalization mission.

Allowlist (narrow, per-line, documented):
  * consumed contracts are immutable historical mission records; base-era ones
    predate the path-free contract schema (active contracts are now REFUSED if
    they carry any absolute-path field — tools/mission_authorization.py);
  * schwab_v4_scoreboard.json register_path/perf_proof_dir are pre-existing
    base-branch values (future regeneration may normalize them).

Schwab CSV authority checked: yes
CSV row(s): NO_SCHWAB_EQUIVALENT — governance privacy enforcement only.
SCHWAB_CSV_CHECKED
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PRIVATE_PATH_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("windows_user_home", re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+[A-Za-z0-9_.-]+", re.IGNORECASE)),
    ("posix_user_home", re.compile(r"(?<![\w<])/(?:home|Users)/[A-Za-z0-9_.-]+[\\/]")),
    ("file_uri_home", re.compile(r"file:///[A-Za-z]:[\\/]", re.IGNORECASE)),
    # pytest names its tmp root after the OS user (pytest-of-<username>); the
    # fragment leaks the username even when an assertion-diff elides the path
    # prefix (the PR41 D9 residual class). Abstracted forms pytest-of-<...> pass.
    ("pytest_user_tmpdir", re.compile(r"pytest-of-(?!<)[A-Za-z0-9_.-]+", re.IGNORECASE)),
)

# (path-prefix, required-substring-on-line) — an allowlisted line must carry the
# substring AND sit under the prefix; anything else in the file still fails.
PRIVATE_PATH_ALLOWLIST: tuple[tuple[str, str], ...] = (
    ("governance/mission_authorization/consumed/", '"authorized_worktree"'),
    ("governance/artifacts/schwab_v4_scoreboard.json", '"register_path"'),
    ("governance/artifacts/schwab_v4_scoreboard.json", '"perf_proof_dir"'),
)

SCAN_PREFIXES = ("reports/scoreboard_forensic/", "governance/mission_authorization/")
SCAN_EXTRA_FILES = (
    "governance/artifacts/schwab_v4_scoreboard.json",
    "governance/artifacts/schwab_v4_register_build_meta.json",
)


def tracked_scan_targets() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "--", *SCAN_PREFIXES, *SCAN_EXTRA_FILES],
        capture_output=True, text=True, cwd=ROOT, check=True,
    ).stdout
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def line_allowlisted(rel: str, line: str) -> bool:
    return any(rel.startswith(prefix) and marker in line
               for prefix, marker in PRIVATE_PATH_ALLOWLIST)


def find_private_paths(root: Path = ROOT, targets: list[str] | None = None) -> list[str]:
    """Injectable root/targets so tests can prove the detector REPORTS violations
    (a silenced reporter must never pass adversarial coverage)."""
    violations: list[str] = []
    for rel in (targets if targets is not None else tracked_scan_targets()):
        p = root / rel
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            for label, pat in PRIVATE_PATH_PATTERNS:
                if pat.search(line):
                    if line_allowlisted(rel, line):
                        continue
                    violations.append(f"{rel}:{i}: {label}: {line.strip()[:160]}")
    return violations


def main() -> int:
    v = find_private_paths()
    if v:
        print("check_private_paths: FAIL — operator-home paths in tracked evidence:")
        for x in v[:40]:
            print(f"- {x}")
        if len(v) > 40:
            print(f"... {len(v) - 40} more")
        return 1
    print("check_private_paths: PASS (tracked evidence scope clean)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
