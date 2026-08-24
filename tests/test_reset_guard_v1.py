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
    monkeypatch.delenv("ED_RESET_GUARD", raising=False)
    go = tmp_path / "go.json"
    go.write_text('{"granted": false, "scope": []}', encoding="utf-8")
    monkeypatch.setattr(OPL, "OPERATOR_GO_PATH", go)


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
    go = tmp_path / "go.json"
    monkeypatch.setattr(OPL, "OPERATOR_GO_PATH", go)
    go.write_text('{"granted": true, "scope": ["git_reset_product"]}', encoding="utf-8")
    monkeypatch.delenv("ED_RESET_GUARD", raising=False)
    assert OPL.reset_guard_violations("git reset -- static/chart.html")
    go.write_text('{"granted": false, "scope": []}', encoding="utf-8")
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
