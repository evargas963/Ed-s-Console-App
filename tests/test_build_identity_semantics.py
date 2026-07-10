"""BUILD_IDENTITY consumer semantics (operator-approved 2026-07-10).

git_sha == startup process identity, stable for the process lifetime;
request-time repository state is exposed ONLY under repository_state_now;
drift between them is explicit, never silent.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent


def _api_build(monkeypatch, repo_head: str):
    import server as srv

    monkeypatch.setattr(srv, "_repo_git_head_sha", lambda: repo_head)
    return srv.api_build()


def test_git_sha_is_startup_process_identity(monkeypatch):
    import server as srv

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


def test_mechanical_lock_no_request_time_git_as_identity():
    """New-consumer lock: _repo_git_head_sha (request-time git) may feed ONLY
    the repository_state_now diagnostic inside api_build — no other function
    in server.py may call it, so no code path can present request-time git as
    process identity."""
    src = (_REPO / "server.py").read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    def enclosing_fn(node):
        cur = parents.get(node)
        while cur is not None and not isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            cur = parents.get(cur)
        return cur.name if cur is not None else "<module>"

    callers = sorted({
        enclosing_fn(n)
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id == "_repo_git_head_sha"
    })
    assert callers == ["api_build"], (
        f"_repo_git_head_sha called outside api_build: {callers} — request-time "
        f"git must never masquerade as process identity"
    )
