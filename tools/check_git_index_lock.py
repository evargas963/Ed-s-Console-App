#!/usr/bin/env python3
"""Stale git index.lock defense (multi-agent / interrupted commit).

A live ``git commit`` holds index.lock briefly. A crashed agent can leave it
forever and starve the other worktree's commits. This helper removes ONLY
locks older than STALE_SEC (default 60).

    python tools/check_git_index_lock.py
    python tools/check_git_index_lock.py --clear

OBSERVED (2026-07-25): concurrent Cursor/Claude git ops hit index.lock
starvation after aborted commits. VALIDATED: mtime threshold; never deletes
fresh locks.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STALE_SEC = 60.0


def _git_dir(repo: Path) -> Path:
    p = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout or "git rev-parse failed").strip())
    gd = Path(p.stdout.strip())
    if not gd.is_absolute():
        gd = (repo / gd).resolve()
    return gd


def index_lock_path(repo: Path | None = None) -> Path:
    return _git_dir(repo or REPO) / "index.lock"


def stale_index_lock_info(
    repo: Path | None = None,
    *,
    stale_sec: float = STALE_SEC,
    now: float | None = None,
) -> tuple[Path, float] | None:
    """Return (lock_path, age_sec) if a stale lock exists; else None."""
    lock = index_lock_path(repo)
    if not lock.is_file():
        return None
    age = (now if now is not None else time.time()) - lock.stat().st_mtime
    if age < stale_sec:
        return None
    return lock, age


def clear_stale_index_lock(
    repo: Path | None = None,
    *,
    stale_sec: float = STALE_SEC,
) -> str | None:
    """Remove stale index.lock. Returns a message if cleared, else None."""
    info = stale_index_lock_info(repo, stale_sec=stale_sec)
    if info is None:
        return None
    lock, age = info
    lock.unlink(missing_ok=True)
    return f"cleared stale index.lock age={age:.1f}s path={lock}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--clear",
        action="store_true",
        help=f"Delete index.lock if older than {STALE_SEC:.0f}s.",
    )
    ap.add_argument("--stale-sec", type=float, default=STALE_SEC)
    args = ap.parse_args()
    try:
        info = stale_index_lock_info(stale_sec=args.stale_sec)
    except RuntimeError as e:
        print(f"check_git_index_lock: FAIL — {e}", file=sys.stderr)
        return 1
    if info is None:
        print("check_git_index_lock: OK (no stale index.lock)")
        return 0
    lock, age = info
    print(
        f"check_git_index_lock: STALE index.lock age={age:.1f}s path={lock}",
        file=sys.stderr,
    )
    if not args.clear:
        print("Re-run with --clear to remove it.", file=sys.stderr)
        return 1
    msg = clear_stale_index_lock(stale_sec=args.stale_sec)
    print(f"check_git_index_lock: {msg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
