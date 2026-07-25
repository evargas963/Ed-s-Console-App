#!/usr/bin/env python3
"""Run provenance block for execution / report JSON artifacts.

Stamps git identity + runtime so a result file is never orphaned from the
code that produced it (multi-agent / dirty-tree forensic need, 2026-07-25).
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]


def _git(*args: str) -> str | None:
    try:
        p = subprocess.run(
            ["git", *args],
            cwd=REPO,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if p.returncode != 0:
        return None
    return (p.stdout or "").strip() or None


def build_run_provenance() -> dict[str, Any]:
    sha = _git("rev-parse", "HEAD")
    porcelain = _git("status", "--porcelain")
    dirty = None if porcelain is None else bool(porcelain.strip())
    return {
        "git_commit": sha,
        "git_dirty": dirty,
        "python_version": sys.version.split()[0],
        "python_executable": str(Path(sys.executable).resolve()),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def stamp_report(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy with `run_provenance` injected (idempotent replace)."""
    out = dict(payload)
    out["run_provenance"] = build_run_provenance()
    return out
