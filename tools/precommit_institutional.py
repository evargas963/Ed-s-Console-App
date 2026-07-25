#!/usr/bin/env python3
"""Pre-commit entry: institutional gate under primary (cursor) worktree role.

Local pre-commit hooks do not honor an ``env:`` map on ``repo: local`` entries
(pre-commit warns and ignores it). This wrapper sets ED_AGENT_ROLE=cursor
explicitly for the primary-checkout hook, then re-execs via run_with_repo_venv.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    os.environ["ED_AGENT_ROLE"] = "cursor"
    runner = REPO / "tools" / "run_with_repo_venv.py"
    gate = REPO / "tools" / "check_institutional_correctness.py"
    os.execv(sys.executable, [sys.executable, str(runner), str(gate)])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
