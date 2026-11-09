"""A checkout bound to ANOTHER checkout's runtime cannot run a live console or capture daemon.

MEASURED 2026-09-23 (found 2026-09-25): a console started from a linked worktree (unmerged
code) converged on production's runtime and ran for hours against the production database,
token and log, writing 15,451 errors into production's logs/ed_server.log.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import runtime_layout
from tests.test_data_path_stored_sessions_v1 import _record_answers


def test_the_checkout_that_owns_its_runtime_may_run(tmp_path):
    assert runtime_layout.live_binding_error(tmp_path, tmp_path) is None


def test_a_sandbox_runtime_that_is_not_a_checkout_may_run(tmp_path):
    src, sandbox = tmp_path / "worktree", tmp_path / "sandbox"
    src.mkdir()
    sandbox.mkdir()
    assert runtime_layout.live_binding_error(src, sandbox) is None


@pytest.mark.parametrize("git_kind", ["dir", "file"])
def test_another_checkouts_runtime_is_refused(tmp_path, git_kind):
    src, other = tmp_path / "worktree", tmp_path / "production"
    src.mkdir()
    other.mkdir()
    if git_kind == "dir":
        (other / ".git").mkdir()
    else:
        (other / ".git").write_text("gitdir: elsewhere")
    why = runtime_layout.live_binding_error(src, other)
    assert why is not None and str(other) in why and "ED_RUNTIME_ROOT" in why


#: a console process starting its pages (server._app_lifespan), its log on stderr
CONSOLE_START = """
import asyncio
import logging

import server

logging.basicConfig(level=logging.INFO)


async def go():
    async with server._app_lifespan(server.app):
        pass


asyncio.run(go())
"""


def test_the_console_refuses_before_starting_anything(tmp_path):
    """A console whose runtime root is another checkout (a `.git` folder in it) holding the
    daemon's recorded /markets answers: it refuses at its start, and loads none of them (the
    first thing it starts, logged as 'Recorded market answers held').
    """
    _record_answers(tmp_path / "data" / "stream_capture.db")
    (tmp_path / ".git").mkdir()
    run = subprocess.run(
        [sys.executable, "-c", CONSOLE_START],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parent.parent,
        env={
            **os.environ,
            "ED_RUNTIME_ROOT": str(tmp_path),
            "SCHWAB_TOKEN_PATH": str(tmp_path / "missing_schwab_token.json"),
            "PYTHONIOENCODING": "utf-8",
        },
        timeout=120,
    )
    assert run.returncode != 0
    assert "live console refused: this checkout" in run.stderr and str(tmp_path) in run.stderr
    assert "Recorded market answers held" not in run.stderr, (
        "nothing may start before the binding check"
    )
