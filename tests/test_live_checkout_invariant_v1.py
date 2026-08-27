"""Live-checkout invariant (RC-350 + governance/AGENT_OPERATING_PROCESS_V1.md §6).

The production/primary EdWebConsole checkout stays branch main == origin/main, and an assigned
agent cannot MOVE it onto a feature branch or edit its app code in place. These negative controls
prove the PREVENTION seam (tools/process_lock_guard.py) refuses the exact 2026-08-26 drift that
downed the desk while ALLOWING the sanctioned production operations (reads, fetch, the
fast-forward-to-origin/main update, return-to-main), leaves dev worktrees unconstrained, and that
the RC-350 launch lock now asserts branch==main AND HEAD==origin/main (equality), not merely
"not detached / not ahead".
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import tools.check_live_path_is_main as clp  # noqa: E402
import tools.process_lock_guard as plg  # noqa: E402


def _make_primary(tmp_path: Path) -> Path:
    prim = tmp_path / "EdWebConsole"
    (prim / ".git").mkdir(parents=True)      # a PRIMARY working tree: its .git is a DIRECTORY
    return prim


def _make_linked(tmp_path: Path, prim: Path) -> Path:
    wt = tmp_path / "EdWebConsole-dev"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {prim}/.git/worktrees/dev\n", encoding="utf-8")  # linked: FILE
    return wt


# ── git branch-move / commit ban on the production primary ──────────────────────────────────

def test_prod_checkout_git_move_blocks_the_incident(tmp_path, monkeypatch):
    prim = _make_primary(tmp_path)
    monkeypatch.setattr(plg, "REPO", prim)
    cwd = str(prim)
    for cmd in (
        "git checkout -b cleanup/delete-now-root-stubs",   # the exact 2026-08-26 drift
        "git switch -c feature",
        "git checkout some-feature",
        "git commit -m 'landing'",
        'git -c user.name=x commit -m "y"',                # global option before the subcommand
        "git merge feature",
        "git pull",
        "git reset --soft HEAD~1",
        "git rebase origin/main",
        "git cherry-pick abc123",
        "git revert HEAD",
        "git branch newbranch",
        "git branch -D oldbranch",
    ):
        assert plg.prod_checkout_git_move_violations(cmd, cwd), f"must BLOCK on production: {cmd}"


def test_prod_checkout_allows_reads_fetch_ffupdate_and_return_to_main(tmp_path, monkeypatch):
    prim = _make_primary(tmp_path)
    monkeypatch.setattr(plg, "REPO", prim)
    cwd = str(prim)
    for cmd in (
        "git status", "git fetch origin", "git log --oneline -5", "git diff", "git show HEAD",
        "git rev-parse HEAD", "git branch", "git branch -a", "git branch --show-current",
        "git checkout main", "git switch main",            # sanctioned return-to-main recovery
        "git merge --ff-only origin/main",                 # the merge-then-fast-forward update
        "git pull --ff-only", "git pull --ff-only origin main",
        "git checkout -- server.py",                       # file-restore (destructive rail owns it)
        "git worktree add ../wt -b b origin/main",
        "git add server.py",
    ):
        assert plg.prod_checkout_git_move_violations(cmd, cwd) == [], f"must ALLOW on production: {cmd}"


def test_prod_checkout_move_ban_leaves_dev_worktrees_free(tmp_path, monkeypatch):
    prim = _make_primary(tmp_path)
    wt = _make_linked(tmp_path, prim)
    # primary session targeting the dev worktree via -C is free (this is how the agent commits)
    monkeypatch.setattr(plg, "REPO", prim)
    assert plg.prod_checkout_git_move_violations(f"git -C {wt} checkout -b feature", str(prim)) == []
    assert plg.prod_checkout_git_move_violations(f"git -C {wt} commit -m x", str(prim)) == []
    # a session whose cwd IS the dev worktree branches there freely
    monkeypatch.setattr(plg, "REPO", wt)
    assert plg.prod_checkout_git_move_violations("git checkout -b feature", str(wt)) == []
    assert plg.prod_checkout_git_move_violations("git commit -m x", str(wt)) == []


# ── app-code edit ban on the production primary ─────────────────────────────────────────────

def test_prod_checkout_app_edit_blocks_primary_session_editing_app_code(tmp_path, monkeypatch):
    prim = _make_primary(tmp_path)
    monkeypatch.setattr(plg, "REPO", prim)
    (prim / "server.py").write_text("x = 1\n", encoding="utf-8")
    (prim / "governance").mkdir()
    (prim / "governance" / "root_cause_log.md").write_text("# ledger\n", encoding="utf-8")
    # app code in the production checkout → BLOCK
    assert plg.production_checkout_app_edit_violations({"file_path": str(prim / "server.py")}, prim)
    # governance / docs / reports are not app code → allowed (agents still comply by editing them)
    assert plg.production_checkout_app_edit_violations(
        {"file_path": str(prim / "governance" / "root_cause_log.md")}, prim) == []


def test_prod_checkout_app_edit_exempts_worktree_files_and_linked_sessions(tmp_path, monkeypatch):
    prim = _make_primary(tmp_path)
    wt = _make_linked(tmp_path, prim)
    (wt / "server.py").write_text("x = 1\n", encoding="utf-8")
    # the primary session editing a WORKTREE file (outside the primary tree) → not blocked
    monkeypatch.setattr(plg, "REPO", prim)
    assert plg.production_checkout_app_edit_violations({"file_path": str(wt / "server.py")}, prim) == []
    # a LINKED-worktree session is unconstrained by this rail (cross_checkout owns its direction)
    assert plg.production_checkout_app_edit_violations({"file_path": str(wt / "server.py")}, wt) == []


# ── the strengthened RC-350 launch/CI lock: branch==main AND HEAD==origin/main ──────────────

def test_launch_lock_asserts_branch_main_and_head_equals_origin(monkeypatch):
    calls: dict[str, str] = {}
    monkeypatch.setattr(clp, "_git", lambda *args: calls.get(" ".join(args), ""))

    def base_ok():
        calls.clear()
        calls.update({
            "rev-parse --short HEAD": "abc1234",
            "symbolic-ref --short HEAD": "main",
            "rev-list --count origin/main..HEAD": "0",
            "rev-list --count HEAD..origin/main": "0",
            "status --porcelain": "",
        })

    base_ok()
    assert clp.violations() == []                                   # on main, equal, clean → PASS

    base_ok(); calls["symbolic-ref --short HEAD"] = "cleanup/delete-now-root-stubs"
    assert any("not `main`" in v for v in clp.violations())         # feature branch → BLOCK

    base_ok(); calls["symbolic-ref --short HEAD"] = ""
    assert any("detached" in v.lower() for v in clp.violations())   # detached HEAD → BLOCK

    base_ok(); calls["rev-list --count HEAD..origin/main"] = "3"
    assert any("BEHIND origin/main" in v for v in clp.violations()) # stale desk → BLOCK

    base_ok(); calls["rev-list --count origin/main..HEAD"] = "2"
    assert any("NOT on origin/main" in v for v in clp.violations()) # divergent lineage → BLOCK


# ── chained-command laundering: EVERY git invocation is judged on its own (bypass class) ────

def test_prod_checkout_git_move_chained_no_launder_by_harmless_first(tmp_path, monkeypatch):
    prim = _make_primary(tmp_path)
    wt = _make_linked(tmp_path, prim)
    monkeypatch.setattr(plg, "REPO", prim)
    cwd = str(prim)
    # A harmless (or elsewhere-aimed) FIRST git must NOT launder a later forbidden git that
    # TARGETS the production primary — the exact bypass this closes.
    for cmd in (
        "git status && git checkout -b cleanup/x",             # harmless first git
        "git log --oneline -1 ; git switch -c feature",
        f"git -C {wt} status && git checkout -b feature",      # first git aimed at the dev worktree
        "git rev-parse HEAD && git commit -m x",
        "true && git reset --hard HEAD~1",
        f"git -C {wt} commit -m x && git merge feature",       # later non-ff merge on the primary
        "git fetch origin && git rebase origin/main",
    ):
        assert plg.prod_checkout_git_move_violations(cmd, cwd), f"laundered forbidden git must BLOCK: {cmd}"


def test_prod_checkout_git_move_cd_into_primary_from_dev_session_blocks(tmp_path, monkeypatch):
    prim = _make_primary(tmp_path)
    wt = _make_linked(tmp_path, prim)
    # a dev-worktree session that `cd`s into the production primary and branches there → BLOCK
    monkeypatch.setattr(plg, "REPO", wt)
    assert plg.prod_checkout_git_move_violations(f"cd {prim} && git checkout -b feature", str(wt))
    # ...but `cd`-ing the OTHER way (into the dev worktree) to branch is free
    monkeypatch.setattr(plg, "REPO", prim)
    assert plg.prod_checkout_git_move_violations(f"cd {wt} && git checkout -b feature", str(prim)) == []


def test_prod_checkout_git_move_chained_all_dev_or_allowed_pass(tmp_path, monkeypatch):
    prim = _make_primary(tmp_path)
    wt = _make_linked(tmp_path, prim)
    monkeypatch.setattr(plg, "REPO", prim)
    for cmd in (
        "git fetch origin && git merge --ff-only origin/main",  # the production update
        "git status && git log --oneline -5 && git diff",       # all reads
        f"git -C {wt} checkout -b feature && git -C {wt} commit -m x",  # all in the dev worktree
        "git fetch && git checkout main",
    ):
        assert plg.prod_checkout_git_move_violations(cmd, str(prim)) == [], f"must ALLOW: {cmd}"


# ── materially-equivalent SHELL edits to production app code (not only Edit/Write) ──────────

def test_prod_checkout_shell_app_write_blocks_material_edits(tmp_path, monkeypatch):
    prim = _make_primary(tmp_path)
    monkeypatch.setattr(plg, "REPO", prim)
    (prim / "server.py").write_text("x = 1\n", encoding="utf-8")
    (prim / "static").mkdir()
    (prim / "static" / "index.html").write_text("<h1>", encoding="utf-8")
    cwd = str(prim)
    for cmd in (
        "cp /tmp/evil.py server.py",                 # copy over production app code
        "mv /tmp/x.py server.py",
        "sed -i 's/x = 1/x = 2/' server.py",         # in-place edit
        "perl -pi -e 's/a/b/' server.py",
        "tee server.py",
        "cat /tmp/x | tee static/index.html",
        "install -m644 /tmp/x static/index.html",
        "dd if=/tmp/x of=server.py",
        "truncate -s 0 server.py",
        "true && cp /tmp/evil.py server.py",         # a leading no-op cannot launder it
    ):
        assert plg.production_checkout_shell_app_write_violations(cmd, cwd), \
            f"materially-equivalent shell edit to production app code must BLOCK: {cmd}"


def test_prod_checkout_shell_app_write_exempts_reads_nonapp_and_worktrees(tmp_path, monkeypatch):
    prim = _make_primary(tmp_path)
    wt = _make_linked(tmp_path, prim)
    (prim / "server.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(plg, "REPO", prim)
    for cmd, cwd in (
        ("cp server.py /tmp/backup.py", str(prim)),      # READING server.py (dest is outside)
        ("cat server.py", str(prim)),                    # pure read, no write verb
        ("python server.py", str(prim)),                 # run, not write
        ("sed -i 's/a/b/' README.md", str(prim)),        # not app code
        (f"cp /tmp/evil.py {wt}/server.py", str(prim)),  # dest is the DEV worktree
        ("sed -i 's/a/b/' server.py", str(wt)),          # session cwd is the dev worktree
    ):
        assert plg.production_checkout_shell_app_write_violations(cmd, cwd) == [], f"must ALLOW: {cmd}"


def test_prod_checkout_shell_app_write_is_target_based_from_any_session(tmp_path, monkeypatch):
    prim = _make_primary(tmp_path)
    wt = _make_linked(tmp_path, prim)
    (prim / "server.py").write_text("x = 1\n", encoding="utf-8")
    (wt / "server.py").write_text("x = 1\n", encoding="utf-8")
    # a LINKED-worktree session writing the PRODUCTION primary's app code by absolute path → BLOCK
    monkeypatch.setattr(plg, "REPO", wt)
    assert plg.production_checkout_shell_app_write_violations(f"cp /tmp/evil.py {prim}/server.py", str(wt))
    # ...but writing its OWN worktree's app code is free
    assert plg.production_checkout_shell_app_write_violations(f"cp /tmp/evil.py {wt}/server.py", str(wt)) == []


def test_prod_checkout_shell_redirect_to_static_app_blocks(tmp_path, monkeypatch):
    # the gap the universal redirect ban (.py-only) misses: ordinary shell redirection to
    # production static/*.html and static/*.js — materially equivalent to editing them.
    prim = _make_primary(tmp_path)
    wt = _make_linked(tmp_path, prim)
    monkeypatch.setattr(plg, "REPO", prim)
    (prim / "static").mkdir()
    for cmd in (
        "printf x > static/index.html",
        "echo x > static/app.js",
        "echo x >> static/index.html",
        "cat /tmp/x > static/main.css",
        "echo x > server.py",                       # redirect to .py is caught here too
        "true && printf x > static/index.html",     # a leading no-op cannot launder it
    ):
        assert plg.production_checkout_shell_app_write_violations(cmd, str(prim)), \
            f"redirect to production app code must BLOCK: {cmd}"
    # ...a redirect to a non-app file, outside the tree, or into the dev worktree stays free
    for cmd, cwd in (
        ("echo x > notes.md", str(prim)),                    # not app code
        ("echo x > /tmp/out.log", str(prim)),                # outside the production tree
        (f"echo x > {wt}/static/app.js", str(prim)),         # dev worktree, absolute
        ("echo x > static/app.js", str(wt)),                 # session cwd is the dev worktree
    ):
        assert plg.production_checkout_shell_app_write_violations(cmd, cwd) == [], f"must ALLOW: {cmd}"
