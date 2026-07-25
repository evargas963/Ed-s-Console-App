"""Seams for the Git-shaped multi-agent handoff + worktree boundary gate."""
from pathlib import Path

from tools.check_worktree_handoff import (
    dirty_protected_paths,
    infer_role,
    is_protected_source,
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


def test_infer_role_from_suffix_and_env():
    assert infer_role(Path("EdWebConsole"), env={}) == "cursor"
    assert infer_role(Path("EdWebConsole-Claude"), env={}) == "claude"
    assert infer_role(Path("EdWebConsole"), env={"ED_AGENT_ROLE": "claude"}) == "claude"
    assert infer_role(Path("EdWebConsole-Claude"), env={"ED_AGENT_ROLE": "cursor"}) == "cursor"


def test_boundary_rejects_role_mismatch():
    # Claude role in a non-Claude folder
    v = worktree_boundary_violations(
        repo=Path("C:/repo/EdWebConsole"),
        env={"ED_AGENT_ROLE": "claude"},
    )
    assert v and "role=claude" in v[0]
    # Cursor role inside a *-Claude folder
    v2 = worktree_boundary_violations(
        repo=Path("C:/repo/EdWebConsole-Claude"),
        env={"ED_AGENT_ROLE": "cursor"},
    )
    assert v2 and "role=cursor" in v2[0]
