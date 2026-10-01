# institutional-synthetic-ok: crafted command strings prove the action bans block and permit correctly.
"""operator_law_guard: the host-wide action bans, in both directions, and its hook entrypoint."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import operator_law_guard as G  # noqa: E402


# ── RC-273: unrecoverable trees ────────────────────────────────────────────────────────
def test_appdata_redirect_not_protected_tree():
    """_PROTECTED_TREE is path-segment anchored: `AppData/` is not `data/`."""
    cmd = "git show HEAD:x > /c/Users/evarg/AppData/Local/Temp/claude/s/out.txt"
    assert G._protected_path_violation(cmd) is False


@pytest.mark.parametrize("cmd", [
    "rm data/ed_console.db",
    "> data/x.db",
    "mv backups/a b",
    "Remove-Item backups/db/x.db",
    "python -c \"import os; os.remove('data/ed_console.db')\"",
])
def test_real_protected_tree_targets_still_block(cmd):
    assert G._protected_path_violation(cmd) is True, cmd


@pytest.mark.parametrize("cmd", [
    "cp backups/db/x.db data/ed_console.db",          # a restore INTO the tree is legal
    "git commit -m 'RC-273: refused rm data/ed_console.db'",   # a message describing it
    "ls data/",
])
def test_protected_tree_permits_restores_messages_and_reads(cmd):
    assert G._protected_path_violation(cmd) is False, cmd


# ── lock disable ───────────────────────────────────────────────────────────────────────
def test_git_push_dry_run_not_lock_disable():
    for cmd in ("git push -n origin main", "git push --dry-run origin main"):
        out = G.bash_violations(cmd)
        assert not any("disables a mechanical lock" in v for v in out), (cmd, out)
    for cmd in ("git commit -n -m x", "git push --no-verify", "SKIP=ruff-correctness git commit -m x",
                "$env:SKIP='eol-style-invariant'; git commit -m x", "pre-commit uninstall",
                "git -c core.hooksPath=/dev/null commit -m x"):
        out = G.bash_violations(cmd)
        assert any("disables a mechanical lock" in v for v in out), (cmd, out)


# ── blind staging ──────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("cmd", ["git add -A", "git add --all", "git add .", "git add -u", "git add *"])
def test_blind_staging_blocks(cmd):
    assert any("blind staging" in v for v in G.bash_violations(cmd)), cmd


@pytest.mark.parametrize("cmd", ["git add tools/x.py", "git add -p", "git add tests/ tools/"])
def test_explicit_staging_passes(cmd):
    assert G.bash_violations(cmd) == [], cmd


# ── every ban, and the action refused, never the word ──────────────────────────────────
@pytest.mark.parametrize("cmd,needle", [
    ("git commit --no-verify -m x", "disables a mechanical lock"),
    ("git config core.hooksPath /dev/null", "disables a mechanical lock"),
    ("python -m pre_commit uninstall", "disables a mechanical lock"),
    ("rm .git/hooks/pre-commit", "disables a mechanical lock"),
    ("git add -A", "blind staging"),
    ("rm -rf data/ed_console.db", "data/ or backups/"),
    ("git push origin HEAD:main", "only through a PR"),
    ("git push origin main", "only through a PR"),
])
def test_universal_protections_fire(cmd, needle):
    out = G.bash_violations(cmd)
    assert any(needle in v for v in out), (cmd, out)


@pytest.mark.parametrize("cmd", [
    "git push -u origin fix/main-screen",
    "git config --get core.hooksPath",
    "gh pr merge 427 --merge",
    "gh pr view 427",
    "grep -n no-verify tools/operator_law_guard.py",
])
def test_the_action_is_refused_never_the_word(cmd):
    """Reading about a lock, pushing a branch whose name contains "main", or merging a PR (the
    agent merges under AGENTS.md § Authority) is not a refused action."""
    assert G.bash_violations(cmd) == [], cmd


# ── the deleted rules stay deleted ─────────────────────────────────────────────────────
def test_inspection_and_shell_writes_are_not_the_guards_business():
    """The no-grep rule blocked read-only stdout filters three times in one session and the
    source-write bans guarded a retired registry; a rule that obstructs inspection with no
    unique protection is gone, with no successor under another name."""
    for cmd in ("grep -r foo tools/", "rg foo", "git grep foo", "Select-String foo server.py",
                "cat > x.py <<EOF\nprint(1)\nEOF", "python -c \"open('x.py','w').write('1')\"",
                "sed -i 's/a/b/' server.py", "Set-Content server.py 'x=1'"):
        assert G.bash_violations(cmd) == [], cmd
    for gone in ("_repo_search_violation", "_heredoc_write_violation", "_redirect_source_violation",
                 "_payload_write_violation", "_PS_WRITE_BAD", "edit_violations", "turn_slice",
                 "_successful_commands", "_verification_ran", "last_assistant_text"):
        assert not hasattr(G, gone), gone


# ── the real hook entrypoint ───────────────────────────────────────────────────────────
def _hook(command: str):
    payload = {"session_id": "pytest", "tool_name": "Bash", "tool_input": {"command": command},
               "cwd": str(REPO)}
    return subprocess.run([sys.executable, str(REPO / "tools" / "operator_law_guard.py")],
                          input=json.dumps(payload), capture_output=True, text=True, cwd=str(REPO),
                          check=False)


def test_hook_permits_a_commit():
    p = _hook('git commit -m "x"')
    assert p.returncode == 0, p.stderr


def test_hook_rejects_no_verify_with_guard_env_off(monkeypatch):
    """No environment switch turns the hook off."""
    monkeypatch.setenv("ED_OPERATOR_LAW_GUARD", "off")
    p = _hook("git commit --no-verify -m x")
    assert p.returncode == 2, (p.returncode, p.stdout, p.stderr)
    assert "disables a mechanical lock" in p.stderr
