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


# The isolation mechanics are pinned with an explicit policy so they stay proven
# regardless of which mode the shipped policy file declares (RC-129).
_ISOLATED = {"env_role_var": "ED_AGENT_ROLE", "claude_root_suffix": "-Claude",
             "mode": "isolated"}
_SHARED = {"env_role_var": "ED_AGENT_ROLE", "claude_root_suffix": "-Claude",
           "mode": "shared-root"}


def test_boundary_rejects_role_path_mismatch():
    v = worktree_boundary_violations(
        repo=Path("C:/repo/EdWebConsole"),
        env={"ED_AGENT_ROLE": "claude"},
        policy=_ISOLATED,
    )
    assert v and "ED_AGENT_ROLE=claude" in v[0]
    v2 = worktree_boundary_violations(
        repo=Path("C:/repo/EdWebConsole-Claude"),
        env={"ED_AGENT_ROLE": "cursor"},
        policy=_ISOLATED,
    )
    assert v2 and "ED_AGENT_ROLE=cursor" in v2[0]


def test_matching_cursor_role_on_primary_has_no_path_error():
    v = worktree_boundary_violations(
        repo=Path("C:/repo/EdWebConsole"),
        env={"ED_AGENT_ROLE": "cursor"},
        policy=_ISOLATED,
    )
    assert v == []


# ── RC-129: shared-root mode — the operator-decided arrangement ──────────────────────────────

def test_shared_root_mode_admits_both_roles_in_the_primary_checkout():
    for role in ("claude", "cursor"):
        v = worktree_boundary_violations(
            repo=Path("C:/repo/EdWebConsole"),
            env={"ED_AGENT_ROLE": role},
            policy=_SHARED,
        )
        assert v == [], f"shared-root mode must admit role={role} in the primary root: {v}"


def test_shared_root_mode_still_requires_an_explicit_role():
    """Negative control: mode relaxes the PATH binding only — silent role inference stays
    fatal, because that is what hid mis-routed agents (2026-07-25)."""
    v = worktree_boundary_violations(
        repo=Path("C:/repo/EdWebConsole"),
        env={},
        policy=_SHARED,
    )
    assert v and "not set" in v[0]


def test_shared_root_mode_does_not_touch_the_dirty_source_block():
    """Negative control: the REAL handoff hazard — uncommitted protected source invisible
    to the other agent — must block in every mode. dirty_protected_paths has no mode
    parameter at all; this pins that a dirty server.py is still reported."""
    lines = [" M server.py", " M reports/noise.jsonl"]
    assert dirty_protected_paths(lines) == ["server.py"]


def test_shipped_policy_declares_its_mode_with_a_reason():
    """The shipped file must say WHICH mode and WHY (notes law) — an undeclared mode is
    exactly the silent default the gate exists to ban."""
    import json
    policy = json.loads(Path("tools/agent_worktree_policy.json").read_text(encoding="utf-8"))
    assert policy.get("mode") in ("isolated", "shared-root")
    if policy["mode"] == "shared-root":
        assert "RC-129" in str(policy.get("mode_reason", "")), (
            "shared-root without its RC-129 rationale — the next reader cannot challenge it"
        )
