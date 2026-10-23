"""Deleting, moving, overwriting or unprotecting a file under data/ is refused at the agent
layer: data/ is gitignored, so nothing in it has a history to restore from. The guard judges
what a command RUNS, not text that mentions the folder; restores into it and reads stay legal.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import operator_law_guard as G  # noqa: E402

#: The protected tree and the backups folder, as the commands below name them.
D = "data/"
B = "backups/"


@pytest.mark.parametrize("cmd", [
    f"rm -f {D}ed_console.db",
    f"rm -rf {D}",
    f"del {D}ed_console.db",
    f"erase {D}ed_console.db",
    f"Remove-Item {D}x.db",
    f"Remove-Item -Recurse -Force {D}",
    f"mv {D}ed_console.db /tmp/x",
    f"Move-Item {D}ed_console.db C:/temp/",
    f"python -c \"import os; os.remove('{D}ed_console.db')\"",
    f"python -c \"import shutil; shutil.rmtree('{D}')\"",
    f"echo x > {D}ed_console.db",
])
def test_destruction_of_an_unrecoverable_tree_is_refused(cmd):
    """Delete, remove, move, python file removal and redirect-overwrite of data/ are refused."""
    assert any(f"under {D}" in b for b in G.bash_violations(cmd)), f"NOT blocked: {cmd}"


@pytest.mark.parametrize("cmd", [
    # The restore path must never be blocked -- it is the recovery route.
    f"cp {B}db/20260806_203509_ed_console.db {D}ed_console.db",
    f"Copy-Item {B}db/latest.db {D}ed_console.db",
    # Reads and queries are untouched.
    f"sqlite3 {D}ed_console.db \"select count(*) from price_bars_1m\"",
    f"python -c \"import sqlite3; sqlite3.connect('{D}ed_console.db')\"",
    # Deleting elsewhere is the cleanup work and must stay possible.
    "rm -f /tmp/scratch.txt",
    "rm -f reports/old_report.md",
    "rm -f tools/dead_tool.py",
    "git worktree remove --force ../EdWebConsole-item4",
])
def test_restore_read_and_ordinary_cleanup_pass(cmd):
    """Recovery into data/, reads, and deletes elsewhere are not refused."""
    assert not any(f"under {D}" in b for b in G.bash_violations(cmd)), f"wrongly blocked: {cmd}"


def test_a_commit_message_quoting_a_destructive_command_is_not_blocked():
    """A commit message that quotes a destructive command is not refused: `git commit`
    cannot remove a file, so it is exempt — by verb, not by channel: heredocs stay watched
    everywhere else because they are a real write path.
    """
    msg = (
        f"git commit -F - <<'MSG'\n"
        f"RC-273: I destroyed the database twice.\n"
        f"Once with `mv {D}ed_console.db /tmp/_x`, once with `rm -f {D}ed_console.db`.\n"
        f"Restored from {B}db/20260806_203509_ed_console.db.\n"
        f"MSG"
    )
    assert not any(f"under {D}" in b for b in G.bash_violations(msg)), (
        "the guard blocks a commit whose message quotes a destructive command")


def test_the_commit_exemption_is_by_verb_not_by_heredoc():
    """A heredoc that is NOT a commit is judged."""
    payload = f"cat <<'EOF' | bash\nrm -f {D}ed_console.db\nEOF"
    assert any(f"under {D}" in b for b in G.bash_violations(payload)), (
        "a heredoc piped to a shell is a write channel and must stay watched")


def test_the_protected_tree_is_guarded_and_backups_is_not():
    """Destructive is defined by the TARGET's recoverability, not by the verb. No database
    backups are kept (operator's decision), so backups/ is no protected tree."""
    assert any(f"under {D}" in b for b in G.bash_violations(f"rm -rf {D}x"))
    assert not any(f"under {D}" in b for b in G.bash_violations(f"rm -rf {B}x"))


def test_empty_and_none_commands_do_not_crash():
    assert G.bash_violations("") == []
    assert G.bash_violations(None) == []  # type: ignore[arg-type]



@pytest.mark.parametrize("cmd", [
    # text written into a file is content, not a command
    f"cat > plan.md <<'EOF'\nMove {D}, logs/ and the token out of the checkout.\nEOF\nrm plan.md",
    f"cat > notes.md <<'EOF'\nrm -f {D}ed_console.db destroyed it twice\nEOF",
    # a Python string that only mentions a protected path
    f"python - <<'EOF'\nprint('never delete {D}ed_console.db')\nEOF",
    # adding protection is not removing it
    f"icacls {D}ed_console.db /deny \"someuser:(DE)\"",
    # deleting a temp file whose path shares no protected segment
    "rm ../ap.md",
])
def test_text_that_only_mentions_a_protected_path_passes(cmd):
    """The rule judges what runs: prose, file content and protection pass untouched."""
    assert not any(f"under {D}" in b for b in G.bash_violations(cmd)), f"wrongly blocked: {cmd}"


@pytest.mark.parametrize("cmd", [
    f"python - <<'EOF'\nimport shutil\nshutil.rmtree('{D}')\nEOF",
    f"python - <<'EOF'\nfrom pathlib import Path\nPath('{D}ed_console.db').unlink()\nEOF",
    f"python - <<'EOF'\nfrom pathlib import Path\nPath('{D}ed_console.db').write_bytes(b'')\nEOF",
    f"python - <<'EOF'\nopen('{D}ed_console.db', 'w').close()\nEOF",
    f"bash <<'EOF'\nrm -f {D}stream_capture.db\nEOF",
    f"icacls {D}ed_console.db /remove:d someuser",
    f"icacls C:/repo/{D} /reset",
    f"cd /c/repo && rm -rf {D}",
])
def test_code_that_would_destroy_or_unprotect_is_refused(cmd):
    """Python run from a heredoc, a shell heredoc, and removing the OS protection all block."""
    assert any(f"under {D}" in b for b in G.bash_violations(cmd)), f"NOT blocked: {cmd}"
