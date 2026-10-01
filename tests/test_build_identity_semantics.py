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


def test_no_drift_when_checkout_matches_process(monkeypatch):
    import server as srv

    startup = srv.PROCESS_IDENTITY_V1.startup_git_sha
    body = _api_build(monkeypatch, startup)
    assert body["code_drift"]["repo_moved_past_process"] is False
