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
    assert not OPL.reset_guard_violations("git reset -- static/chart.html")
    go.write_text('{"granted": false, "scope": []}', encoding="utf-8")
    monkeypatch.setenv("ED_RESET_GUARD", "off")
    assert not OPL.reset_guard_violations("git reset -- static/chart.html")


def test_live_path_wired_through_guard(monkeypatch, tmp_path):
    """The guard's Shell path carries the reset-guard — the live BLOCK site."""
    _no_escape(monkeypatch, tmp_path)
    bad = PLG.pretooluse_block("Bash", {"command": "git restore -- static/chart.html"})
    assert any("RESET_GUARD" in b for b in bad), "reset guard not on the live PreToolUse path"
