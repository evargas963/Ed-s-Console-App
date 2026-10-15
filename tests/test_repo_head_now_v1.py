"""A checkout's HEAD now (server.checkout_head; for the app's own checkout, /api/build's
repository_state_now.repo_head_now) is read from the checkout's git files, the same commit git
itself names, for each layout a checkout of this repo has: a clone (its branch's commit in a loose
ref, or packed into packed-refs), a worktree (its own HEAD, the refs in the shared git directory)
and a detached HEAD. Real git repositories made by git in a temporary folder; git's own answer
(`git rev-parse HEAD`) is the expected value.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import server


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "test")
    for n in range(2):
        (repo / "f.txt").write_text(str(n), encoding="utf-8")
        _git(repo, "add", "f.txt")
        _git(repo, "commit", "-q", "-m", f"commit {n}")
    return repo


def test_a_clones_head_is_gits_with_its_ref_loose_and_packed(tmp_path):
    repo = _repo(tmp_path)
    assert (repo / ".git" / "refs" / "heads" / "main").is_file()
    assert server.checkout_head(repo) == _git(repo, "rev-parse", "HEAD")
    _git(repo, "pack-refs", "--all")
    assert not (repo / ".git" / "refs" / "heads" / "main").exists()
    assert server.checkout_head(repo) == _git(repo, "rev-parse", "HEAD")


def test_a_worktrees_head_and_a_detached_head_are_gits(tmp_path):
    repo = _repo(tmp_path)
    tree = tmp_path / "tree"
    _git(repo, "worktree", "add", "-q", "-b", "side", str(tree), "HEAD~1")
    assert (tree / ".git").is_file()
    assert server.checkout_head(tree) == _git(tree, "rev-parse", "HEAD") != _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "--detach", "HEAD~1")
    assert server.checkout_head(repo) == _git(repo, "rev-parse", "HEAD")


def test_a_folder_that_is_no_checkout_has_no_head(tmp_path):
    assert server.checkout_head(tmp_path) is None


def test_the_apps_own_head_is_read_without_starting_a_process():
    """/api/build reads the app's checkout's HEAD per request: from its files, as git names it."""
    assert server._repo_git_head_sha() == _git(Path(server.APP_DIR), "rev-parse", "HEAD")
