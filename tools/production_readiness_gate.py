#!/usr/bin/env python3
"""
Production readiness gate (full stack, code-grounded).

Runs:
- tools/validate_feature_contracts.py (non-zero exit on failure)
- verify_active_models.py (non-zero exit on failure)

Intended usage:
  python tools/production_readiness_gate.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _run(cmd: list[str]) -> int:
    print("+", " ".join(cmd))
    p = subprocess.run(cmd, cwd=str(Path(__file__).resolve().parents[1]))
    return int(p.returncode)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    rc = 0
    rc |= _run([sys.executable, str(root / "tools" / "validate_feature_contracts.py")])
    rc |= _run([sys.executable, str(root / "verify_active_models.py")])
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
