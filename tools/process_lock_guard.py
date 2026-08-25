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


def pretooluse_block(tool: str, tool_input: dict) -> list[str]:
    out: list[str] = []
    if tool in _EDIT_TOOLS:
        out.extend(cross_checkout_edit_violations(tool_input))
    if tool in ("Bash", "PowerShell", "Shell"):
        cmd = tool_input.get("command") or ""
        if re.search(r"\bgit\s+commit\b", cmd, re.I):
            out.extend(OPL.commit_violations())
            # RC-234: piped commits mask hook failures as exit 0 — block BEFORE it runs.
            out.extend(OPL.commit_pipe_violations(cmd))
        # LOCK-2 (RC-231): the tree-destructive git CLASS blocks BEFORE the tree is touched —
        # three 2026-08-03 wipes used soft forms the old --hard-literal ban never matched.
        out.extend(OPL.reset_guard_violations(cmd))
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

    if tool in _EDIT_TOOLS or tool in ("Bash", "PowerShell", "Shell"):
        bad = pretooluse_block(tool, ti)
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
