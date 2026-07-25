#!/usr/bin/env python3
"""Re-exec a tool under repo .venv (multi-agent interpreter parity).

Usage:
    python tools/run_with_repo_venv.py tools/check_institutional_correctness.py

CI (no .venv): runs the target with the current interpreter.
Local: requires .venv and re-execs into it.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _venv_python() -> Path:
    if os.name == "nt":
        return REPO / ".venv" / "Scripts" / "python.exe"
    return REPO / ".venv" / "bin" / "python"


def main() -> int:
    target = sys.argv[1:]
    if not target:
        print("usage: run_with_repo_venv.py <script> [args...]", file=sys.stderr)
        return 2
    in_ci = bool(os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"))
    vpy = _venv_python()
    if in_ci and not vpy.is_file():
        os.execv(sys.executable, [sys.executable, *target])
    if not vpy.is_file():
        print(
            f"FATAL: {vpy} missing. Create .venv before running gates.",
            file=sys.stderr,
        )
        return 1
    if Path(sys.executable).resolve() != vpy.resolve():
        os.execv(str(vpy), [str(vpy), *target])
    os.execv(str(vpy), [str(vpy), *target])
    return 0  # unreachable


if __name__ == "__main__":
    raise SystemExit(main())
