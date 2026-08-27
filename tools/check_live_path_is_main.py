#!/usr/bin/env python3
"""ONE-APP LOCK (RC-350): the running app must be a provable build of origin/main.

World-class invariant: there is exactly one lineage. What runs on the desk is a
released commit of `main`, never a detached HEAD, never a divergent lineage, never
an uncommitted working tree. This guard is the mechanical enforcement of that.

Wire it in three places (all fail-closed):
  1. Server launch  — start_ed_console.bat calls this BEFORE `uvicorn`; a non-zero
     exit aborts the launch. The desk cannot run code that is not on main.
  2. pre-push hook  — refuses to push a branch whose tip is not built on main.
  3. CI             — the same check runs on every PR.

Checks (all must pass):
  A. HEAD is on branch `main` — not detached, not a feature branch. The production checkout is
     the single live lineage; a feature branch or a detached snapshot is never the desk.
  B. HEAD == origin/main EXACTLY: zero commits ahead (`git rev-list --count origin/main..HEAD`
     == 0, no private divergent lineage) AND zero behind (`HEAD..origin/main` == 0, no stale
     desk). Invariant: production is always main == origin/main; land via PR, then fast-forward.
  C. The working tree has no uncommitted APP code (server.py, *.py, static/*.html,
     static/*.js). Docs/reports/scratch are ignored; app code is not.

Prevention, not just detection: A-C run at launch / pre-push / CI (fail-closed). The PreToolUse
guard (`tools/process_lock_guard.py`) additionally BLOCKs, at the moment of the command, any git
branch-move / commit / reset / merge or app-code edit that targets the production checkout — so an
assigned agent cannot move the live checkout onto a feature branch in the first place, rather than
this check catching the divergence only at the next launch.

Emergency bypass: `ED_LIVE_PATH_UNLOCKED=1` skips the launch abort but STILL prints
the violation loudly and logs it — use only to recover a downed desk, never as a
habit. Every bypass is a visible admission that the invariant was broken.
"""
from __future__ import annotations

import os
import subprocess
import sys

APP_CODE_PREFIXES = ("server.py", "db.py")
APP_CODE_SUFFIXES = (".py",)
APP_UI_PREFIXES = ("static/",)
APP_UI_SUFFIXES = (".html", ".js")
# Non-app paths whose uncommitted state does not gate a launch.
IGNORE_SUFFIXES = (".md", ".txt", ".json", ".jsonl", ".log", ".csv", ".mdc")
IGNORE_PREFIXES = ("reports/", "governance/", "scratchpad/", ".claude/", "docs/")


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace"
    ).stdout.strip()


def _is_app_code(path: str) -> bool:
    if any(path.startswith(p) for p in IGNORE_PREFIXES):
        return False
    if path.endswith(IGNORE_SUFFIXES):
        return False
    if path in APP_CODE_PREFIXES or path.endswith(APP_CODE_SUFFIXES):
        return True
    if any(path.startswith(p) for p in APP_UI_PREFIXES) and path.endswith(APP_UI_SUFFIXES):
        return True
    return False


def violations() -> list[str]:
    out: list[str] = []
    head = _git("rev-parse", "--short", "HEAD")
    # A. on branch `main` specifically — not detached, not a feature branch. The production
    #    checkout is the single live lineage (invariant #1); a feature branch or a detached
    #    snapshot is never the desk. (RC-350's original check accepted ANY non-detached branch,
    #    which let a feature-branch checkout pass — the exact drift that downed the desk.)
    branch = _git("symbolic-ref", "--short", "HEAD")   # "" when detached
    if branch != "main":
        where = f"branch '{branch}'" if branch else f"a detached HEAD at {head}"
        out.append(
            f"the production checkout is on {where}, not `main`: the live desk runs ONLY "
            f"branch main == origin/main. Do development on the separate dev worktree and land "
            f"via PR; return production to main with `git checkout main`."
        )
    # B. HEAD == origin/main EXACTLY — zero ahead (no private divergent lineage) AND zero behind
    #    (no stale desk running code main has already moved past). Invariant #1 is equality;
    #    invariant #5 is merge-to-main-then-fast-forward.
    ahead = _git("rev-list", "--count", "origin/main..HEAD")
    if ahead and ahead != "0":
        out.append(
            f"{ahead} commit(s) on HEAD are NOT on origin/main: a private divergent "
            f"lineage is running. Merge them to main; the desk runs only released commits of main."
        )
    behind = _git("rev-list", "--count", "HEAD..origin/main")
    if behind and behind != "0":
        out.append(
            f"HEAD is {behind} commit(s) BEHIND origin/main: the desk is running stale code. "
            f"Fast-forward production to origin/main (`git merge --ff-only origin/main`) before "
            f"launch — merge-then-fast-forward is how released code legally reaches the live tree."
        )
    # C. no uncommitted APP code
    porcelain = _git("status", "--porcelain")
    dirty_app = sorted(
        {ln[3:].split(" -> ")[-1] for ln in porcelain.splitlines()
         if ln[3:] and _is_app_code(ln[3:].split(" -> ")[-1])}
    )
    if dirty_app:
        shown = ", ".join(dirty_app[:8]) + (f" (+{len(dirty_app) - 8} more)" if len(dirty_app) > 8 else "")
        out.append(
            f"{len(dirty_app)} uncommitted APP file(s) — the running code exists only in the "
            f"working tree, not in any commit: {shown}. Commit to a branch and merge to main."
        )
    return out


def main() -> int:
    try:
        subprocess.run(["git", "fetch", "origin", "main", "--quiet"], timeout=30)
    except Exception:
        # institutional-swallow-ok: offline/unreachable-remote launch must not brick the
        # desk; checks A-C still run against the last-fetched origin/main ref, so the
        # guard degrades to last-known-truth rather than failing open or crashing.
        pass
    viol = violations()
    if not viol:
        print("ONE-APP LOCK: PASS — the running app is a provable build of origin/main.")
        return 0
    print("=" * 72, file=sys.stderr)
    print("ONE-APP LOCK VIOLATED (RC-350): the desk is NOT running origin/main.", file=sys.stderr)
    for v in viol:
        print(f"  - {v}", file=sys.stderr)
    print("=" * 72, file=sys.stderr)
    if os.environ.get("ED_LIVE_PATH_UNLOCKED") == "1":
        print("ED_LIVE_PATH_UNLOCKED=1 — launch permitted under emergency bypass (LOGGED).", file=sys.stderr)
        return 0
    print("Set ED_LIVE_PATH_UNLOCKED=1 to override for emergency recovery only.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
