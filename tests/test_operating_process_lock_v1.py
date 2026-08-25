# institutional-synthetic-ok: inject index≠WT and sole-writer violations to prove RC-217 BLOCKs.
"""Operating process lock — negative controls + quiet paths (RC-217)."""
from __future__ import annotations

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


def test_edit_tools_are_not_gated_by_this_guard():
    """2026-08-24 teardown: the role/mission/authority edit rails are GONE. The guard's
    Edit branch must not block ordinary product edits — nor resurrect a role denylist.
    The one surviving Edit rail is RC-442/RC-477's cross-checkout topology check, which
    names no agent and fires only on a linked-worktree session targeting the primary
    working tree (tested below); an in-checkout edit like this one stays unblocked."""
    bad = PLG.pretooluse_block("Write", {"file_path": str(ROOT / "db.py"),
                                         "content": "# edit\n"})
    assert bad == [], bad
    assert not hasattr(OPL, "claude_isolated_edit_violation")
    assert not hasattr(OPL, "operator_go_granted")
    assert not hasattr(OPL, "pm_mission_record")


def _linked_worktree_layout(tmp_path: Path) -> tuple[Path, Path]:
    """A primary checkout (.git directory) and a linked worktree (.git FILE pointing at
    primary/.git/worktrees/wt) — pure file topology, exactly what the rail reads."""
    primary = tmp_path / "primary"
    (primary / ".git").mkdir(parents=True)
    (primary / ".git" / "worktrees" / "wt").mkdir(parents=True)
    (primary / "db.py").write_text("# live\n", encoding="utf-8")
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {primary / '.git' / 'worktrees' / 'wt'}\n",
                             encoding="utf-8")
    (wt / "own.py").write_text("# mine\n", encoding="utf-8")
    return primary, wt


def test_cross_checkout_edit_into_primary_blocks(tmp_path):
    """RC-442(a)/RC-477: a linked-worktree session editing the PRIMARY working tree is the
    2026-08-20 hazard — the rail must fire on that exact topology."""
    primary, wt = _linked_worktree_layout(tmp_path)
    bad = PLG.cross_checkout_edit_violations(
        {"file_path": str(primary / "db.py")}, repo=wt)
    assert len(bad) == 1 and "CROSS_CHECKOUT_EDIT" in bad[0], bad


def test_own_worktree_edit_stays_unblocked(tmp_path):
    primary, wt = _linked_worktree_layout(tmp_path)
    assert PLG.cross_checkout_edit_violations(
        {"file_path": str(wt / "own.py")}, repo=wt) == []
    # Relative paths resolve against the session checkout, not the primary.
    assert PLG.cross_checkout_edit_violations({"file_path": "own.py"}, repo=wt) == []


def test_primary_session_is_never_gated_by_the_rail(tmp_path):
    """The primary checkout editing anywhere (including a linked worktree) is the
    operator-visible direction — the rail is inert when .git is a directory."""
    primary, wt = _linked_worktree_layout(tmp_path)
    assert PLG.cross_checkout_edit_violations(
        {"file_path": str(wt / "own.py")}, repo=primary) == []
    assert PLG.cross_checkout_edit_violations(
        {"file_path": str(primary / "db.py")}, repo=primary) == []


def test_rail_fails_open_on_unreadable_topology(tmp_path):
    """A malformed .git file must never block (the rail blocks only on an affirmative
    cross-checkout hit)."""
    wt = tmp_path / "wt2"
    wt.mkdir()
    (wt / ".git").write_text("not a gitdir line\n", encoding="utf-8")
    assert PLG.cross_checkout_edit_violations(
        {"file_path": str(tmp_path / "anything.py")}, repo=wt) == []


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


def test_reset_guard_blocks_destructive_git_on_product(monkeypatch, tmp_path):
    """LOCK-2 (RC-231): soft tree-destructive git against product scope BLOCKS.

    The guard's own static inventory (PRODUCT_WIPE_PROTECTED) is the only thing that can
    satisfy it — no mission scope, no grant file (both gone, 2026-08-24 teardown)."""
    monkeypatch.delenv("ED_RESET_GUARD", raising=False)
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
    for cmd in ("git status", "git log --oneline -3",
                "git restore --staged governance/root_cause_log.md",
                "git stash list", "git checkout -b feature/x"):
        assert not OPL.reset_guard_violations(cmd), f"reset guard false-fired on: {cmd}"


def test_reset_guard_escapes_do_not_disable(monkeypatch):
    """RC-450: ED_RESET_GUARD=off must not disarm the wipe block."""
    monkeypatch.delenv("ED_RESET_GUARD", raising=False)
    assert OPL.reset_guard_violations("git restore -- static/chart.html")
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
    # 2026-08-24 teardown: no role/GO/mission records — the repo stores none of them.
    assert "sole_writer" not in rep
    assert "pm_mission" not in rep
    assert "operator_go" not in rep


def test_main_precommit_exits_zero_on_clean_repo(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    monkeypatch.chdir(repo)
    monkeypatch.setattr(OPL, "REPO", repo)
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
