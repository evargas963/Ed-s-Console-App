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


def test_edit_branch_topology_rails_only_no_role_denylist(tmp_path):
    """2026-08-24 teardown: the role/mission/authority edit DENYLISTS are GONE and must not
    resurrect. The Edit branch carries only topology rails that name no agent — RC-442/RC-477
    cross-checkout (a LINKED worktree editing the primary), and the live-checkout invariant #4
    (a session that IS the production primary editing its OWN app code). A linked worktree
    editing its own files stays unblocked: that is where development belongs. Deterministic
    against a temp topology, so it holds in a primary clone (CI) and a linked worktree alike."""
    primary, wt = _linked_worktree_layout(tmp_path)
    (wt / "server.py").write_text("# mine\n", encoding="utf-8")
    (primary / "notes.md").write_text("# doc\n", encoding="utf-8")
    # a LINKED-worktree session editing its OWN app code → unblocked (ordinary dev work)
    assert PLG.production_checkout_app_edit_violations({"file_path": str(wt / "server.py")}, wt) == []
    assert PLG.cross_checkout_edit_violations({"file_path": str(wt / "server.py")}, wt) == []
    # a session that IS the production primary editing its OWN app code → BLOCKED (invariant #4)
    bad = PLG.production_checkout_app_edit_violations({"file_path": str(primary / "db.py")}, primary)
    assert any("PROD_CHECKOUT_APP_EDIT" in b for b in bad), bad
    # ...but a non-app file (docs/governance) in the primary is NOT gated
    assert PLG.production_checkout_app_edit_violations({"file_path": str(primary / "notes.md")}, primary) == []
    # no role-based denylist resurrected
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


# ── REDATE_LOCK (audit rounds 2-3, 2026-08-25): a promised due date moves only when the
# row is BLOCKED on something outside the repository, declared as BLOCKED_ON_<CLASS> with
# specifics (operator: fixable defects get fixed, not administratively postponed).
# Measured basis: 67 historical due-cell moves, 61 on already-overdue rows, 2 with no
# reason anywhere.

_ROW = "| RC-900 | {status} | 2026-08-01 | {due} | defect text | why -> chain | {fix} |"


def _ledger_repo(tmp_path, head_due="2026-08-10", head_status="OPEN"):
    repo = _init_repo(tmp_path)
    led = repo / "governance" / "root_cause_log.md"
    led.write_text(_ROW.format(status=head_status, due=head_due, fix="FIXED: x") + "\n",
                   encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "ledger"], cwd=repo, check=True,
                   capture_output=True)
    return repo, led


def _stage(repo, led, row_text):
    led.write_text(row_text + "\n", encoding="utf-8")
    subprocess.run(["git", "add", str(led)], cwd=repo, check=True, capture_output=True)


def test_redate_lock_blocks_a_silent_due_move(tmp_path):
    repo, led = _ledger_repo(tmp_path)
    _stage(repo, led, _ROW.format(status="OPEN", due="2026-09-10", fix="FIXED: x"))
    out = OPL.rc_redate_violations(repo)
    assert out and "REDATE_LOCK" in out[0] and "RC-900" in out[0], out


def test_redate_lock_passes_with_a_declared_blocker_class(tmp_path):
    repo, led = _ledger_repo(tmp_path)
    _stage(repo, led, _ROW.format(
        status="OPEN", due="2026-09-10",
        fix="FIXED: x RE-DATED 2026-08-10->2026-09-10: BLOCKED_ON_DATA_ACCRUAL — "
            "wide-capture n reaches 30 sessions on 2026-09-10"))
    assert OPL.rc_redate_violations(repo) == []


def test_redate_lock_blocks_a_free_text_reason(tmp_path):
    """Operator round 3 (2026-08-25): a reason alone no longer legitimizes postponement —
    'need more time' is exactly the administrative deferral the requirement bans."""
    repo, led = _ledger_repo(tmp_path)
    _stage(repo, led, _ROW.format(
        status="OPEN", due="2026-09-10",
        fix="FIXED: x RE-DATED 2026-08-10->2026-09-10: need more time on this"))
    out = OPL.rc_redate_violations(repo)
    assert out and "administratively postponed" in out[0], out


def test_redate_lock_blocks_a_bare_blocker_class_with_no_specifics(tmp_path):
    repo, led = _ledger_repo(tmp_path)
    _stage(repo, led, _ROW.format(
        status="OPEN", due="2026-09-10",
        fix="FIXED: x RE-DATED 2026-08-10->2026-09-10: BLOCKED_ON_OPERATOR"))
    assert OPL.rc_redate_violations(repo), "the class without WHAT is awaited is a rubber stamp"


def test_redate_lock_blocks_an_empty_reason(tmp_path):
    repo, led = _ledger_repo(tmp_path)
    _stage(repo, led, _ROW.format(
        status="OPEN", due="2026-09-10",
        fix="FIXED: x RE-DATED 2026-08-10->2026-09-10: "))
    assert OPL.rc_redate_violations(repo), "an empty reason is not a reason"


def test_redate_lock_blocks_wrong_lineage(tmp_path):
    repo, led = _ledger_repo(tmp_path)
    _stage(repo, led, _ROW.format(
        status="OPEN", due="2026-09-10",
        fix="FIXED: x RE-DATED 2026-08-09->2026-09-10: reason with wrong old date"))
    assert OPL.rc_redate_violations(repo), "lineage must name the actual old due date"


def test_redate_lock_exempts_a_closing_row(tmp_path):
    repo, led = _ledger_repo(tmp_path)
    _stage(repo, led, _ROW.format(status="CLOSED", due="2026-08-25",
                                  fix="FIXED and VERIFIED: 3 tests"))
    assert OPL.rc_redate_violations(repo) == []


def test_redate_lock_ignores_new_rows_and_non_due_edits(tmp_path):
    repo, led = _ledger_repo(tmp_path)
    _stage(repo, led,
           _ROW.format(status="OPEN", due="2026-08-10", fix="FIXED: x plus more detail")
           + "\n| RC-901 | OPEN | 2026-08-25 | 2026-09-30 | new defect | why -> chain | NEXT-DEPTH: y |")
    assert OPL.rc_redate_violations(repo) == []


def test_redate_lock_quiet_on_untouched_ledger(tmp_path):
    repo, _led = _ledger_repo(tmp_path)
    assert OPL.rc_redate_violations(repo) == []


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

