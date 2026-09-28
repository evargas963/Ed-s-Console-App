"""BUILD_IDENTITY consumer semantics (operator-approved 2026-07-10).

git_sha == startup process identity, stable for the process lifetime;
request-time repository state is exposed ONLY under repository_state_now;
drift between them is explicit, never silent.
"""

from __future__ import annotations


def _api_build(monkeypatch, repo_head: str):
    import server as srv

    monkeypatch.setattr(srv, "_repo_git_head_sha", lambda: repo_head)
    return srv.api_build()


def test_git_sha_is_startup_process_identity(monkeypatch):
    body = _api_build(monkeypatch, "f" * 40)
    startup = body["process_identity"]["startup_git_sha"]
    assert body["git_sha"] == startup
    assert body["git_sha_semantics"] == "startup_process_identity"


def test_repo_head_now_is_separate_and_drift_explicit(monkeypatch):
    """Reproduces the observed 2026-07-09/2026-07-10 drift class: the checkout
    moves past the running process — git_sha must NOT move, and the drift
    must be reported explicitly."""
    import server as srv

    startup = srv.PROCESS_IDENTITY_V1.startup_git_sha
    moved_head = "a" * 40
    assert moved_head != startup
    body = _api_build(monkeypatch, moved_head)
    assert body["git_sha"] == startup                      # stable identity
    assert body["repository_state_now"]["repo_head_now"] == moved_head
    drift = body["code_drift"]
    assert drift["repo_moved_past_process"] is True
    assert drift["running_code"] == startup
    assert drift["checked_out_code"] == moved_head


def test_no_drift_when_checkout_matches_process(monkeypatch):
    import server as srv

    startup = srv.PROCESS_IDENTITY_V1.startup_git_sha
    body = _api_build(monkeypatch, startup)
    assert body["code_drift"]["repo_moved_past_process"] is False


def test_git_sha_stable_across_requests_regardless_of_repo(monkeypatch):
    body1 = _api_build(monkeypatch, "1" * 40)
    body2 = _api_build(monkeypatch, "2" * 40)
    assert body1["git_sha"] == body2["git_sha"]
