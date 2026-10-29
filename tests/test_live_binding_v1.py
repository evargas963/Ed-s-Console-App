"""A checkout bound to ANOTHER checkout's runtime cannot run a live console or capture daemon.

MEASURED 2026-09-23 (found 2026-09-25): a console started from a linked worktree (unmerged
code) converged on production's runtime and ran for hours against the production database,
token and log, writing 15,451 errors into production's logs/ed_server.log.
"""
from __future__ import annotations

import asyncio

import pytest

import runtime_layout


def test_the_checkout_that_owns_its_runtime_may_run(tmp_path):
    assert runtime_layout.live_binding_error(tmp_path, tmp_path) is None


def test_a_sandbox_runtime_that_is_not_a_checkout_may_run(tmp_path):
    src, sandbox = tmp_path / "worktree", tmp_path / "sandbox"
    src.mkdir(); sandbox.mkdir()
    assert runtime_layout.live_binding_error(src, sandbox) is None


@pytest.mark.parametrize("git_kind", ["dir", "file"])
def test_another_checkouts_runtime_is_refused(tmp_path, git_kind):
    src, other = tmp_path / "worktree", tmp_path / "production"
    src.mkdir(); other.mkdir()
    if git_kind == "dir":
        (other / ".git").mkdir()
    else:
        (other / ".git").write_text("gitdir: elsewhere")
    why = runtime_layout.live_binding_error(src, other)
    assert why is not None and str(other) in why and "ED_RUNTIME_ROOT" in why


def test_the_console_refuses_before_starting_anything(monkeypatch):
    import server
    monkeypatch.setattr(runtime_layout, "live_binding_error", lambda *a, **k: "bound elsewhere")
    started = []
    monkeypatch.setattr(server, "_install_signal_handlers", lambda: started.append("signals"))

    async def go():
        async with server._app_lifespan(server.app):
            pass
    with pytest.raises(RuntimeError, match="live console refused: bound elsewhere"):
        asyncio.run(go())
    assert started == [], "nothing may start before the binding check"


