#!/usr/bin/env python3
"""ONE-APP LOCK (RC-350): the running app must be a provable build of origin/main.

World-class invariant: there is exactly one lineage. What runs on the desk is a
released commit of `main`, never a detached HEAD, never a divergent lineage, never
an uncommitted working tree. This guard is the mechanical enforcement of that.

Classification: REQUIRED_CONTROL at Windows desk launch only
  (`start_ed_console.bat` calls this BEFORE uvicorn; non-zero aborts).

NOT a PR/CI control: check B (`origin/main..HEAD == 0`) is true only for
released main, so wiring this to pull_request CI would fail every honest
feature branch. pre-push hooks are retired. Those two advertisements were
phantom enforcement and are withdrawn.

Emergency bypass: `ED_LIVE_PATH_UNLOCKED=1` skips the launch abort but STILL prints
the violation loudly and logs it — use only to recover a downed desk, never as a
habit. Every bypass is a visible admission that the invariant was broken.

Checks (all must pass):
  A. HEAD is NOT detached (you are on a branch or a tag that resolves onto main).
  B. HEAD has ZERO commits that are not on origin/main
     (`git rev-list --count origin/main..HEAD` == 0) — i.e. what runs is released,
     not a private divergent lineage.
  C. The working tree has no uncommitted APP code (server.py, *.py, static/*.html,
     static/*.js). Docs/reports/scratch are ignored; app code is not.
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
    # A. not detached
    on_branch = subprocess.run(
        ["git", "symbolic-ref", "-q", "HEAD"], capture_output=True
    ).returncode == 0
    head = _git("rev-parse", "--short", "HEAD")
    if not on_branch:
        # a tag that is an ancestor of origin/main is acceptable (a release point)
        tag = _git("describe", "--tags", "--exact-match") if not on_branch else ""
        if not tag:
            out.append(
                f"DETACHED HEAD at {head}: the desk is running a snapshot on no branch. "
                f"Run from `main` or a release tag."
            )
    # B. no commits ahead of origin/main (what runs must be released)
    ahead = _git("rev-list", "--count", "origin/main..HEAD")
    if ahead and ahead != "0":
        out.append(
            f"{ahead} commit(s) on HEAD are NOT on origin/main: a private divergent "
            f"lineage is running. Merge them to main; the desk runs only ancestors of main."
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
