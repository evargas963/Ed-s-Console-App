"""Front-end hook for operating_process_lock (RC-217).

Runs on PreToolUse (Edit/Write/StrReplace/Bash). RC-471 removed the Stop registration;
stop_block() is retained for manual/test use. Exit 2 BLOCKS.
No env kill-switch: ED_PROCESS_LOCK_GUARD cannot disable this control (RC-450).
2026-08-24 teardown: the role/authority rails (writer_drift_lock, isolated-worktree
boundary, mission gating, GO closeout) are gone with Architecture A — what remains is
process integrity: index parity, LIVE-vs-DISK, destructive-git and piped-commit blocks.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import tools.operating_process_lock as OPL  # noqa: E402
from tools.operator_law_guard import (  # noqa: E402
    _tokens,
    git_target_repo,
    normalize_repo,
    shell_executed_part,
)
from tools.pretooluse_guard import classify_path  # noqa: E402

#: Cursor continuum tools that mutate files (RC-226: StrReplace/path were previously ignored).
_EDIT_TOOLS = (
    "Edit",
    "Write",
    "MultiEdit",
    "NotebookEdit",
    "StrReplace",
    "Delete",
)


#: Keys across the two continua that carry an edit target path.
_EDIT_TARGET_KEYS = ("file_path", "notebook_path", "path")


def _primary_worktree_root(repo: Path) -> Path | None:
    """The PRIMARY working tree root when `repo` is a LINKED worktree; None when `repo`
    IS the primary (its .git is a directory) or the layout is unreadable.

    Pure file logic, no subprocess: a linked worktree's `.git` is a FILE reading
    `gitdir: <primary>/.git/worktrees/<name>`; the primary root is the path above `.git`.
    """
    dotgit = repo / ".git"
    if not dotgit.is_file():
        return None
    try:
        text = dotgit.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(r"^gitdir:\s*(.+?)\s*$", text, re.M)
    if not m:
        return None
    gitdir = Path(m.group(1))
    # <primary>/.git/worktrees/<name> -> <primary>
    for parent in gitdir.parents:
        if parent.name == ".git":
            return parent.parent
    return None


def cross_checkout_edit_violations(tool_input: dict, repo: Path = REPO) -> list[str]:
    """RC-442(a), restored role-free (RC-477): a session running in a LINKED worktree may not
    Edit/Write a file inside the PRIMARY working tree — that is the live/production checkout,
    and endangering it from a side checkout is the exact 2026-08-20 hazard. The 2026-08-24
    teardown removed the role-based form of this rail with Architecture A; this form reads
    only the filesystem topology (which checkout am I, where does the target resolve) and
    names no agent. The primary session editing a linked worktree is not blocked — that is
    the operator-visible direction. Fail-open on unresolvable paths: this rail blocks only
    on an affirmative cross-checkout hit."""
    primary = _primary_worktree_root(repo)
    if primary is None:
        return []
    out: list[str] = []
    for key in _EDIT_TARGET_KEYS:
        raw = tool_input.get(key)
        if not raw or not isinstance(raw, str):
            continue
        try:
            target = Path(raw)
            if not target.is_absolute():
                target = repo / target
            resolved = target.resolve()
            resolved.relative_to(primary.resolve())
        except (OSError, ValueError):
            continue
        out.append(
            f"CROSS_CHECKOUT_EDIT (RC-442/RC-477): this session runs in the linked worktree "
            f"{repo} but targets {resolved} inside the PRIMARY working tree {primary} — the "
            f"live checkout. Edit it from its own session, or hand the change over via "
            f"branch/PR."
        )
    return out


#: Git subcommands that move HEAD, create/re-point/delete a branch, or write history in the
#: checkout they run against. On the production primary these are refused; reads, fetch, the
#: fast-forward-to-origin/main update, and return-to-main are allowed (_prod_forbidden_git_reason).
_PROD_MOVE_SUBCOMMANDS = frozenset({
    "commit", "reset", "rebase", "cherry-pick", "revert", "am",
    "merge", "pull", "checkout", "switch", "branch",
})
_GIT_GLOBAL_WITH_ARG = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace",
                                  "--super-prefix", "--exec-path"})


def _prod_forbidden_git_reason(cmd: str) -> str | None:
    """For a git command already known to TARGET the production primary, return WHY it is
    forbidden there, or None if it is an allowed production operation. Parses one git
    invocation: strip `git` + global options, then classify the subcommand and its args.
    ALLOWED on production: reads/fetch; `git merge|pull --ff-only origin/main` (the
    merge-then-fast-forward update, invariant #5); `git checkout|switch main` (return to main);
    `git checkout -- <path>` file-restore (left to the destructive-git rail)."""
    toks = [t.strip("\"'") for t in _tokens(shell_executed_part(cmd or ""))]
    gi = next((i for i, t in enumerate(toks)
               if Path(t).name.lower() in ("git", "git.exe")), -1)
    if gi < 0:
        return None
    rest = toks[gi + 1:]
    i = 0
    while i < len(rest):                 # skip git GLOBAL options up to the subcommand
        t = rest[i]
        if any(t.startswith(p + "=") for p in _GIT_GLOBAL_WITH_ARG):
            i += 1
        elif t in _GIT_GLOBAL_WITH_ARG:
            i += 2                       # option + its separate value (e.g. `-C <path>`)
        elif t.startswith("-"):
            i += 1                       # -P/--no-pager/--paginate/--bare/other no-arg globals
        else:
            break
    if i >= len(rest):
        return None                      # bare `git` with no subcommand
    sub = rest[i]
    args = rest[i + 1:]
    if sub not in _PROD_MOVE_SUBCOMMANDS:
        return None                      # status/log/diff/show/add/fetch/worktree/stash/... allowed
    if sub in ("checkout", "switch"):
        if "--" in args:
            return None                  # file-restore, not a branch move
        creates = any(a in ("-b", "-B", "-c", "-C") for a in args)
        refs = [a for a in args if not a.startswith("-")]
        if not creates and refs == ["main"]:
            return None                  # return-to-main recovery is sanctioned
        if creates:
            return f"`git {sub} -b` creates/moves onto a new branch"
        return f"`git {sub} {refs[0] if refs else ''}`".rstrip() + " moves the checkout off main"
    if sub in ("merge", "pull"):
        ff = "--ff-only" in args
        refs = [a for a in args if not a.startswith("-")]
        if ff and refs in ([], ["origin/main"], ["origin", "main"]):
            return None                  # the fast-forward-to-origin/main production update
        return f"`git {sub}` (only `--ff-only origin/main` is allowed on production)"
    if sub == "branch":
        mutating = any(a in ("-m", "-M", "-c", "-C", "-d", "-D", "-f", "--force", "--move",
                             "--copy", "--delete", "--edit-description") for a in args)
        creates = any(not a.startswith("-") for a in args)
        return "`git branch` creates/moves/deletes a branch" if (mutating or creates) else None
    return f"`git {sub}` writes history / moves HEAD in the checkout"


def prod_checkout_git_move_violations(cmd: str, payload_cwd: str = "") -> list[str]:
    """PREVENT (not merely detect) an assigned agent MOVING or committing to the PRODUCTION
    checkout (live-checkout invariant #1/#4). The production checkout is the PRIMARY working
    tree of this repo (its `.git` is a directory; linked dev worktrees have a `.git` FILE). This
    fires whenever a git command TARGETS that primary — whichever checkout the session runs in —
    and the verb would move HEAD off main, create/re-point a branch, or write history there.
    Dev worktrees are unconstrained; branch work belongs there. RC-350 caught this divergence
    only at the next launch — this refuses it at the moment of the command. Not
    subject-disableable (RC-450)."""
    primary = _primary_worktree_root(REPO) or REPO
    try:
        primary_norm = normalize_repo(primary)
    except (OSError, ValueError):
        return []
    target = git_target_repo(cmd or "", payload_cwd or "")
    if not target or target != primary_norm:
        return []                        # not targeting the production checkout
    reason = _prod_forbidden_git_reason(cmd or "")
    if not reason:
        return []                        # a read / fetch / ff-update / return-to-main
    return [
        f"PROD_CHECKOUT_LOCK (live-checkout invariant / RC-350): {reason} in the PRODUCTION "
        f"checkout {primary}. That checkout is production ONLY — always main == origin/main. Do "
        f"this in the separate dev worktree and land via PR; production updates by fast-forward "
        f"to origin/main. See governance/AGENT_OPERATING_PROCESS_V1.md."
    ]


def production_checkout_app_edit_violations(tool_input: dict, repo: Path = REPO) -> list[str]:
    """PREVENT an assigned agent EDITING app code in the PRODUCTION checkout (invariant #4).

    The symmetric companion to cross_checkout_edit_violations: that rail stops a LINKED worktree
    reaching INTO the primary; this stops the session that IS the primary from editing product
    code in place. Fires only when this session runs in the production primary
    (`_primary_worktree_root` is None) and the Edit/Write target resolves INSIDE it AND is a
    production path (server.py, *.py, static/*.html|*.js — governance/docs/reports/tests are not
    app code). A dev-worktree file edited from the primary session resolves OUTSIDE the primary
    and is not blocked. Not subject-disableable (RC-450)."""
    if _primary_worktree_root(repo) is not None:
        return []                        # this session is a linked dev worktree — unconstrained
    try:
        primary = repo.resolve()
    except (OSError, ValueError):
        return []
    out: list[str] = []
    for key in _EDIT_TARGET_KEYS:
        raw = tool_input.get(key)
        if not raw or not isinstance(raw, str):
            continue
        try:
            target = Path(raw)
            if not target.is_absolute():
                target = repo / target
            resolved = target.resolve()
            resolved.relative_to(primary)    # must be inside the production tree
        except (OSError, ValueError):
            continue
        if classify_path(str(resolved), repo=str(primary)).production:
            out.append(
                f"PROD_CHECKOUT_APP_EDIT (live-checkout invariant): {resolved} is app code in the "
                f"PRODUCTION checkout {primary}. Development does not edit the live checkout — make "
                f"the change in the separate dev worktree and land via PR. "
                f"See governance/AGENT_OPERATING_PROCESS_V1.md."
            )
    return out


def pretooluse_block(tool: str, tool_input: dict, payload_cwd: str = "") -> list[str]:
    out: list[str] = []
    if tool in _EDIT_TOOLS:
        out.extend(cross_checkout_edit_violations(tool_input))
        # Live-checkout invariant #4: the primary SESSION may not edit app code in the production
        # checkout (the symmetric companion to the linked->primary rail above).
        out.extend(production_checkout_app_edit_violations(tool_input))
    if tool in ("Bash", "PowerShell", "Shell"):
        cmd = tool_input.get("command") or ""
        if re.search(r"\bgit\s+commit\b", cmd, re.I):
            out.extend(OPL.commit_violations())
            # RC-234: piped commits mask hook failures as exit 0 — block BEFORE it runs.
            out.extend(OPL.commit_pipe_violations(cmd))
        # LOCK-2 (RC-231): the tree-destructive git CLASS blocks BEFORE the tree is touched —
        # three 2026-08-03 wipes used soft forms the old --hard-literal ban never matched.
        out.extend(OPL.reset_guard_violations(cmd))
        # Live-checkout invariant #1/#4: PREVENT a git branch-move/commit/reset/merge that
        # TARGETS the production checkout, at the moment of the command (not just at next launch).
        out.extend(prod_checkout_git_move_violations(cmd, payload_cwd))
    return out


def stop_block(payload: dict) -> list[str]:
    out: list[str] = []
    transcript = payload.get("transcript_path") or ""
    text = ""
    if transcript:
        try:
            from tools.proof_only_guard import last_assistant_text
            text = last_assistant_text(transcript) or ""
        except Exception:  # institutional-swallow-ok: guard must fail-open on transcript read, never hang a Stop; index/DISK checks below still run
            pass
    if text:
        out.extend(OPL.completion_claim_violations(text))
    mism = OPL.index_worktree_mismatches()
    if mism:
        out.append(
            "AUDITOR WINDOW: index≠WT on enforcement paths — re-prove before ending turn: "
            + "; ".join(mism[:5])
        )
    disk = OPL.live_collect_disk_only()
    if disk:
        out.append(f"LIVE vs DISK: {disk}")
    return out


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    if payload.get("stop_hook_active") is True:
        return 0

    tool = payload.get("tool_name") or ""
    ti = payload.get("tool_input") or {}
    payload_cwd = str(payload.get("cwd") or "")

    if tool in _EDIT_TOOLS or tool in ("Bash", "PowerShell", "Shell"):
        bad = pretooluse_block(tool, ti, payload_cwd)
    elif not tool or tool == "Stop":
        bad = stop_block(payload)
    else:
        return 0

    if not bad:
        return 0
    sys.stderr.write(
        "BLOCKED by operating process lock (RC-217 / AGENT_OPERATING_PROCESS_V1).\n\n"
        + "".join(f"  {b}\n" for b in bad)
        + "\nSee governance/AGENT_OPERATING_PROCESS_V1.md, "
        + "tools/operating_process_lock.py --measure\n"
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
