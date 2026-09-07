#!/usr/bin/env python3
"""ONE-APP LOCK (RC-350): report whether a checkout is a provable build of origin/main.

Lineage invariant: what runs on the desk should be a released commit of `main`, not a
detached HEAD, not a divergent lineage, not an uncommitted working tree.

WHERE THIS RUNS — corrected, RC-512. It claimed three fail-closed wiring points; two of
them never existed and the third was the harmful one:

  * pre-push — NEVER wired. `.pre-commit-config.yaml` sets `default_stages: [pre-commit]`
    and states in its own header that the pre-push stage has no hooks.
  * CI — NEVER wired. `.github/workflows/hardening.yml` and `pytest.yml` do not invoke it.
  * Server launch — the ONLY real wiring, and it has been REMOVED. It ran in
    start_ed_console.bat before `uvicorn` and aborted the launch on a non-zero exit, so
    repository position decided whether the desk could run. MEASURED 2026-09-03: the
    production checkout was 9 commits behind origin/main, and the launcher exited 1 with
    no application defect of any kind. It also opened with `git fetch origin main`, making
    app startup depend on reaching a remote.

So as wired, this file's sole effect was to stop the desk from starting. It is now an
AGENT/OPERATOR-side report, not a runtime gate: `violations()` is what the tests and any
operator invocation read, and callers decide what to do with it. Nothing on the
application runtime path consults it.

The lineage invariant itself is enforced where governance belongs — at the agent seam,
where it PREVENTS the divergence rather than punishing it at launch time.
`tools/process_lock_guard.py` blocks, on every PreToolUse event, an agent moving the
production checkout onto another branch, committing into it, or editing app code in it.
That enforcement predates this file's launch wiring and is unchanged by its removal.

Checks (all must pass):
  A. HEAD is on branch `main` — not detached, not a feature branch. The production checkout is
     the single live lineage; a feature branch or a detached snapshot is never the desk.
  B. HEAD == origin/main EXACTLY: zero commits ahead (`git rev-list --count origin/main..HEAD`
     == 0, no private divergent lineage) AND zero behind (`HEAD..origin/main` == 0, no stale
     desk). Invariant: production is always main == origin/main; land via PR, then fast-forward.
  C. The working tree has no uncommitted APP code (server.py, *.py, static/*.html,
     static/*.js). Docs/reports/scratch are ignored; app code is not.

Prevention, not detection, is where this invariant actually holds: the PreToolUse guard
(`tools/process_lock_guard.py`) BLOCKs, at the moment of the command, any git branch-move /
commit / reset / merge or app-code edit that targets the production checkout — so an assigned
agent cannot move the live checkout onto a feature branch in the first place. A-C below only
ever described a divergence that prevention had already refused, or one the OPERATOR chose,
which is the operator's call to make.

`ED_LIVE_PATH_UNLOCKED=1` is retained for callers that treat a non-zero exit as fatal: it
still prints every violation loudly, then returns 0. There is no longer a launch abort for it
to bypass (RC-512).
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


class GitProbeFailed(RuntimeError):
    """A git measurement did not run. NOT the same fact as "the measurement came back clean"."""

    def __init__(self, args: tuple[str, ...], rc: int, err: str) -> None:
        super().__init__(f"git {' '.join(args)} exited {rc}: {err}")
        self.probe = " ".join(args)
        self.rc = rc
        # git's fatals carry a multi-line usage hint; the first line is the reason.
        self.err = (err or "").splitlines()[0] if err else ""


def _git(*args: str) -> str:
    """Raw stdout of a git probe, RAISING when the child did not exit 0.

    RC-529 (ported from #219's RC-506; re-measured 2026-09-06 on ac3f78fb). The version that
    returned `.stdout.strip()` and dropped the CompletedProcess: in a checkout on branch main
    with a clean tree and no resolvable `origin/main`, both `rev-list --count` probes exit 128
    and print nothing. The callers read `if ahead and ahead != "0"`, so an EMPTY string — a
    crashed measurement — took the same branch as a measured zero, and this report printed
    "ONE-APP LOCK: PASS" for a lineage it had not measured.

    Two changes, both load-bearing:
      * non-zero now RAISES, so callers must decide; an unmeasurable fact is a violation.
      * stdout is returned RAW. The old `.strip()` also removed the leading status column of
        `git status --porcelain`, so the FIRST line's `ln[3:]` cut one character into the
        filename: ' M static/app.js' became 'tatic/app.js', which fails the `startswith
        ("static/")` test in _is_app_code and was silently dropped from check C.
    """
    p = subprocess.run(
        ["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if p.returncode != 0:
        raise GitProbeFailed(args, p.returncode, (p.stderr or "").strip())
    return p.stdout


def _git_line(*args: str) -> str:
    """A single-value git probe, stripped. Same fail-closed contract as _git."""
    return _git(*args).strip()


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
    try:
        head = _git_line("rev-parse", "--short", "HEAD")
    except GitProbeFailed:
        head = "an unreadable HEAD"
    # A. on branch `main` specifically — not detached, not a feature branch. The production
    #    checkout is the single live lineage (invariant #1); a feature branch or a detached
    #    snapshot is never the desk. (RC-350's original check accepted ANY non-detached branch,
    #    which let a feature-branch checkout pass — the exact drift that downed the desk.)
    #    `symbolic-ref` exits 128 on a legitimately detached HEAD, so failure here is EXPECTED
    #    and is itself the violation. Any OTHER non-zero means the branch is unmeasurable —
    #    also a violation, but it must not be reported as "detached", which would be a guess.
    branch, branch_unreadable = "", ""
    try:
        branch = _git_line("symbolic-ref", "--short", "HEAD")
    except GitProbeFailed as e:
        if "not a symbolic ref" not in e.err.lower():
            branch_unreadable = f"git exited {e.rc}: {e.err}"
    if branch != "main":
        where = (f"branch '{branch}'" if branch
                 else f"an UNREADABLE branch ({branch_unreadable})" if branch_unreadable
                 else f"a detached HEAD at {head}")
        out.append(
            f"the production checkout is on {where}, not `main`: the live desk runs ONLY "
            f"branch main == origin/main. Do development on the separate dev worktree and land "
            f"via PR; return production to main with `git checkout main`."
        )
    # B. HEAD == origin/main EXACTLY — zero ahead (no private divergent lineage) AND zero behind
    #    (no stale desk running code main has already moved past). Invariant #1 is equality;
    #    invariant #5 is merge-to-main-then-fast-forward. RC-529: "could not measure" is a
    #    violation, never a pass.
    try:
        ahead = _git_line("rev-list", "--count", "origin/main..HEAD")
        if not ahead.isdigit():
            out.append(
                f"HEAD vs origin/main returned no count ({ahead!r}), so the lineage is "
                f"UNPROVEN."
            )
        elif ahead != "0":
            out.append(
                f"{ahead} commit(s) on HEAD are NOT on origin/main: a private divergent "
                f"lineage is running. Merge them to main; the desk runs only released commits "
                f"of main."
            )
    except GitProbeFailed as e:
        out.append(
            f"HEAD vs origin/main could NOT be measured ({e.probe} exited {e.rc}: {e.err}). "
            f"origin/main is unresolvable in this checkout — a tree restored without remote "
            f"refs, or a remote removed or renamed. The lineage is UNPROVEN: 'could not "
            f"measure' is not 'measured clean'."
        )
    try:
        behind = _git_line("rev-list", "--count", "HEAD..origin/main")
        if not behind.isdigit():
            out.append(
                f"staleness vs origin/main returned no count ({behind!r}), so the lineage is "
                f"UNPROVEN."
            )
        elif behind != "0":
            out.append(
                f"HEAD is {behind} commit(s) BEHIND origin/main: the desk is running stale code. "
                f"Fast-forward production to origin/main (`git merge --ff-only origin/main`) "
                f"before launch — merge-then-fast-forward is how released code legally reaches "
                f"the live tree."
            )
    except GitProbeFailed as e:
        out.append(
            f"staleness vs origin/main could NOT be measured ({e.probe} exited {e.rc}: "
            f"{e.err}). The lineage is UNPROVEN."
        )
    # C. no uncommitted APP code
    try:
        porcelain = _git("status", "--porcelain")
    except GitProbeFailed as e:
        porcelain = ""
        out.append(
            f"the working tree could NOT be inspected ({e.probe} exited {e.rc}: {e.err}). "
            f"Whether the desk is running uncommitted code is UNKNOWN."
        )
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
