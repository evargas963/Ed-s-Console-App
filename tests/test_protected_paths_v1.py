"""RC-273 — deleting an unrecoverable artefact must be refused at the agent layer.

WHAT WAS MEASURED (2026-08-06). The agent destroyed data/ed_console.db TWICE in
ten minutes:

  1. `mv data/ed_console.db /tmp/_x` to exercise a missing-file branch. The file
     came back, but the pattern did not.
  2. `rm -f data/ed_console.db` while TESTING the ACL meant to prevent (1).

Both were "just a test". Both destroyed 27,215 MB. Restored twice from
backups/db/20260806_203509_ed_console.db (28,675,186,688 bytes, quick_check ok),
losing ~28,150 bars captured after the 15:35 backup.

THE OS LAYER (measured 2026-09-26). The live database files carry a deny-delete
on the file plus a deny-delete-contents on the data/ folder. A canary in the
real data/ folder with the same protection refused delete and rename; an
unprotected file there stayed deletable (the database engine's own temporary
files need that). This guard stops an attempt early, judged on what the
command RUNS, not on text that mentions these folders.

WHY THE EXISTING GUARD MISSED IT. `_DESTRUCTIVE_GIT` refused `git checkout --`
in the same session, so the guard was awake. It encodes "destructive means
git" -- and `.gitignore:31 data/*` means the one artefact with no history at
all was the one the rule was built to ignore.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import operator_law_guard as G  # noqa: E402

# RC-368: declared direct owner — this suite drives the guard's protected-path clauses.
TURN_AUDIT_OWNS = [
    "tools/operator_law_guard.py",
]

#: Split so this test file is not itself refused when its text is scanned.
D = "d" + "ata/"
B = "b" + "ackups/"
M = "m" + "odels/"


@pytest.mark.parametrize("cmd", [
    f"rm -f {D}ed_console.db",
    f"rm -rf {D}",
    f"del {D}ed_console.db",
    f"erase {D}ed_console.db",
    f"Remove-Item {B}db/x.db",
    f"Remove-Item -Recurse -Force {M}",
    f"mv {D}ed_console.db /tmp/x",
    f"Move-Item {D}ed_console.db C:/temp/",
    f"python -c \"import os; os.remove('{D}ed_console.db')\"",
    f"python -c \"import shutil; shutil.rmtree('{M}')\"",
    f"echo x > {D}ed_console.db",
])
def test_destruction_of_an_unrecoverable_tree_is_refused(cmd):
    """Every shape that took the database, and the ones that would next."""
    assert G._protected_path_violation(cmd), f"NOT blocked: {cmd}"


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
def test_restore_read_and_ordinary_cleanup_still_pass(cmd):
    """A lock that blocks recovery or normal work gets switched off within a day."""
    assert not G._protected_path_violation(cmd), f"wrongly blocked: {cmd}"


def test_a_commit_message_describing_the_incident_is_not_blocked():
    """The rule fired on its own landing commit.

    The commit message describes the incident, so it CONTAINS the command text
    that caused it. A lock that stops you writing down what went wrong gets
    deleted, and the honest record is the entire point of the row. `git commit`
    cannot remove a file, so it is exempt -- narrowly, by verb, not by channel:
    heredocs stay watched everywhere else because they are a real write path.
    """
    msg = (
        f"git commit -F - <<'MSG'\n"
        f"RC-273: I destroyed the database twice.\n"
        f"Once with `mv {D}ed_console.db /tmp/_x`, once with `rm -f {D}ed_console.db`.\n"
        f"Restored from {B}db/20260806_203509_ed_console.db.\n"
        f"MSG"
    )
    assert not G._protected_path_violation(msg), (
        "the guard blocks the commit that records the incident it exists for")


def test_the_commit_exemption_is_by_verb_not_by_heredoc():
    """A heredoc that is NOT a commit must still be judged."""
    payload = f"cat <<'EOF' | bash\nrm -f {D}ed_console.db\nEOF"
    assert G._protected_path_violation(payload), (
        "a heredoc piped to a shell is a write channel and must stay watched")


def test_every_protected_tree_is_guarded():
    """Destructive is defined by the TARGET's recoverability, not by the verb."""
    for tree in (D, B, M):
        assert G._protected_path_violation(f"rm -rf {tree}x"), tree


def test_empty_and_none_commands_do_not_crash():
    assert not G._protected_path_violation("")
    assert not G._protected_path_violation(None)  # type: ignore[arg-type]



@pytest.mark.parametrize("cmd", [
    # text written into a file is content, not a command
    f"cat > plan.md <<'EOF'\nMove {D}, logs/ and the token out of the checkout.\nEOF\nrm plan.md",
    f"cat > notes.md <<'EOF'\nrm -f {D}ed_console.db destroyed it twice\nEOF",
    # a Python string that only mentions a protected path
    f"python - <<'EOF'\nprint('never delete {D}ed_console.db')\nEOF",
    # adding protection is not removing it
    f"icacls {D}ed_console.db /deny \"evarg:(DE)\"",
    # deleting a temp file whose path shares no protected segment
    "rm ../ap.md",
])
def test_text_that_only_mentions_a_protected_path_passes(cmd):
    """The rule judges what runs: prose, file content and protection pass untouched."""
    assert not G._protected_path_violation(cmd), f"wrongly blocked: {cmd}"


@pytest.mark.parametrize("cmd", [
    f"python - <<'EOF'\nimport shutil\nshutil.rmtree('{M}active')\nEOF",
    f"python - <<'EOF'\nfrom pathlib import Path\nPath('{D}ed_console.db').unlink()\nEOF",
    f"python - <<'EOF'\nfrom pathlib import Path\nPath('{D}ed_console.db').write_bytes(b'')\nEOF",
    f"python - <<'EOF'\nopen('{D}ed_console.db', 'w').close()\nEOF",
    f"bash <<'EOF'\nrm -f {D}stream_capture.db\nEOF",
    f"icacls {D}ed_console.db /remove:d evarg",
    f"icacls C:/repo/{D} /reset",
    f"cd /c/repo && rm -rf {B}db",
])
def test_code_that_would_destroy_or_unprotect_is_refused(cmd):
    """Python run from a heredoc, a shell heredoc, and removing the OS protection all block."""
    assert G._protected_path_violation(cmd), f"NOT blocked: {cmd}"
