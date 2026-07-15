"""Mechanical privacy guard: no operator-home absolute paths in tracked evidence.

PR41_OPERATOR_PATH_PRIVACY_SCRUB_V1: raw mutation stdout, the mutation manifest
and the consumed mission contract carried machine-specific home paths. Evidence
must use stable abstractions (<WORKTREE_ROOT>, <TEMP_WORKTREE_ROOT>, <PYTEST_TMP>,
<TEMP>, <USER_HOME>, <EXTERNAL_EVIDENCE_ROOT>) or repository-relative paths.

Scope: git-tracked files under reports/scoreboard_forensic/ and
governance/mission_authorization/, plus the two Schwab V4 pin artifacts.
Narrow documented allowlist only:
  * active mission contracts' "authorized_worktree" is machine-binding
    configuration REQUIRED by the mission-authorization gate
    (tools/mission_authorization.py validate_workspace string-compares it);
  * schwab_v4_scoreboard.json register_path/perf_proof_dir are pre-existing
    base-branch values, not attributable to Lane-A work (future regeneration
    may normalize them).
Fictional fixture paths live only in test sources, which are outside this scope.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PRIVATE_PATH_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("windows_user_home", re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+[A-Za-z0-9_.-]+", re.IGNORECASE)),
    ("posix_user_home", re.compile(r"(?<![\w<])/(?:home|Users)/[A-Za-z0-9_.-]+[\\/]")),
    ("file_uri_home", re.compile(r"file:///[A-Za-z]:[\\/]", re.IGNORECASE)),
)

# (path-prefix, required-substring-on-line) — every allowlisted line must carry
# the substring; anything else in the file still fails.
PRIVATE_PATH_ALLOWLIST: tuple[tuple[str, str], ...] = (
    ("governance/mission_authorization/active/", '"authorized_worktree"'),
    # consumed contracts are immutable historical mission records; base-era ones
    # predate this guard, and the binding value was functional when live.
    ("governance/mission_authorization/consumed/", '"authorized_worktree"'),
    ("governance/artifacts/schwab_v4_scoreboard.json", '"register_path"'),
    ("governance/artifacts/schwab_v4_scoreboard.json", '"perf_proof_dir"'),
)

# Lane-A evidence cone only: base-era reports/** outside scoreboard_forensic
# carry pre-existing machine paths (1016 lines measured 2026-07-14) that are not
# attributable to this PR; widening the scope is a separate normalization mission.
SCAN_PREFIXES = ("reports/scoreboard_forensic/", "governance/mission_authorization/")
SCAN_EXTRA_FILES = (
    "governance/artifacts/schwab_v4_scoreboard.json",
    "governance/artifacts/schwab_v4_register_build_meta.json",
)


def _tracked_scan_targets() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "--", *SCAN_PREFIXES, *SCAN_EXTRA_FILES],
        capture_output=True, text=True, cwd=ROOT, check=True,
    ).stdout
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def _line_allowlisted(rel: str, line: str) -> bool:
    return any(rel.startswith(prefix) and marker in line
               for prefix, marker in PRIVATE_PATH_ALLOWLIST)


def find_private_paths() -> list[str]:
    violations: list[str] = []
    for rel in _tracked_scan_targets():
        p = ROOT / rel
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            for label, pat in PRIVATE_PATH_PATTERNS:
                if pat.search(line):
                    if _line_allowlisted(rel, line):
                        continue
                    violations.append(f"{rel}:{i}: {label}: {line.strip()[:160]}")
    return violations


def test_no_operator_home_paths_in_tracked_evidence():
    """Fail closed on any machine-specific home path in tracked evidence scope."""
    v = find_private_paths()
    assert v == [], "operator-home paths in tracked evidence:\n" + "\n".join(v)


def test_private_path_patterns_catch_all_required_forms():
    """Adversarial: every prohibited form is caught; every allowed form passes."""
    fictional_hits = (
        "C:\\Users\\someuser\\repo\\file.py",
        "C:/Users/otherperson/AppData/Local/Temp/x",
        "c:/users/anyone/Documents/notes.txt",
        "/home/someuser/project/main.py",
        "/Users/somebody/work/tool.py",
        "path = 'file:///C:/anything/at/all'",
        'json escaped "C:\\\\Users\\\\someone\\\\x"',
    )
    for s in fictional_hits:
        assert any(p.search(s) for _, p in PRIVATE_PATH_PATTERNS), f"missed: {s!r}"
    allowed = (
        "reports/scoreboard_forensic/mutation_raw/x.txt",
        "<WORKTREE_ROOT>/calibration/daily_scoreboard.py",
        "<TEMP_WORKTREE_ROOT>/mA_run1",
        "<PYTEST_TMP>/pytest-1/test_x0",
        "<USER_HOME>/anything",
        "https://github.com/evargas963/Ed-s-Console-App/pull/41",
        "tmp_path = WindowsPath('<PYTEST_TMP>/pytest-889/test_case0')",
    )
    for s in allowed:
        assert not any(p.search(s) for _, p in PRIVATE_PATH_PATTERNS), f"false positive: {s!r}"


def test_private_path_allowlist_is_narrow_and_used():
    """Every allowlist row must reference a real tracked file; the active-contract
    exemption exists solely because validate_workspace string-compares the value."""
    tracked = set(_tracked_scan_targets())
    for prefix, marker in PRIVATE_PATH_ALLOWLIST:
        assert any(rel.startswith(prefix) for rel in tracked), f"stale allowlist prefix: {prefix}"
        assert marker.startswith('"') and marker.endswith('"')
