# institutional-synthetic-ok: inject cross-checkout edits and destructive git to prove the locks BLOCK.
"""Operating process lock — negative controls + quiet paths."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.operating_process_lock as OPL  # noqa: E402
import tools.process_lock_guard as PLG  # noqa: E402


def test_edit_branch_topology_rails_only_no_role_denylist(tmp_path):
    """No role/mission/authority edit denylist exists. The Edit branch carries only topology
    rails that name no agent — cross-checkout (a LINKED worktree editing the primary), and the live-checkout invariant #4
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
    """A linked-worktree session editing the PRIMARY working tree: the rail fires on that
    exact topology."""
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


def test_reset_guard_blocks_destructive_git_on_product():
    """The reset guard: soft tree-destructive git against product scope BLOCKS.

    The guard's own static inventory (PRODUCT_WIPE_PROTECTED) is the only thing that can
    satisfy it."""
    for cmd in ("git restore -- static/chart.html",
                "git checkout -- server.py",
                "git restore -- math_levels.py",
                "git checkout -- math_exposure_core.py",
                "git clean -fd static/",
                "git reset --hard",
                "git stash"):
        assert OPL.reset_guard_violations(cmd), f"reset guard silent on: {cmd}"


def test_reset_guard_permits_safe_git():
    """The reset guard's negative control: index-only and read-only git stays legal."""
    for cmd in ("git status", "git log --oneline -3",
                "git restore --staged governance/root_cause_log.md",
                "git stash list", "git checkout -b feature/x"):
        assert not OPL.reset_guard_violations(cmd), f"reset guard false-fired on: {cmd}"


# ---------------------------------------------------------------------------
# Pipe-masked commits: a `git commit` piped into a filter reports the filter's
# exit code, not the commit's.
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


def test_an_edit_target_is_placed_once_whatever_its_spelling(tmp_path):
    """The production checkout's app code is refused whether the target is spelled absolute or
    relative to the checkout; tests/, docs/ and scratch files there are not app code; a file in
    another checkout is not the production checkout's."""
    primary, wt = _linked_worktree_layout(tmp_path)
    for target in (str(primary / "db.py"), "db.py", "tools/x.py"):
        bad = PLG.production_checkout_app_edit_violations({"file_path": target}, primary)
        assert any("PROD_CHECKOUT_APP_EDIT" in b for b in bad), (target, bad)
    for target in ("tests/test_x.py", "docs/x.py", "scratchpad/x.py", str(wt / "own.py")):
        assert PLG.production_checkout_app_edit_violations({"file_path": target}, primary) == [], target


def test_every_file_the_console_and_daemon_run_is_app_code_to_the_rails():
    """The rails' list of what is app code is checked against what runs: every repository file
    the console (server) and the capture daemon load is app code in the production checkout, so
    an edit to it there is refused. A folder of running code left off the list fails here. The two
    load in a fresh process, so what other tests imported into this worker is not counted."""
    loaded = subprocess.run(
        [sys.executable, "-c", "import sys, server, app.market_data.schwab.streaming.capture; "
         "print('\\n'.join(m.__file__ for m in list(sys.modules.values()) if getattr(m, '__file__', None)))"],
        cwd=ROOT, check=True, capture_output=True, text=True).stdout.splitlines()
    files = {Path(f).resolve() for f in loaded if Path(f).resolve().is_relative_to(ROOT)
             and not {".venv", "tests"} & set(Path(f).resolve().relative_to(ROOT).parts[:1])}
    assert any(f.parent.name == "calibration" for f in files)          # the daemon's chain sweep
    missed = sorted(str(f.relative_to(ROOT)) for f in files if PLG.production_path(str(f), ROOT, ROOT) is None)
    assert missed == [], missed


def test_an_edit_target_that_cannot_be_placed_is_refused(tmp_path):
    """INDUCED CONDITION: a target holding a NUL byte, inside the production checkout. Where the
    filesystem cannot place it (Linux), the guard raises and hook_chain refuses the event; where
    it can (Windows), it is app code and refused. It is never let through."""
    primary, _wt = _linked_worktree_layout(tmp_path)
    try:
        bad = PLG.production_checkout_app_edit_violations(
            {"file_path": str(primary / "tools" / "x\x00.py")}, primary)
    except ValueError:
        return                                   # a raising guard is a block (test_hook_chain_v1)
    assert any("PROD_CHECKOUT_APP_EDIT" in b for b in bad), bad


def test_a_cross_checkout_target_that_cannot_be_placed_is_refused(tmp_path):
    """INDUCED CONDITION: a linked worktree's edit target in the production checkout holding a NUL
    byte. The cross-checkout rail places it with the same function as the other rails: it raises
    (a block) or it is refused; the old rail skipped it and let it through."""
    primary, wt = _linked_worktree_layout(tmp_path)
    try:
        bad = PLG.cross_checkout_edit_violations({"file_path": str(primary / "x\x00.md")}, repo=wt)
    except ValueError:
        return                                   # a raising guard is a block (test_hook_chain_v1)
    assert len(bad) == 1 and "CROSS_CHECKOUT_EDIT" in bad[0], bad


def test_a_shell_write_to_the_production_checkouts_app_code_is_refused_and_devices_are_not():
    """The shell rail places each write destination with `production_path`, against this
    repository's own production checkout: a redirect into static/ is refused; a device, stdout or
    an empty name is not app code there, and placing it does not raise."""
    primary = PLG._primary_worktree_root(ROOT) or ROOT
    bad = PLG.production_checkout_shell_app_write_violations(PLG.read("echo x > static/x.js", str(primary)))
    assert len(bad) == 1 and "PROD_CHECKOUT_APP_EDIT" in bad[0], bad
    for cmd in ("echo x > /dev/null", "echo x > NUL", "echo x > nul", 'echo x > ""'):
        assert PLG.production_checkout_shell_app_write_violations(PLG.read(cmd, str(primary))) == [], cmd

