"""Seams for the Git-shaped multi-agent handoff + worktree boundary gate."""
from pathlib import Path

from tools.check_worktree_handoff import (
    dirty_protected_paths,
    is_protected_source,
    require_role,
    worktree_boundary_violations,
)


def test_protected_source_patterns():
    assert is_protected_source("server.py")
    assert is_protected_source("tools/check_worktree_handoff.py")
    assert is_protected_source("static/chart.html")
    assert is_protected_source("AGENTS.md")
    assert is_protected_source("governance/root_cause_log.md")
    assert not is_protected_source("reports/flip_drift_log.jsonl")
    assert not is_protected_source("MEMORY.md")
    assert not is_protected_source("README.md")


def test_dirty_protected_paths_from_porcelain():
    lines = [
        " M server.py",
        " M reports/stream_capture_status.json",
        "?? tools/check_worktree_handoff.py",
        "?? reports/noise.jsonl",
        "R  old_name.py -> static/chart.html",
    ]
    assert dirty_protected_paths(lines) == [
        "old_name.py",
        "server.py",
        "static/chart.html",
        "tools/check_worktree_handoff.py",
    ]


def test_missing_role_is_fatal_no_silent_default():
    role, err = require_role(env={})
    assert role is None
    assert err and "not set" in err
    v = worktree_boundary_violations(
        repo=Path("EdWebConsole"),
        env={},
    )
    assert v and "FATAL" in v[0] and "not set" in v[0]


def test_invalid_role_is_fatal():
    role, err = require_role(env={"ED_AGENT_ROLE": "agent"})
    assert role is None and err and "invalid" in err


def test_boundary_rejects_role_path_mismatch():
    v = worktree_boundary_violations(
        repo=Path("C:/repo/EdWebConsole"),
        env={"ED_AGENT_ROLE": "claude"},
    )
    assert v and "ED_AGENT_ROLE=claude" in v[0]
    v2 = worktree_boundary_violations(
        repo=Path("C:/repo/EdWebConsole-Claude"),
        env={"ED_AGENT_ROLE": "cursor"},
    )
    assert v2 and "ED_AGENT_ROLE=cursor" in v2[0]


def test_matching_cursor_role_on_primary_has_no_path_error():
    v = worktree_boundary_violations(
        repo=Path("C:/repo/EdWebConsole"),
        env={"ED_AGENT_ROLE": "cursor"},
    )
    assert v == []
