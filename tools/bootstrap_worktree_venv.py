#!/usr/bin/env python3
"""Provision an isolated .venv for the current git worktree.

Each agent worktree gets its own .venv (not a shared symlink) so Cursor and
Claude cannot collide on site-packages or interpreter identity.

    python tools/bootstrap_worktree_venv.py
    python tools/bootstrap_worktree_venv.py --venv-only   # create, skip pip

OBSERVED (2026-07-25): multi-agent worktrees without per-tree venvs fell back
to global Python313 and drifted. VALIDATED: path checks in check_venv_parity.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import venv
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def venv_python(repo: Path | None = None) -> Path:
    root = repo or REPO
    if os.name == "nt":
        return root / ".venv" / "Scripts" / "python.exe"
    return root / ".venv" / "bin" / "python"


def ensure_venv(
    repo: Path | None = None,
    *,
    install_requirements: bool = True,
) -> Path:
    """Create .venv if missing; optionally pip-install requirements*.txt."""
    root = (repo or REPO).resolve()
    vpy = venv_python(root)
    if not vpy.is_file():
        print(f"bootstrap_worktree_venv: creating {root / '.venv'} …")
        venv.EnvBuilder(with_pip=True, clear=False, upgrade=False).create(
            str(root / ".venv")
        )
    if not vpy.is_file():
        raise RuntimeError(f"venv python missing after create: {vpy}")
    if install_requirements:
        reqs = [
            root / "requirements.txt",
            root / "requirements-dev.txt",
        ]
        for req in reqs:
            if not req.is_file():
                print(f"bootstrap_worktree_venv: skip missing {req.name}")
                continue
            print(f"bootstrap_worktree_venv: pip install -r {req.name} …")
            subprocess.run(
                [str(vpy), "-m", "pip", "install", "--upgrade", "pip"],
                cwd=root,
                check=True,
            )
            subprocess.run(
                [str(vpy), "-m", "pip", "install", "-r", str(req)],
                cwd=root,
                check=True,
            )
    print(f"bootstrap_worktree_venv: OK -> {vpy}")
    return vpy


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--venv-only",
        action="store_true",
        help="Create .venv but skip pip install (fast / CI bootstrap).",
    )
    ap.add_argument(
        "--repo",
        type=Path,
        default=None,
        help="Worktree root (default: this repo).",
    )
    args = ap.parse_args()
    try:
        ensure_venv(args.repo, install_requirements=not args.venv_only)
    except (RuntimeError, subprocess.CalledProcessError) as e:
        print(f"bootstrap_worktree_venv: FAIL — {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
