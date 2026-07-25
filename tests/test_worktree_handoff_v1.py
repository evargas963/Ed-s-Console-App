"""Seams for the Git-shaped multi-agent handoff gate."""
from tools.check_worktree_handoff import dirty_protected_paths, is_protected_source


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
