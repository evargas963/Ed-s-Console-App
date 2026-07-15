"""Adversarial coverage for the privacy guard (tools/check_private_paths.py).

Single pattern source: this suite imports the guard tool — the pre-commit hook
and required-CI pytest-full enforce the SAME scope, patterns and allowlist.
The active-contract allowlist row was REMOVED with the PR41 root-cause fix:
active contracts are path-free (worktree_lease_sha256 + authorized_remote) and
tools/mission_authorization.py refuses any legacy absolute-path field.
Fictional fixture paths live only in this test source, outside the guard scope.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.check_private_paths import (  # noqa: E402
    PRIVATE_PATH_ALLOWLIST,
    PRIVATE_PATH_PATTERNS,
    find_private_paths,
    line_allowlisted,
    tracked_scan_targets,
)


def test_no_operator_home_paths_in_tracked_evidence():
    """Fail closed on any machine-specific home path in tracked evidence scope."""
    v = find_private_paths()
    assert v == [], "operator-home paths in tracked evidence:\n" + "\n".join(v)


def test_active_contracts_are_path_free():
    """Root-cause lock: no active contract may carry ANY private-path pattern —
    there is deliberately NO allowlist row for governance/mission_authorization/active/."""
    assert not any(prefix.startswith("governance/mission_authorization/active")
                   for prefix, _ in PRIVATE_PATH_ALLOWLIST)
    for rel in tracked_scan_targets():
        if not rel.startswith("governance/mission_authorization/active/"):
            continue
        text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        for label, pat in PRIVATE_PATH_PATTERNS:
            assert not pat.search(text), f"{rel}: active contract carries {label}"


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
        # prefix elided by an assertion diff — the tmpdir fragment still leaks
        "...n_sco...\\\\\\pytest-of-someone\\\\\\\\pytest-1\\\\\\\\test_x0",
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
        "pytest-of-<USER>/pytest-1/test_x0",
    )
    for s in allowed:
        assert not any(p.search(s) for _, p in PRIVATE_PATH_PATTERNS), f"false positive: {s!r}"


def test_allowlist_binds_line_and_file():
    """A marker on the wrong LINE or in the wrong FILE never allowlists a hit."""
    consumed = "governance/mission_authorization/consumed/X.retired.json"
    fictional = 'C:/Users/someone/wt'
    # right file, right marker
    assert line_allowlisted(consumed, f'"authorized_worktree": "{fictional}",')
    # right file, WRONG line (marker absent)
    assert not line_allowlisted(consumed, f'"notes": "{fictional}"')
    # WRONG file, marker present
    assert not line_allowlisted(
        "reports/scoreboard_forensic/anything.json",
        f'"authorized_worktree": "{fictional}",')
    # active contracts: never allowlisted, even with the marker
    assert not line_allowlisted(
        "governance/mission_authorization/active/X.json",
        f'"authorized_worktree": "{fictional}",')


def test_guard_reports_synthetic_violation(tmp_path):
    """Fail-open lock: a violating file MUST produce a violation line with exact
    file:line — a silenced reporter turns this red."""
    rel = "reports/scoreboard_forensic/synthetic_evidence.json"
    p = tmp_path / rel
    p.parent.mkdir(parents=True)
    p.write_text('{"path": "C:/Users/someuser/secret/evidence.json"}\n', encoding="utf-8")
    v = find_private_paths(root=tmp_path, targets=[rel])
    # the synthetic line legitimately trips both the windows and posix patterns
    assert v and all(x.startswith(f"{rel}:1:") for x in v)
    assert any("windows_user_home" in x for x in v)


def test_fixture_self_reference_cannot_satisfy_guard():
    """This test file's fictional fixtures are OUTSIDE the guard scope — they can
    neither trip nor satisfy it."""
    assert not any(rel.startswith("tests/") for rel in tracked_scan_targets())


def test_private_path_allowlist_is_narrow_and_used():
    """Every allowlist row must reference a real tracked file; stale rows fail."""
    tracked = set(tracked_scan_targets())
    for prefix, marker in PRIVATE_PATH_ALLOWLIST:
        assert any(rel.startswith(prefix) for rel in tracked), f"stale allowlist prefix: {prefix}"
        assert marker.startswith('"') and marker.endswith('"')
