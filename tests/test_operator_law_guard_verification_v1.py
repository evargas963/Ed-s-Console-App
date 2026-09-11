# institutional-synthetic-ok: crafted command strings prove the action bans block and permit correctly.
"""operator_law_guard — the three surviving host-wide action bans, in both directions.

KEEP/MERGE/DELETE 2026-09-10: the no-grep rule, the shell source-write bans, the -c payload
classifier and the transcript-derived CLOSE-needs-verification rule were deleted (the module
docstring records why); their suites went with them. What remains must still bite where it
bit before and stay quiet on the measured false-positive classes.
"""
from __future__ import annotations

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
    "Remove-Item models/active/x.bin",
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
        out = G.bash_violations(cmd, [], payload_cwd=str(REPO))
        assert not any("disables a mechanical lock" in v for v in out), (cmd, out)
    for cmd in ("git commit -n -m x", "git push --no-verify", "SKIP=ruff-correctness git commit -m x",
                "$env:SKIP='eol-style-invariant'; git commit -m x", "pre-commit uninstall",
                "git -c core.hooksPath=/dev/null commit -m x"):
        out = G.bash_violations(cmd, [], payload_cwd=str(REPO))
        assert any("disables a mechanical lock" in v for v in out), (cmd, out)


def test_the_retired_env_kill_switch_spellings_are_not_policed():
    """RC-450: no ED_*_GUARD/LOCK switch exists, so a string that spells one is not an action."""
    for cmd in ("ED_UI_MOCKUP_LOCK=off git commit -m x", "$env:ED_STOP_GUARD='false'"):
        assert not any("disables a mechanical lock" in v for v in G.bash_violations(cmd, [], "")), cmd


# ── blind staging ──────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("cmd", ["git add -A", "git add --all", "git add .", "git add -u", "git add *"])
def test_blind_staging_blocks(cmd):
    assert any("blind staging" in v for v in G.bash_violations(cmd, [], "")), cmd


@pytest.mark.parametrize("cmd", ["git add tools/x.py", "git add -p", "git add tests/ tools/"])
def test_explicit_staging_passes(cmd):
    assert G.bash_violations(cmd, [], "") == [], cmd


# ── the deleted rules stay deleted ─────────────────────────────────────────────────────
def test_inspection_and_shell_writes_are_not_the_guards_business():
    """The no-grep rule blocked read-only stdout filters three times in one session and the
    source-write bans guarded a retired registry; a rule that obstructs inspection with no
    unique protection is gone, with no successor under another name."""
    for cmd in ("grep -r foo tools/", "rg foo", "git grep foo", "Select-String foo server.py",
                "cat > x.py <<EOF\nprint(1)\nEOF", "python -c \"open('x.py','w').write('1')\"",
                "sed -i 's/a/b/' server.py", "Set-Content server.py 'x=1'"):
        assert G.bash_violations(cmd, [], str(REPO)) == [], cmd
    for gone in ("_repo_search_violation", "_heredoc_write_violation", "_redirect_source_violation",
                 "_payload_write_violation", "_PS_WRITE_BAD", "edit_violations", "turn_slice",
                 "_successful_commands", "_verification_ran", "last_assistant_text"):
        assert not hasattr(G, gone), gone
    src = Path(G.__file__).read_text(encoding="utf-8")
    assert "transcript_path" not in src.split('"""', 2)[-1]
