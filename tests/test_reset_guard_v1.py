# institutional-synthetic-ok: inject destructive git commands to prove the reset guard BLOCKs.
"""The reset guard — dedicated acceptance suite.

Tree-destructive git blocks at PreToolUse: reset --hard, checkout -- <path>, clean -f,
push --force and every stash but `stash list` on any target; the wider reset, restore,
checkout --, clean class against protected or product paths or in bare whole-tree form.
Safe and read-only forms stay legal.
"""

from __future__ import annotations

from pathlib import Path

import tools.operating_process_lock as OPL
import tools.process_lock_guard as PLG

ROOT = Path(__file__).resolve().parent.parent


def test_destructive_class_blocks():
    for cmd in (
        "git restore -- server.py",
        "git checkout -- static/chart.html",
        "git checkout HEAD -- db.py",
        "git reset --hard",
        "git clean -fd",
        "git stash",
    ):
        assert OPL.reset_guard_violations(cmd), f"reset guard silent on: {cmd}"


def test_safe_forms_allow():
    for cmd in (
        "git log --oneline -5",
        "git diff HEAD -- server.py",
        "git restore --staged governance/root_cause_log.md",
        "git stash list",
        "git checkout -b feature/next",
        "git clean -n",
    ):
        assert not OPL.reset_guard_violations(cmd), f"reset guard false-fired on: {cmd}"


# ── Judge the ACTION, not the data the command carries ──────────────────────────────────
# A commit message or other quoted text that describes destructive git is not a statement.


def test_a_commit_message_quoting_destructive_git_is_not_an_action():
    heredoc = (
        "git commit --file - <<'MSG'\n"
        "RC-252: the guard was silent on git restore -- static/chart.html\n"
        "and on git checkout -- server.py, so product files were wipeable.\n"
        "Also proved git reset --hard still blocks.\n"
        "MSG"
    )
    assert not OPL.reset_guard_violations(heredoc), (
        "the reset guard blocked a commit whose only destructive git is prose in the message — "
        "banning the word, not the action"
    )
    inline = "git commit -m 'RC-231 was opened after a git reset --hard wiped static/chart.html'"
    assert not OPL.reset_guard_violations(inline)


def test_stripping_payloads_does_not_open_a_bypass():
    """The exemption is for DATA. A body handed to an interpreter is the instruction, and a
    real destructive command is unaffected by any of this."""
    piped = "bash <<'EOF'\ngit reset --hard\nEOF"
    assert OPL.reset_guard_violations(piped), (
        "a heredoc piped into a shell IS the instruction — stripping it would be a bypass"
    )
    for cmd in ("git restore -- server.py", "git reset --hard", "git clean -fd static/"):
        assert OPL.reset_guard_violations(cmd), f"real command no longer blocks: {cmd}"


def test_a_destructive_command_after_a_quoted_message_still_blocks():
    """Stripping the quoted payload must not swallow what follows it."""
    chained = "git commit -m 'notes' && git checkout -- server.py"
    assert OPL.reset_guard_violations(chained), (
        "the destructive command after the quoted message is dropped with the message payload"
    )


def test_live_path_wired_through_guard():
    """The guard's Shell path carries the reset-guard — the live BLOCK site."""
    for cmd in (
        "git restore -- static/chart.html",
        "git stash push -q -m probe -- stream_spine.py",
    ):
        bad = PLG.pretooluse_block("Bash", {"command": cmd})
        assert any("RESET_GUARD" in b for b in bad), (
            f"reset guard not on the live PreToolUse path: {cmd}"
        )


# ── Adjudicated by what the command can DESTROY: the class rule is judged per statement, ────
# the globals prefix admits `-C <path>`, the push clause admits `-f` and flags after the refspec.

#: (command, must_block, what it can reach). One table, both directions.
_ADJUDICATION: tuple[tuple[str, bool, str], ...] = (
    # SAFE — cannot reach operator work
    ("git reset --soft HEAD~1", False, "HEAD only"),
    ("git reset --soft origin/main", False, "HEAD only"),
    ("git reset --soft", False, "HEAD only"),
    ("git -C ../other reset --soft HEAD~1", False, "HEAD only, another checkout"),
    ("git restore --staged tools/x.py", False, "index only"),
    ("git stash list", False, "read"),
    ("git checkout -b feat/x", False, "creates a branch"),
    ("git clean -n", False, "dry run"),
    ("git push --force-with-lease origin main", False, "refuses to clobber unseen work"),
    ("git push -u origin feat/x", False, "no force flag"),
    ("git push origin feat/x --follow-tags", False, "no force flag"),
    ("git status", False, "read"),
    # DESTRUCTIVE — every mode that can discard something
    ("git reset --hard", True, "index + worktree"),
    ("git reset --hard HEAD~1", True, "index + worktree + commit"),
    ("git reset --mixed HEAD~1", True, "the index"),
    ("git reset HEAD~1", True, "the index (--mixed is the default)"),
    ("git reset --keep HEAD~1", True, "local changes"),
    ("git reset --merge HEAD~1", True, "merge state"),
    ("git reset -- static/chart.html", True, "the index of a product file"),
    ("git clean -fd", True, "untracked files"),
    ("git clean -xfd", True, "untracked + ignored"),
    ("git checkout -- .", True, "whole worktree"),
    ("git checkout -- server.py", True, "a product file"),
    ("git restore .", True, "whole worktree"),
    ("git stash", True, "moves the worktree away"),
    ("git stash push -q -m probe -- stream_spine.py", True, "a product file on no wipe list"),
    (
        "git stash push -- app/market_data/schwab/streaming/capture.py",
        True,
        "a product file on no wipe list",
    ),
    ("git stash pop", True, "rewrites the worktree"),
    ("git stash apply", True, "rewrites the worktree"),
    ("git stash drop", True, "deletes a stash"),
    ("git stash show -p stash@{0}", True, "AGENTS.md: never git stash; only `stash list` reads"),
    ("git -C ../other stash push -- stream_spine.py", True, "another checkout's product file"),
    ("git push -f origin main", True, "remote history"),
    ("git push origin main -f", True, "remote history, flag after the refspec"),
    ("git push --force origin main", True, "remote history"),
    ("git -C ../other reset --hard", True, "another checkout entirely"),
    ("git -C ../other push --force origin main", True, "another checkout's remote history"),
    ("git --git-dir=../x/.git --work-tree=../x reset --hard", True, "explicit dirs"),
)


def test_git_is_adjudicated_by_what_it_can_destroy():
    """Both directions in one table: safe forms pass, every destructive mode still blocks."""
    wrong = [
        (cmd, reaches)
        for cmd, must_block, reaches in _ADJUDICATION
        if bool(OPL.reset_guard_violations(cmd)) != must_block
    ]
    assert wrong == [], f"verdict disagrees with what the command can destroy: {wrong}"


def test_a_safe_form_cannot_launder_a_destructive_one():
    """The class rule is judged per statement: a safe form exempts only itself, never a
    destructive statement chained after it."""
    for chain in (
        "git reset --soft HEAD~1 && git clean -fd",
        "git reset --soft HEAD~1 && git reset --mixed HEAD~1",
        "git restore --staged x.py && git reset --mixed HEAD~1",
        "git stash list ; git restore .",
        "git checkout -b feat/x && git checkout -- server.py",
        "git status | cat && git stash",
    ):
        assert OPL.reset_guard_violations(chain), f"a safe form laundered the chain: {chain}"
    # ...and a chain that is safe end to end stays legal.
    assert not OPL.reset_guard_violations("git status && git reset --soft HEAD~1")
    assert not OPL.reset_guard_violations("git fetch origin && git reset --soft origin/main")


def test_an_interpreter_heredoc_is_judged_per_line():
    """A heredoc handed to a shell IS the instruction, so a CLASS form inside it
    (not only a hard form) still blocks, and a quoted commit message stays prose."""
    assert OPL.reset_guard_violations("bash <<'EOF'\ngit status\ngit restore .\nEOF")
    assert not OPL.reset_guard_violations(
        "git commit -m 'RC-231: git restore . wiped the tree' && git push origin feat/x"
    )


def test_the_safe_reset_is_live_on_the_pretooluse_path():
    """The seam that actually runs: the reset guard lets --soft through and still refuses --hard.

    Asserted on the RESET_GUARD verdict, not on an empty result: the Bash seam also carries
    PROD_CHECKOUT_LOCK, which legitimately refuses HEAD-moving git in the production primary
    checkout, and a control whose verdict depends on which checkout it runs in is testing the
    topology, not the law.
    """
    soft = PLG.pretooluse_block("Bash", {"command": "git reset --soft HEAD~1"})
    assert not any("RESET_GUARD" in b for b in soft), (
        f"the reset guard still refuses a reset that cannot touch index or worktree: {soft}"
    )
    hard = PLG.pretooluse_block("Bash", {"command": "git reset --hard HEAD~1"})
    assert any("RESET_GUARD" in b for b in hard), "the destructive form stopped blocking"


def test_git_named_by_its_full_path_or_exe_is_judged_as_git():
    """git given by its path or with `.exe` (`& C:\\Git\\cmd\\git.exe reset --hard`) is git."""
    for tool, cmd in (
        ("PowerShell", "& C:\\Git\\cmd\\git.exe reset --hard"),
        ("PowerShell", '& "C:\\Program Files\\Git\\cmd\\git.exe" reset --hard HEAD~1'),
        ("Bash", "C:/Git/cmd/git.exe stash"),
        ("Bash", "/usr/bin/git checkout -- server.py"),
    ):
        assert any("RESET_GUARD" in b for b in PLG.pretooluse_block(tool, {"command": cmd})), cmd
    for cmd in ("& C:\\Git\\cmd\\git.exe reset --soft HEAD~1", "C:/Git/cmd/git.exe stash list"):
        assert not OPL.reset_guard_violations(cmd), cmd
    assert PLG.git_subcommand(["C:\\Git\\cmd\\git.exe", "push", "origin", "main"])[0] == "push"


def test_a_heredoc_handed_to_an_interpreter_by_its_full_path_is_judged():
    """A heredoc handed to bash by its path (`C:\\Git\\bin\\bash.exe <<'EOF'`) is judged as
    bash's."""
    for shell in (
        "C:\\Git\\bin\\bash.exe",
        "/usr/bin/bash",
        '"C:\\Program Files\\Git\\bin\\bash.exe"',
        "sudo bash",
    ):
        assert OPL.reset_guard_violations(f"{shell} <<'EOF'\ngit status\ngit reset --hard\nEOF"), (
            shell
        )
    assert not OPL.reset_guard_violations(
        "C:\\Git\\cmd\\git.exe commit -F - <<'MSG'\ngit reset --hard wiped it\nMSG"
    )
