"""The running process's identity (server.capture_process_identity, captured once at import) and
/api/build's answer (server.build_identity_answer): `git_sha` is the code the process loaded,
stable for its life; the checkout's HEAD now is reported apart, and the drift between them is
explicit, None while either is unknown. Real git repositories made by git in a temporary folder;
git's own answers are the expected values.
"""

from __future__ import annotations

import dataclasses
import os
import subprocess
from pathlib import Path

import pytest
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


def test_a_clean_checkouts_identity_is_its_head(tmp_path):
    repo = _repo(tmp_path)
    ident = srv.capture_process_identity(repo)
    sha = _git(repo, "rev-parse", "HEAD")
    assert (ident.startup_git_sha, ident.startup_git_sha_short) == (sha, sha[:12])
    assert ident.startup_git_dirty is False and ident.startup_git_available
    assert (ident.identity_source, ident.identity_capture_error) == ("git_startup_capture", None)
    assert (
        ident.process_id == os.getpid()
        and 0 < ident.process_started_at_utc <= ident.startup_identity_captured_at_utc
    )


def test_an_untracked_file_makes_the_checkout_dirty(tmp_path):
    repo = _repo(tmp_path)
    (repo / "new.txt").write_text("x", encoding="utf-8")
    assert srv.capture_process_identity(repo).startup_git_dirty is True


def test_a_checkout_whose_dirty_state_git_cannot_say_is_unknown_never_clean(tmp_path):
    repo = _repo(tmp_path)
    (repo / ".git" / "index").write_bytes(b"not an index")  # git status fails on it
    ident = srv.capture_process_identity(repo)
    assert ident.startup_git_sha == _git(repo, "rev-parse", "HEAD")
    assert (ident.startup_git_dirty, ident.identity_capture_error) == (
        None,
        "git_dirty_state_unavailable",
    )


def test_a_folder_that_is_no_checkout_has_no_identity(tmp_path):
    ident = srv.capture_process_identity(tmp_path)
    assert (ident.startup_git_sha, ident.startup_git_sha_short, ident.startup_git_dirty) == (
        None,
        None,
        None,
    )
    assert not ident.startup_git_available
    assert (ident.identity_source, ident.identity_capture_error) == (
        "unavailable",
        "head_unreadable",
    )


def test_the_identity_stands_while_the_checkout_moves_and_the_drift_is_explicit(tmp_path):
    """The process loaded commit A; the checkout moves to B: git_sha stays A on every answer, the
    HEAD now is B, and the drift says so; the same HEAD is no drift; an unknown HEAD is unknown
    drift, never "no drift"."""
    repo = _repo(tmp_path)
    ident = srv.capture_process_identity(repo)
    sha_a, sha_b = ident.startup_git_sha, _commit(repo, "b.txt")
    moved = srv.build_identity_answer(ident, srv.checkout_head(repo))
    assert (moved["git_sha"], moved["repository_state_now"]["repo_head_now"]) == (sha_a, sha_b)
    assert moved["code_drift"] == {
        "repo_moved_past_process": True,
        "running_code": sha_a,
        "checked_out_code": sha_b,
    }
    assert srv.build_identity_answer(ident, sha_a)["code_drift"]["repo_moved_past_process"] is False
    assert srv.build_identity_answer(ident, None)["code_drift"]["repo_moved_past_process"] is None
    assert srv.capture_process_identity(repo).startup_git_sha == sha_b  # a new process loads B
    unknown_start = srv.capture_process_identity(tmp_path / "nowhere")  # no checkout: no identity
    assert (
        srv.build_identity_answer(unknown_start, sha_b)["code_drift"]["repo_moved_past_process"]
        is None
    )


def test_the_identity_cannot_be_changed():
    with pytest.raises(dataclasses.FrozenInstanceError):
        srv.PROCESS_IDENTITY_V1.startup_git_sha = "f" * 40  # type: ignore[misc]


def test_api_build_serves_the_answer_for_the_apps_own_checkout_on_every_request():
    """The route's answer keeps its keys, and its identity is the same object on every request."""
    with TestClient(srv.app) as client:
        first, second = client.get("/api/build").json(), client.get("/api/build").json()
    assert first == second
    assert (
        first["contract"] == "meet_or_exceed_v1"
        and first["git_sha_semantics"] == "startup_process_identity"
    )
    assert set(first["process_identity"]) == {
        "schema_version",
        "startup_git_sha",
        "startup_git_sha_short",
        "startup_git_dirty",
        "startup_git_available",
        "startup_identity_captured_at_utc",
        "process_started_at_utc",
        "process_id",
        "identity_source",
        "identity_capture_error",
    }
    assert first["process_identity"]["schema_version"] == "1"
    assert first == srv.build_identity_answer(
        srv.PROCESS_IDENTITY_V1, srv.checkout_head(srv.APP_DIR)
    )
