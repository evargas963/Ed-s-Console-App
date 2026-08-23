# institutional-synthetic-ok: inject index≠WT and sole-writer violations to prove RC-217 BLOCKs.
"""Operating process lock — negative controls + quiet paths (RC-217)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.operating_process_lock as OPL  # noqa: E402
import tools.process_lock_guard as PLG  # noqa: E402


def _init_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "governance").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tools").mkdir(parents=True, exist_ok=True)
    checker = tmp_path / "tools" / "check_institutional_correctness.py"
    checker.write_text(
        'CHECKS = [\n    ("old_check", None, True),\n]\n',
        encoding="utf-8",
    )
    (tmp_path / "db.py").write_text("# RC-183\nis_collect_window_bar_end_ts_utc\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


def test_sole_writer_blocks_cursor_on_db():
    msg = OPL.sole_writer_edit_violation("db.py", agent="cursor")
    assert msg and (
        "sole_writer" in msg or "PM-FIRST" in msg or "WRITER-DRIFT" in msg or "SOD_DRIFT" in msg
    )


def test_sole_writer_allows_writer_agent(monkeypatch, tmp_path):
    # Pin the mission: the live pm_mission.json scopes the writer to the CURRENT mission's
    # paths, so this permits-check must supply its own all-scope mission rather than
    # inherit ambient state (same defect class as ambient ED_AGENT_ROLE).
    mission = tmp_path / "pm_mission.json"
    mission.write_text(
        '{"status": "active", "writer": "claude", "scope_paths": ["*"], "mission_id": "t"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(OPL, "PM_MISSION_PATH", mission)
    assert OPL.sole_writer_edit_violation("db.py", agent="claude") is None


def test_sole_writer_allows_governance_process_files():
    assert OPL.sole_writer_edit_violation("governance/sole_writer.json", agent="cursor") is None


def test_index_worktree_mismatch_detected(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    checker = repo / "tools" / "check_institutional_correctness.py"
    checker.write_text(checker.read_text(encoding="utf-8") + "\n# wt delta\n", encoding="utf-8")
    monkeypatch.chdir(repo)
    mism = OPL.index_worktree_mismatches(repo)
    assert any("index≠WT" in m or "worktree=" in m for m in mism)


def test_index_parity_passes_when_clean(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    monkeypatch.chdir(repo)
    assert OPL.index_worktree_mismatches(repo) == []


def test_staged_checks_not_on_head_flags_delta(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    checker = repo / "tools" / "check_institutional_correctness.py"
    checker.write_text(
        'CHECKS = [\n    ("old_check", None, True),\n    ("new_lock", None, True),\n]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", checker], cwd=repo, check=True, capture_output=True)
    monkeypatch.chdir(repo)
    v = OPL.staged_enforced_checks_not_on_head(repo)
    assert v and "new_lock" in v[0]


def test_operator_go_suppresses_staged_check_block(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    go = repo / "governance" / "operator_go.json"
    go.write_text(
        json.dumps({"granted": True, "scope": ["staged_lock_surface"]}),
        encoding="utf-8",
    )
    checker = repo / "tools" / "check_institutional_correctness.py"
    checker.write_text(
        'CHECKS = [\n    ("brand_new", None, True),\n]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", checker], cwd=repo, check=True, capture_output=True)
    monkeypatch.setattr(OPL, "OPERATOR_GO_PATH", go)
    assert OPL.operator_go_granted("staged_lock_surface")
    assert OPL.commit_violations(repo) == [] or not any("brand_new" in x for x in OPL.commit_violations(repo))


def test_operator_go_grant_does_not_leak_to_unrelated_scopes(tmp_path, monkeypatch):
    """RC-402: a grant of staged_lock_surface must NOT permit every other scope.

    This is the deny-side control the predicate never had. Before the fix,
    `staged_lock_surface` in the grant made every scope query return True, which
    silently disarmed reset_guard_violations("git_reset_product").
    """
    go = tmp_path / "operator_go.json"
    go.write_text(
        json.dumps({"granted": True, "scope": ["rc_status_vocabulary", "staged_lock_surface"]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(OPL, "OPERATOR_GO_PATH", go)
    # ALLOW side: the two granted scopes resolve True.
    assert OPL.operator_go_granted("staged_lock_surface")
    assert OPL.operator_go_granted("rc_status_vocabulary")
    # DENY side: scopes the operator never granted must be False.
    assert not OPL.operator_go_granted("git_reset_product")
    assert not OPL.operator_go_granted("bogus")
    assert not OPL.operator_go_granted("all")


def test_reset_guard_is_not_disarmed_by_the_staged_lock_grant(tmp_path, monkeypatch):
    """RC-402: the concrete blast radius — LOCK-2 must still fire under this grant."""
    go = tmp_path / "operator_go.json"
    go.write_text(
        json.dumps({"granted": True, "scope": ["rc_status_vocabulary", "staged_lock_surface"]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(OPL, "OPERATOR_GO_PATH", go)
    monkeypatch.delenv("ED_RESET_GUARD", raising=False)
    protected = OPL.PROTECTED_PATHS[0]
    v = OPL.reset_guard_violations(f"git reset --hard HEAD -- {protected}")
    assert v, "reset guard was waved through despite only a staged_lock_surface grant"


def test_completion_claim_blocks_on_index_mismatch(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    checker = repo / "tools" / "check_institutional_correctness.py"
    checker.write_text(checker.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")
    monkeypatch.setattr(OPL, "REPO", repo)
    text = "We have one intentional tree ready to commit — all green."
    v = OPL.completion_claim_violations(text, repo)
    assert v and any("index≠WT" in x or "worktree" in x for x in v)


def test_live_claim_requires_disk_only_token_when_disk_only(monkeypatch):
    monkeypatch.setattr(
        OPL,
        "live_collect_disk_only",
        lambda repo=None, port=8000: "DISK_ONLY: pid old",
    )
    monkeypatch.setattr(OPL, "index_worktree_mismatches", lambda repo=None, **kw: [])
    bad = OPL.completion_claim_violations("Collect gate is LIVE_ENFORCED now.", OPL.REPO)
    assert bad and "LIVE_ENFORCED" in bad[0] or "DISK_ONLY" in bad[0]
    ok = OPL.completion_claim_violations(
        "DISK_ONLY_UNTIL_RESTART — gate on disk only.", OPL.REPO
    )
    assert not any("LIVE_ENFORCED" in x for x in ok)


def test_pretooluse_hook_blocks_sole_writer_edit(monkeypatch):
    # Pin the role: the block is for the NON-writer. Ambient env now declares the real
    # agent (ED_AGENT_ROLE=claude in .claude/settings.json), so the test must not inherit it.
    monkeypatch.setenv("ED_AGENT_ROLE", "cursor")
    bad = PLG.pretooluse_block("Write", {"file_path": str(ROOT / "db.py")})
    assert bad and any(
        "sole_writer" in b or "PM-FIRST" in b or "WRITER-DRIFT" in b or "SOD_DRIFT" in b
        for b in bad
    )


def test_pretooluse_hook_permits_sole_writer_edit(monkeypatch, tmp_path):
    # The named writer is NOT blocked on the same protected path (RC-217 negative control).
    # Role AND mission both pinned — ambient env/mission state must not leak in.
    monkeypatch.setenv("ED_AGENT_ROLE", "claude")
    mission = tmp_path / "pm_mission.json"
    mission.write_text(
        '{"status": "active", "writer": "claude", "scope_paths": ["*"], "mission_id": "t"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(OPL, "PM_MISSION_PATH", mission)
    bad = PLG.pretooluse_block("Write", {"file_path": str(ROOT / "db.py")})
    assert not [b for b in bad if "sole_writer" in b or "PM-FIRST" in b]


def test_pm_mission_idle_blocks_product_edit(monkeypatch, tmp_path):
    monkeypatch.setenv("ED_AGENT_ROLE", "claude")
    monkeypatch.delenv("ED_PM_MISSION_GUARD", raising=False)
    mission = tmp_path / "pm_mission.json"
    mission.write_text('{"status": "idle", "writer": "claude", "scope_paths": ["*"]}', encoding="utf-8")
    monkeypatch.setattr(OPL, "PM_MISSION_PATH", mission)
    msg = OPL.pm_mission_edit_violation("db.py", agent="claude")
    assert msg and "PM-FIRST" in msg and "idle" in msg


def test_pm_mission_active_allows_scoped_writer(monkeypatch, tmp_path):
    monkeypatch.setenv("ED_AGENT_ROLE", "claude")
    mission = tmp_path / "pm_mission.json"
    mission.write_text(
        json.dumps(
            {
                "status": "active",
                "writer": "claude",
                "scope_paths": ["static/"],
                "mission_id": "ui-test",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(OPL, "PM_MISSION_PATH", mission)
    assert OPL.pm_mission_edit_violation("static/index.html", agent="claude") is None
    assert OPL.pm_mission_edit_violation("db.py", agent="claude") is not None


def test_reset_guard_blocks_destructive_git_on_product(monkeypatch, tmp_path):
    """LOCK-2 (RC-231): soft tree-destructive git against product scope BLOCKS.

    RC-252 pins PM_MISSION_PATH to an EMPTY scope. This test used to leave it pointed at the
    live mission file, so it asserted the guard AND today's configuration together — and passed
    for weeks only because the missions of those weeks happened to name these paths. With an
    empty mission, the only thing that can satisfy it is the guard's own static inventory.
    """
    monkeypatch.delenv("ED_RESET_GUARD", raising=False)
    go = tmp_path / "go.json"
    go.write_text('{"granted": false, "scope": []}', encoding="utf-8")
    monkeypatch.setattr(OPL, "OPERATOR_GO_PATH", go)
    mission = tmp_path / "mission.json"
    mission.write_text('{"mission_id": "empty", "scope_paths": []}', encoding="utf-8")
    monkeypatch.setattr(OPL, "PM_MISSION_PATH", mission)
    for cmd in ("git restore -- static/chart.html",
                "git checkout -- server.py",
                "git restore -- math_levels.py",
                "git checkout -- math_exposure_core.py",
                "git clean -fd static/",
                "git reset --hard",
                "git stash"):
        assert OPL.reset_guard_violations(cmd), f"reset guard silent on: {cmd}"


def test_reset_guard_permits_safe_git(monkeypatch, tmp_path):
    """LOCK-2 negative control: index-only and read-only git stays legal."""
    monkeypatch.delenv("ED_RESET_GUARD", raising=False)
    go = tmp_path / "go.json"
    go.write_text('{"granted": false, "scope": []}', encoding="utf-8")
    monkeypatch.setattr(OPL, "OPERATOR_GO_PATH", go)
    for cmd in ("git status", "git log --oneline -3",
                "git restore --staged governance/root_cause_log.md",
                "git stash list", "git checkout -b feature/x"):
        assert not OPL.reset_guard_violations(cmd), f"reset guard false-fired on: {cmd}"


def test_reset_guard_escapes_do_not_disable(monkeypatch, tmp_path):
    """Architecture A: ED_RESET_GUARD=off and operator_go git_reset_product still BLOCK."""
    go = tmp_path / "go.json"
    go.write_text('{"granted": true, "scope": ["git_reset_product"]}', encoding="utf-8")
    monkeypatch.setattr(OPL, "OPERATOR_GO_PATH", go)
    monkeypatch.delenv("ED_RESET_GUARD", raising=False)
    assert OPL.reset_guard_violations("git restore -- static/chart.html")
    go.write_text('{"granted": false, "scope": []}', encoding="utf-8")
    monkeypatch.setenv("ED_RESET_GUARD", "off")
    assert OPL.reset_guard_violations("git restore -- static/chart.html")


def test_lock5_quiet_pass_required_blocks_complete_claim(monkeypatch, tmp_path):
    """LOCK-5 (RC-232): COMPLETE claim with server.py touched and quiet verdict != PASS
    BLOCKS with QUIET_PASS_REQUIRED; the DISK_ONLY token escapes honestly."""
    monkeypatch.setattr(OPL, "index_worktree_mismatches", lambda repo=None, **kw: [])
    monkeypatch.setattr(OPL, "live_collect_disk_only", lambda repo=None, port=8000: None)
    monkeypatch.setattr(OPL, "staged_enforced_checks_not_on_head", lambda repo=None: [])
    monkeypatch.setattr(OPL, "_git_diff_names", lambda root, a, b: ["server.py"])
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "ed_server_warn_quiet_window_latest.json").write_text(
        '{"verdict": "FAIL"}', encoding="utf-8")
    (tmp_path / "governance").mkdir()
    v = OPL.completion_claim_violations("Mission COMPLETE: all landed.", tmp_path)
    assert any(m.startswith("QUIET_PASS_REQUIRED:") for m in v), v
    ok = OPL.completion_claim_violations(
        "Mission COMPLETE: DISK_ONLY_UNTIL_RESTART for the server half.", tmp_path)
    assert not any(m.startswith("QUIET_PASS_REQUIRED:") for m in ok)
    (tmp_path / "reports" / "ed_server_warn_quiet_window_latest.json").write_text(
        '{"verdict": "PASS"}', encoding="utf-8")
    v2 = OPL.completion_claim_violations("Mission COMPLETE: all landed.", tmp_path)
    assert not any(m.startswith("QUIET_PASS_REQUIRED:") for m in v2)


def test_measure_report_has_enforcement_hashes():
    rep = OPL.measure_report()
    assert "enforcement_hashes" in rep
    assert "sole_writer" in rep
    assert "pm_mission" in rep


def test_main_precommit_exits_zero_on_clean_repo(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    monkeypatch.chdir(repo)
    monkeypatch.setattr(OPL, "REPO", repo)
    monkeypatch.setattr(OPL, "SOLE_WRITER_PATH", repo / "governance" / "sole_writer.json")
    monkeypatch.setattr(OPL, "OPERATOR_GO_PATH", repo / "governance" / "operator_go.json")
    rc = OPL.main(["--pre-commit"])
    assert rc == 0


# ---------------------------------------------------------------------------
# RC-234 — pipe-masked commits (the t6+t12 slice reported exit 0 off `| tail -3`
# while HEAD never moved; the filter's exit code replaced the commit's).
# ---------------------------------------------------------------------------

def test_rc234_piped_commit_blocks():
    bad = OPL.commit_pipe_violations('git commit -m "t6 + t12 slice" 2>&1 | tail -3')
    assert bad and bad[0].startswith("PIPE_MASKED_COMMIT:")


def test_rc234_powershell_out_null_blocks():
    bad = OPL.commit_pipe_violations("git commit -m 'x' | Out-Null")
    assert bad and bad[0].startswith("PIPE_MASKED_COMMIT:")


def test_rc234_unpiped_commit_allows():
    assert OPL.commit_pipe_violations('git commit -m "clean landing" 2>&1') == []


def test_rc234_pipe_inside_quoted_message_allows():
    assert OPL.commit_pipe_violations(
        'git commit -m "RC row schema: 7-cell | pipes live in prose here"') == []


def test_rc234_pipe_on_other_segment_allows():
    assert OPL.commit_pipe_violations(
        'pytest -q | tail -2 && git commit -m "after tests"') == []


def test_rc234_pipe_ok_escape_allows():
    assert OPL.commit_pipe_violations(
        'git commit -m "x" | tail -1  # pipe-ok: operator demo') == []


def test_rc234_live_path_wired_into_bash_branch():
    src = (Path(PLG.__file__)).read_text(encoding="utf-8")
    assert "commit_pipe_violations" in src


# ---------------------------------------------------------------------------
# RC-241 — a commit that CLAIMS the GO was closed must actually ship it closed.
# I reported "operator_go.json closed back to false in this commit" while the
# committed blob carried granted=true; the PM caught it, no lock did.
# ---------------------------------------------------------------------------

def _repo_with_staged_go(tmp_path: Path, granted: bool) -> Path:
    repo = _init_repo(tmp_path)
    gov = repo / "governance"
    gov.mkdir(exist_ok=True)
    (gov / "operator_go.json").write_text(
        json.dumps({"granted": granted, "scope": [], "note": "fixture"}), encoding="utf-8")
    subprocess.run(["git", "add", "governance/operator_go.json"], cwd=str(repo), check=True)
    return repo


def test_rc241_claim_while_go_still_granted_blocks(tmp_path):
    repo = _repo_with_staged_go(tmp_path, granted=True)
    bad = OPL.go_closeout_violations(
        "Landed the thing. GO consumed; operator_go closed back to false per protocol.", repo)
    assert bad and bad[0].startswith("GO_CLOSEOUT:")


def test_rc241_claim_with_go_actually_closed_allows(tmp_path):
    repo = _repo_with_staged_go(tmp_path, granted=False)
    assert OPL.go_closeout_violations(
        "Landed the thing. GO consumed; operator_go closed back to false per protocol.",
        repo) == []


def test_rc241_no_claim_leaves_an_open_go_alone(tmp_path):
    """Leaving a GO open without saying otherwise is a PM process matter, not a lie —
    this lock only judges the CLAIM against the artifact."""
    repo = _repo_with_staged_go(tmp_path, granted=True)
    assert OPL.go_closeout_violations("Ordinary landing with no claim about the gate.",
                                      repo) == []


def test_rc241_live_path_wired_into_the_commit_branch():
    src = (Path(PLG.__file__)).read_text(encoding="utf-8")
    assert "go_closeout_violations" in src


def test_rc438_process_start_epoch_reads_via_psutil_not_powershell():
    """RC-438: _process_start_epoch reads a process start-time in-process via psutil,
    so a host powershell/CLR cold-start hang cannot make a running process's start-time
    unmeasurable and fail the runtime-identity audit on an environmental fault.
    Locks: (a) the current process's start-time is readable and matches psutil, and
    (b) the powershell shell-out is NOT reached when psutil is available."""
    import os
    import psutil

    pid = os.getpid()
    expected = psutil.Process(pid).create_time()

    got = OPL._process_start_epoch(pid)
    assert got is not None, "current process start-time must be readable"
    assert abs(got - expected) < 2.0, f"{got} must match psutil create_time {expected}"

    # Mutation control: if psutil is the primary reader, exploding the powershell
    # shell-out must not affect the result.
    orig = OPL.subprocess.run

    def _boom(*a, **k):
        raise AssertionError("powershell shell-out reached despite psutil availability")

    OPL.subprocess.run = _boom
    try:
        got2 = OPL._process_start_epoch(pid)
        assert got2 is not None and abs(got2 - expected) < 2.0
    finally:
        OPL.subprocess.run = orig
