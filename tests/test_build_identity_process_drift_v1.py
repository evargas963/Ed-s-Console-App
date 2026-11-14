"""/api/build's answer: the commit the running process loaded, and the checkout's HEAD now.

The running commit is server.RUNNING_COMMIT, read once at import (server.checkout_head); the
answer is server.build_answer. The running commit stands for the process's life; the checkout's
HEAD now is reported beside it, and whether the two differ, None while either is unknown. Real
git repositories made by git in a temporary folder; git's own answers are the expected values.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

import server as srv


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True, timeout=30.0
    ).stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "identrepo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@test.local")
    _git(repo, "config", "user.name", "identity-test")
    _git(repo, "config", "commit.gpgsign", "false")
    _commit(repo, "a.txt")
    return repo


def _commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", name, "--no-verify")
    return _git(repo, "rev-parse", "HEAD")


def test_the_running_commit_stands_while_the_checkout_moves_and_the_answer_says_they_differ(
    tmp_path,
):
    """The process loaded commit A; the checkout moves to B: the running commit stays A.

    The checkout's commit is B and the two differ; the same commit does not differ; an unknown
    commit on either side is unknown, never "the same".
    """
    repo = _repo(tmp_path)
    sha_a = srv.checkout_head(repo)
    assert sha_a == _git(repo, "rev-parse", "HEAD")
    sha_b = _commit(repo, "b.txt")
    assert srv.build_answer(sha_a, srv.checkout_head(repo)) == {
        "running_commit": sha_a,
        "checkout_commit": sha_b,
        "differ": True,
    }
    assert srv.build_answer(sha_a, sha_a)["differ"] is False
    assert srv.build_answer(sha_a, None)["differ"] is None
    assert srv.build_answer(srv.checkout_head(tmp_path / "nowhere"), sha_b) == {
        "running_commit": None,
        "checkout_commit": sha_b,
        "differ": None,
    }


def test_api_build_serves_the_answer_for_the_apps_own_checkout_on_every_request():
    with TestClient(srv.app) as client:
        first, second = client.get("/api/build").json(), client.get("/api/build").json()
    assert first == second
    assert first == srv.build_answer(srv.RUNNING_COMMIT, srv.checkout_head(srv.APP_DIR))
