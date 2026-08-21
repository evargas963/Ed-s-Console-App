"""Negative controls for the isolated-worktree edit boundary (operator 2026-08-20).

In `mode: isolated`, ED_AGENT_ROLE=claude must not mutate application source inside the
PRODUCTION (primary) checkout; Claude edits only its own `<primary>-Claude` worktree. This
guard (OPL.claude_isolated_edit_violation, wired into process_lock_guard PreToolUse) makes
that mechanical. Green-and-inert is indistinguishable from green-and-working, so each control
INJECTS the case and asserts BLOCK vs ALLOW.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.operating_process_lock as OPL

# Absolute on BOTH Windows and POSIX. A `C:/...` literal is absolute on Windows but a
# RELATIVE path on Linux, where the guard would join it under the runner's cwd and mis-block
# (the CI failure this fixes). tempdir is absolute on every platform; the paths need not exist.
_BASE = Path(tempfile.gettempdir()).resolve()
PRIMARY = _BASE / "EdWebConsole"
CLAUDE = _BASE / "EdWebConsole-Claude"
ISO = {"mode": "isolated", "env_role_var": "ED_AGENT_ROLE", "claude_root_suffix": "-Claude"}
SHARED = {**ISO, "mode": "shared-root"}
CLAUDE_ENV = {"ED_AGENT_ROLE": "claude"}
CURSOR_ENV = {"ED_AGENT_ROLE": "cursor"}


def _v(target, repo, env, policy):
    return OPL.claude_isolated_edit_violation(
        target_path=str(target), repo=repo, env=env, policy=policy)


def test_control1_claude_edit_in_primary_is_blocked():
    """Claude + primary checkout + APP-file edit -> BLOCKED."""
    assert _v(PRIMARY / "server.py", PRIMARY, CLAUDE_ENV, ISO) is not None


def test_control2_claude_edit_in_claude_worktree_is_allowed():
    """Claude + Claude worktree + same APP-file edit -> ALLOWED (hook running from primary)."""
    assert _v(CLAUDE / "server.py", PRIMARY, CLAUDE_ENV, ISO) is None


def test_sibling_prefix_is_not_containment():
    """EdWebConsole-Claude is a SIBLING of EdWebConsole, never 'under' it (no string-prefix bug)."""
    assert not (CLAUDE / "server.py").is_relative_to(PRIMARY)


def test_shared_root_mode_does_not_enforce():
    """Legacy shared-root (RC-129) leaves the boundary off — no regression for that mode."""
    assert _v(PRIMARY / "server.py", PRIMARY, CLAUDE_ENV, SHARED) is None


def test_cursor_role_is_unaffected():
    """The boundary binds the claude role only; cursor owns the primary."""
    assert _v(PRIMARY / "server.py", PRIMARY, CURSOR_ENV, ISO) is None


def test_hook_running_from_claude_worktree_allows_its_own_tree():
    """When the hook itself runs from a -Claude worktree, edits under it are Claude's own."""
    assert _v(CLAUDE / "server.py", CLAUDE, CLAUDE_ENV, ISO) is None


def test_missing_role_does_not_block():
    """No ED_AGENT_ROLE -> this guard is silent (require_role handles the fail-closed elsewhere)."""
    assert _v(PRIMARY / "server.py", PRIMARY, {}, ISO) is None
