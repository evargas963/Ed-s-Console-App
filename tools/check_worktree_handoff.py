#!/usr/bin/env python3
"""Git-shaped multi-agent handoff gate.

HEAD is the shared brain between Cursor and Claude. Uncommitted source edits are
invisible to the other agent and cause stale reads / overwrites. This gate fails
closed when protected source paths are dirty in the working tree.

    python tools/check_worktree_handoff.py

Exit 0 = clean handoff surface. Exit 1 = commit or stash before handoff.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _porcelain() -> list[str]:
    p = subprocess.run(
        ["git", "status", "--porcelain", "-uall"],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if p.returncode != 0:
        err = (p.stderr or p.stdout or "git status failed").strip()
        raise RuntimeError(err)
    return [ln for ln in (p.stdout or "").splitlines() if ln.strip()]


def _paths_from_line(line: str) -> list[str]:
    """Parse one porcelain line into path(s). Handles rename `->` form."""
    # "XY path" or "XY orig -> new" (rename/copy); untracked is "?? path"
    body = line[3:] if len(line) >= 3 else line
    body = body.strip()
    if " -> " in body:
        return [p.strip().strip('"') for p in body.split(" -> ", 1)]
    return [body.strip().strip('"')]


def is_protected_source(path: str) -> bool:
    """Protected surface: *.py, static/*, AGENTS.md, governance/*."""
    norm = path.replace("\\", "/").lstrip("./")
    if not norm or norm.endswith("/"):
        return False
    if norm == "AGENTS.md":
        return True
    if norm.startswith("governance/"):
        return True
    if norm.startswith("static/"):
        return True
    if norm.endswith(".py"):
        return True
    return False


def dirty_protected_paths(porcelain_lines: list[str] | None = None) -> list[str]:
    lines = _porcelain() if porcelain_lines is None else porcelain_lines
    found: set[str] = set()
    for ln in lines:
        for path in _paths_from_line(ln):
            if is_protected_source(path):
                found.add(path.replace("\\", "/"))
    return sorted(found)


def main() -> int:
    try:
        dirty = dirty_protected_paths()
    except RuntimeError as e:
        print(f"Handoff blocked: {e}", file=sys.stderr)
        return 1
    if dirty:
        print(
            "Handoff blocked: Uncommitted working tree changes. "
            "Commit or stash before handoff.",
            file=sys.stderr,
        )
        for p in dirty:
            print(f"  {p}", file=sys.stderr)
        return 1
    print("Handoff OK — protected source tree clean at HEAD.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
