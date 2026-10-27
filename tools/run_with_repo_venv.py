#!/usr/bin/env python3
"""Re-exec a tool under this worktree's .venv (+ stale index.lock preflight).

Usage:
    python tools/run_with_repo_venv.py tools/check_institutional_correctness.py

CI (no .venv): runs the target with the current interpreter.
Local: requires .venv (auto-bootstrap when ED_AUTO_BOOTSTRAP_VENV=1).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _run(argv: list[str]) -> int:
    """Run the target and PROPAGATE its exit code.

    Not os.execv: on Windows there is no exec — CPython maps os.execv onto the CRT spawn
    family, so the parent would return immediately with status 0 while the target ran
    detached, and every pre-commit hook routed through here would report "Passed"
    whatever the gate found.

    subprocess.run inherits stdout/stderr, so hook output still reaches the operator, and it
    waits — which is the whole point.
    """
    return subprocess.run(argv, cwd=str(REPO)).returncode


def _venv_python() -> Path:
    if os.name == "nt":
        return REPO / ".venv" / "Scripts" / "python.exe"
    return REPO / ".venv" / "bin" / "python"


def _preflight_index_lock() -> None:
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    try:
        from tools.check_git_index_lock import clear_stale_index_lock
    except ImportError:
        return
    msg = clear_stale_index_lock()
    if msg:
        print(f"run_with_repo_venv: {msg}", file=sys.stderr)


def main() -> int:
    target = sys.argv[1:]
    if not target:
        print("usage: run_with_repo_venv.py <script> [args...]", file=sys.stderr)
        return 2
    _preflight_index_lock()
    in_ci = bool(os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"))
    vpy = _venv_python()
    if in_ci and not vpy.is_file():
        return _run([sys.executable, *target])
    if not vpy.is_file():
        auto = os.environ.get("ED_AUTO_BOOTSTRAP_VENV", "").strip().lower() in {
            "1", "true", "yes",
        }
        if auto:
            if str(REPO) not in sys.path:
                sys.path.insert(0, str(REPO))
            from tools.bootstrap_worktree_venv import ensure_venv
            ensure_venv(REPO, install_requirements=True)
            vpy = _venv_python()
        if not vpy.is_file():
            print(
                f"FATAL: {vpy} missing. Run: "
                f"python tools/bootstrap_worktree_venv.py",
                file=sys.stderr,
            )
            return 1
    return _run([str(vpy), *target])


if __name__ == "__main__":
    raise SystemExit(main())
