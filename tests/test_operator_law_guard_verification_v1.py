# institutional-synthetic-ok: crafted command strings prove the RC-93 rails block and permit correctly.
"""operator_law_guard — audit round 2 (2026-08-25): proof must be ISSUABLE, the no-grep
law is an ACTION predicate, and three measured false-positive classes stay fixed.

WHAT WAS MEASURED (executed PoCs): 'echo pytest all green' minted verification; the grep
spelling test flipped on file extensions and downstream pipes ('grep foo x.py | head'
passed while 'grep foo config.yaml' blocked); the RC-189 -c classifier fired on grep -c
and on commit MESSAGES; _PROTECTED_TREE matched 'AppData/'; git push -n (--dry-run) was
read as --no-verify.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import operator_law_guard as G  # noqa: E402


# ── R5: verification must be issued in command position ───────────────────────────────
@pytest.mark.parametrize("cmd", [
    "echo pytest all green",
    "echo 127.0.0.1:8000 healthy",
    "git commit -m 'ran pytest tests/test_db_safety.py -q'",
])
def test_emitters_and_messages_cannot_mint_verification(cmd):
    assert G._verification_ran(cmd) is False, cmd


@pytest.mark.parametrize("cmd", [
    "pytest tests/test_db_safety.py -q",
    ".venv/Scripts/python.exe tools/check_market_correctness.py",
    "python -m pytest -q",
    "ruff check tools",
    "curl -s http://127.0.0.1:8000/api/health",
])
def test_real_verifications_still_count(cmd):
    assert G._verification_ran(cmd) is True, cmd


def test_close_a_row_needs_issued_not_spelled_proof():
    path = str(REPO / "governance" / "root_cause_log.md")
    echo_only = [{"kind": "bash", "detail": "echo pytest all green",
                  "repo": G.normalize_repo(REPO)}]
    real = [{"kind": "bash", "detail": "pytest tests/test_db_safety.py -q",
             "repo": G.normalize_repo(REPO)}]
    assert G.edit_violations(path, "| RC-1 | CLOSED |", echo_only) != []
    assert G.edit_violations(path, "| RC-1 | CLOSED |", real) == []


# ── F1: the no-grep ACTION predicate matrix (pins the measured inconsistencies) ────────
@pytest.mark.parametrize("cmd", [
    "grep foo tools/operator_law_guard.py",
    "grep foo tools/operator_law_guard.py | head -5",
    "grep -r foo .",
    "grep -r foo . | head -5",
    "git grep -r foo .",
    "git grep foo",
    "rg foo",
    "rg foo --type py",
    "find . -name '*.py' | xargs grep foo",
    "time grep -r foo .",
    "grep foo config.yaml",
    "grep foo config.yml",
    "grep foo notes.txt",
    "grep foo Makefile",
    "cd tools && grep foo operator_law_guard.py",
])
def test_no_grep_blocks_every_file_search_spelling(cmd):
    assert G._repo_search_violation(cmd) is True, cmd


@pytest.mark.parametrize("cmd", [
    "ps aux | grep python",
    "cat f.log | grep ERROR | head",
    "git log --grep=RC-435",
])
def test_stdout_filters_stay_legal(cmd):
    assert G._repo_search_violation(cmd) is False, cmd


# ── F2: -c payload classifier fires only for interpreters ──────────────────────────────
@pytest.mark.parametrize("cmd", [
    'grep -c "open(f, \'w\')" notes.txt',
    'sqlite3 db ".dump" -c "open(f,\'w\')"',
    """git commit -m 'RC-189: refuse python -c "open(p, \\'w\\')" payload writes'""",
])
def test_payload_write_requires_interpreter(cmd):
    assert G._payload_write_violation(cmd) is False, cmd


def test_interpreter_payload_writes_still_block():
    assert G._payload_write_violation(
        'python -c "open(\'x.py\',\'w\').write(\'boom\')"') is True


# ── F4: _PROTECTED_TREE is path-segment anchored ───────────────────────────────────────
def test_appdata_redirect_not_protected_tree():
    cmd = "git show HEAD:x > /c/Users/evarg/AppData/Local/Temp/claude/s/out.txt"
    assert G._protected_path_violation(cmd) is False


@pytest.mark.parametrize("cmd", [
    "rm data/ed_console.db",
    "> data/x.db",
    "mv backups/a b",
])
def test_real_protected_tree_targets_still_block(cmd):
    assert G._protected_path_violation(cmd) is True, cmd


# ── F5: git push -n is --dry-run, never --no-verify ────────────────────────────────────
def test_git_push_dry_run_not_lock_disable():
    for cmd in ("git push -n origin main", "git push --dry-run origin main"):
        out = G.bash_violations(cmd, [], payload_cwd=str(REPO))
        assert not any("disables a mechanical lock" in v for v in out), (cmd, out)
    for cmd in ("git commit -n -m x", "git push --no-verify"):
        out = G.bash_violations(cmd, [], payload_cwd=str(REPO))
        assert any("disables a mechanical lock" in v for v in out), (cmd, out)
