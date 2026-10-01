# institutional-synthetic-ok: temp directories stand in for a relocated runtime root.
"""RC-523 — runtime state is rooted in `runtime_layout`, not the source checkout.

Before this, every runtime path was `Path(__file__).parent / "data" | "logs" | "reports"`,
with an override for the database alone, so the production checkout had to be the desk's
cwd and runtime output polluted the source tree (docs/ARCHITECTURE.md "Runtime state lives outside the source"). These controls
drive the real modules through a subprocess with the two variables set and unset, because
the roots are read at import.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import runtime_layout

REPO = Path(__file__).resolve().parent.parent


def test_linked_worktree_metadata_failure_refuses_local_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    linked = tmp_path / "linked"
    linked.mkdir()
    monkeypatch.setattr(runtime_layout, "SOURCE_ROOT", linked)

    (linked / ".git").write_text("not-a-gitdir", encoding="utf-8")
    with pytest.raises(RuntimeError, match="cannot resolve canonical runtime root"):
        runtime_layout._default_runtime_root()

    gitdir = tmp_path / "primary" / ".git" / "worktrees" / "linked"
    gitdir.mkdir(parents=True)
    (linked / ".git").write_text(f"gitdir: {gitdir}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="commondir missing"):
        runtime_layout._default_runtime_root()


def test_ambient_db_override_is_refused(tmp_path):
    rt = tmp_path / "runtime"
    explicit = tmp_path / "elsewhere" / "ed_console.db"
    explicit.parent.mkdir(parents=True)
    explicit.write_bytes(b"")
    env = dict(os.environ)
    env.update({"ED_RUNTIME_ROOT": str(rt), "ED_CONSOLE_DB": str(explicit)})
    result = subprocess.run(
        [sys.executable, "-c", "import db"],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0
    assert "ambient console database overrides are disabled" in result.stderr


def test_runtime_root_cannot_be_a_linked_worktree(tmp_path):
    linked = tmp_path / "linked"
    linked.mkdir()
    (linked / ".git").write_text("gitdir: ../primary/.git/worktrees/linked", encoding="utf-8")
    for runtime_root in (linked, linked / "runtime"):
        env = dict(os.environ)
        env["ED_RUNTIME_ROOT"] = str(runtime_root)
        result = subprocess.run(
            [sys.executable, "-c", "import runtime_layout"],
            cwd=str(REPO),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode != 0
        assert "cannot select a linked source worktree" in result.stderr
