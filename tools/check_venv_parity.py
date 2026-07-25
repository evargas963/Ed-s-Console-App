#!/usr/bin/env python3
"""Virtual-environment parity gate — Claude and Cursor must share one interpreter.

OBSERVED (2026-07-25): multi-agent fracture when one agent runs global
Python (e.g. AppData\\…\\Python313) and another assumes a project venv —
packages, entry points, and hook installs drift silently.
VALIDATED: path check is deterministic (resolve + relative_to); CI runners
have no repo .venv so GITHUB_ACTIONS/CI skip; local/pre-commit fail closed.

    python tools/check_venv_parity.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _in_ci() -> bool:
    return bool(os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"))


def venv_parity_violations(executable: str | None = None) -> list[str]:
    if _in_ci():
        return []
    if os.environ.get("ED_CONSOLE_ALLOW_SYSTEM_PYTHON", "").strip() in {"1", "true", "yes"}:
        return []  # bootstrap escape only — not for routine agent work
    venv = (REPO / ".venv").resolve()
    if not venv.is_dir():
        return [
            "FATAL: .venv missing. Create it: "
            f"{sys.executable} -m venv .venv && "
            ".venv/Scripts/python -m pip install -r requirements.txt -r requirements-dev.txt "
            "(Unix: .venv/bin/python …). Then reinstall hooks with the venv interpreter."
        ]
    exe = Path(executable or sys.executable).resolve()
    try:
        exe.relative_to(venv)
    except ValueError:
        return [
            f"FATAL: sys.executable is outside .venv ({exe}). "
            "Activate .venv or invoke .venv/Scripts/python (Unix: .venv/bin/python). "
            "Global/local interpreter drift between agents is forbidden."
        ]
    return []


def main() -> int:
    v = venv_parity_violations()
    if v:
        print("check_venv_parity: FAIL")
        for line in v:
            print(f"  {line}")
        return 1
    print(f"check_venv_parity: PASS ({Path(sys.executable).resolve()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
