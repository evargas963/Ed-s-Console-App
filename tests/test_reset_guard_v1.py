# institutional-synthetic-ok: inject destructive git commands to prove LOCK-2 BLOCKs.
"""LOCK-2 reset-guard (RC-231/RC-232) — dedicated acceptance suite.

The tree-destructive git CLASS blocks at PreToolUse: reset, restore, checkout --,
clean, stash — against protected/mission scope or in bare whole-tree form. Safe and
read-only forms stay legal; escapes are explicit and operator-visible.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.operating_process_lock as OPL  # noqa: E402
import tools.process_lock_guard as PLG  # noqa: E402


def _no_escape(monkeypatch, tmp_path):
    # 2026-08-24 teardown: the operator_go grant file is GONE — the only residual
    # escape vector is the env var, which must also not disarm the guard.
    monkeypatch.delenv("ED_RESET_GUARD", raising=False)


def test_spec_case_reset_double_dash_chart_blocks(monkeypatch, tmp_path):
    """Spec acceptance literal: `git reset -- static/chart.html` → BLOCK."""
    _no_escape(monkeypatch, tmp_path)
    assert OPL.reset_guard_violations("git reset -- static/chart.html")


def test_spec_case_git_status_allows(monkeypatch, tmp_path):
    """Spec acceptance literal: `git status` → allow."""
    _no_escape(monkeypatch, tmp_path)
    assert not OPL.reset_guard_violations("git status")


def test_destructive_class_blocks(monkeypatch, tmp_path):
    _no_escape(monkeypatch, tmp_path)
    for cmd in (
        "git restore -- server.py",
        "git checkout -- static/chart.html",
        "git checkout HEAD -- db.py",
        "git reset --hard",
        "git clean -fd",
        "git stash",
    ):
        assert OPL.reset_guard_violations(cmd), f"LOCK-2 silent on: {cmd}"


def test_safe_forms_allow(monkeypatch, tmp_path):
    _no_escape(monkeypatch, tmp_path)
    for cmd in (
        "git log --oneline -5",
        "git diff HEAD -- server.py",
        "git restore --staged governance/root_cause_log.md",
        "git stash list",
        "git checkout -b feature/next",
        "git clean -n",
    ):
        assert not OPL.reset_guard_violations(cmd), f"LOCK-2 false-fired on: {cmd}"


def test_escapes_are_explicit(monkeypatch, tmp_path):
    """No grant file exists any more (2026-08-24 teardown) and the env token never
    disarmed the guard (RC-450) — both directions still BLOCK."""
    monkeypatch.delenv("ED_RESET_GUARD", raising=False)
    assert OPL.reset_guard_violations("git reset -- static/chart.html")
    monkeypatch.setenv("ED_RESET_GUARD", "off")
    assert OPL.reset_guard_violations("git reset -- static/chart.html")


# ── RC-253: judge the ACTION, not the data the command carries (RC-93) ──────────────────
# LOCK-2 blocked a `git commit` because the MESSAGE described a wipe. It fired hardest on the
# most precise incident write-ups, which pressures every future writer toward vaguer accounts
# of exactly the incidents this ledger exists to record.


def test_rc253_commit_message_quoting_destructive_git_is_not_an_action(monkeypatch, tmp_path):
    _no_escape(monkeypatch, tmp_path)
    heredoc = (
        "git commit --file - <<'MSG'\n"
        "RC-252: the guard was silent on git restore -- static/chart.html\n"
        "and on git checkout -- server.py, so product files were wipeable.\n"
        "Also proved git reset --hard still blocks.\n"
        "MSG"
    )
    assert not OPL.reset_guard_violations(heredoc), (
        "LOCK-2 blocked a commit whose only destructive git is prose in the message — this is "
        "the RC-93 inversion: banning the word, not the action"
    )
    inline = "git commit -m 'RC-231 was opened after a git reset --hard wiped static/chart.html'"
    assert not OPL.reset_guard_violations(inline)


def test_rc253_stripping_payloads_does_not_open_a_bypass(monkeypatch, tmp_path):
    """The exemption is for DATA. A body handed to an interpreter is the instruction, and a
    real destructive command is unaffected by any of this."""
    _no_escape(monkeypatch, tmp_path)
    piped = "bash <<'EOF'\ngit reset --hard\nEOF"
    assert OPL.reset_guard_violations(piped), (
        "a heredoc piped into a shell IS the instruction — stripping it would be a bypass"
    )
    for cmd in ("git restore -- server.py", "git reset --hard", "git clean -fd static/"):
        assert OPL.reset_guard_violations(cmd), f"real command no longer blocks: {cmd}"


def test_rc253_a_destructive_command_after_a_quoted_message_still_blocks(monkeypatch, tmp_path):
    """Stripping the quoted payload must not swallow what follows it."""
    _no_escape(monkeypatch, tmp_path)
    chained = "git commit -m 'notes' && git checkout -- server.py"
    assert OPL.reset_guard_violations(chained), (
        "the second, genuinely destructive command was lost with the message payload"
    )


def test_live_path_wired_through_guard(monkeypatch, tmp_path):
    """The guard's Shell path carries the reset-guard — the live BLOCK site."""
    _no_escape(monkeypatch, tmp_path)
    bad = PLG.pretooluse_block("Bash", {"command": "git restore -- static/chart.html"})
    assert any("RESET_GUARD" in b for b in bad), "reset guard not on the live PreToolUse path"
# ── RC-508: adjudicated by what the command can DESTROY, not by the word `reset` ──────────
# `git reset --soft` moves HEAD and leaves the index and working tree exactly as they were,
# so no operator work is reachable by it — yet every spelling of it was blocked, while this
# repository's OWN merge authority (check_delta_adds_no_debt) runs it to stage the candidate
# delta. MEASURED 2026-09-03: all reset modes blocked; the ONLY wrong verdicts were the three
# --soft spellings. Adding it to the allowlist was only safe once the class rule was judged
# PER SEGMENT, because the allowlist had been searched across the whole command.

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
    ("git status", False, "read"),
    # DESTRUCTIVE — every mode that can discard something
    ("git reset --hard", True, "index + worktree"),
    ("git reset --hard HEAD~1", True, "index + worktree + commit"),
    ("git reset --mixed HEAD~1", True, "the index"),
    ("git reset HEAD~1", True, "the index (--mixed is the default)"),
    ("git reset --keep HEAD~1", True, "local changes"),
    ("git reset --merge HEAD~1", True, "merge state"),
    ("git clean -fd", True, "untracked files"),
    ("git clean -xfd", True, "untracked + ignored"),
    ("git checkout -- .", True, "whole worktree"),
    ("git checkout -- server.py", True, "a product file"),
    ("git restore .", True, "whole worktree"),
    ("git stash", True, "moves the worktree away"),
    ("git push -f origin main", True, "remote history"),
    ("git push --force origin main", True, "remote history"),
    ("git -C ../other reset --hard", True, "another checkout entirely"),
)


def test_rc508_reset_is_adjudicated_by_what_it_can_destroy(monkeypatch, tmp_path):
    """Both directions in one table: safe forms pass, every destructive mode still blocks."""
    _no_escape(monkeypatch, tmp_path)
    wrong = [(cmd, reaches) for cmd, must_block, reaches in _ADJUDICATION
             if bool(OPL.reset_guard_violations(cmd)) != must_block]
    assert wrong == [], f"verdict disagrees with what the command can destroy: {wrong}"


def test_rc508_a_safe_form_cannot_launder_a_destructive_one(monkeypatch, tmp_path):
    """THE REASON the allowlist is judged per segment.

    The safe list used to be searched across the WHOLE command, so one safe form anywhere
    exempted everything chained after it. That was a live hole BEFORE `reset --soft` was
    added — `git restore --staged x.py && git reset --mixed HEAD~1` was waved through — and
    adding a new safe form without fixing it would have widened the hole rather than closed
    a false positive.
    """
    _no_escape(monkeypatch, tmp_path)
    for chain in (
        "git reset --soft HEAD~1 && git clean -fd",
        "git reset --soft HEAD~1 && git reset --mixed HEAD~1",
        "git restore --staged x.py && git reset --mixed HEAD~1",   # the pre-existing hole
        "git stash list ; git restore .",
        "git checkout -b feat/x && git checkout -- server.py",
    ):
        assert OPL.reset_guard_violations(chain), f"a safe form laundered the chain: {chain}"
    # ...and a chain that is safe end to end stays legal, or the fix would be a new over-block.
    assert not OPL.reset_guard_violations("git status && git reset --soft HEAD~1")
    assert not OPL.reset_guard_violations("git fetch origin && git reset --soft origin/main")


def test_rc508_the_safe_reset_is_live_on_the_pretooluse_path(monkeypatch, tmp_path):
    """The seam that actually runs, not just the predicate: --soft passes, --hard blocks."""
    _no_escape(monkeypatch, tmp_path)
    assert PLG.pretooluse_block("Bash", {"command": "git reset --soft HEAD~1"}) == []
    bad = PLG.pretooluse_block("Bash", {"command": "git reset --hard HEAD~1"})
    assert any("RESET_GUARD" in b for b in bad), "the destructive form stopped blocking"


def test_rc508_the_segment_splitter_has_one_owner():
    """ONE FAUCET: the chain splitter is consumed from operator_law_guard, not re-written."""
    import inspect

    src = inspect.getsource(OPL._command_segments)
    assert "iter_command_segments" in src, "the segment splitter was re-implemented here"
    from tools.operator_law_guard import iter_command_segments
    assert [s for _c, s in iter_command_segments("git status && git reset --soft HEAD~1", "")]
