"""Operating process lock and the process-lock guard's checkout rails: negative controls and
quiet paths."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.operating_process_lock as OPL  # noqa: E402
import tools.process_lock_guard as PLG  # noqa: E402


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

