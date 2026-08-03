"""Front-end hook for operating_process_lock (RC-217).

Runs on PreToolUse (Edit/Write/Bash) and Stop. Exit 2 BLOCKS.
Escape: ED_PROCESS_LOCK_GUARD=off (operator only).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import tools.operating_process_lock as OPL  # noqa: E402


def _tool_new_text(tool_input: dict) -> str:
    chunks: list[str] = []
    for key in ("content", "new_string"):
        v = tool_input.get(key)
        if isinstance(v, str) and v:
            chunks.append(v)
    edits = tool_input.get("edits")
    if isinstance(edits, list):
        for ed in edits:
            if isinstance(ed, dict):
                ns = ed.get("new_string")
                if isinstance(ns, str) and ns:
                    chunks.append(ns)
    return "\n".join(chunks)


def _rel(fp: str) -> str:
    return OPL._rel(fp)


def pretooluse_block(tool: str, tool_input: dict) -> list[str]:
    out: list[str] = []
    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        fp = tool_input.get("file_path") or ""
        if fp:
            rel = _rel(fp)
            msg = OPL.sole_writer_edit_violation(rel)
            if msg:
                out.append(msg)
    if tool in ("Bash", "PowerShell"):
        cmd = tool_input.get("command") or ""
        if __import__("re").search(r"\bgit\s+commit\b", cmd, __import__("re").I):
            out.extend(OPL.commit_violations())
    return out


def stop_block(payload: dict) -> list[str]:
    out: list[str] = []
    transcript = payload.get("transcript_path") or ""
    text = ""
    if transcript:
        try:
            from tools.proof_only_guard import last_assistant_text
            text = last_assistant_text(transcript) or ""
        except Exception:
            pass
    if text:
        out.extend(OPL.completion_claim_violations(text))
    # Always surface index≠WT at stop if enforcement parity fails (auditor window).
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
    if os.environ.get("ED_PROCESS_LOCK_GUARD", "").strip().lower() in ("off", "0", "false"):
        return 0
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    if payload.get("stop_hook_active") is True:
        return 0

    tool = payload.get("tool_name") or ""
    ti = payload.get("tool_input") or {}

    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit", "Bash", "PowerShell"):
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
        + "\nSee governance/AGENT_OPERATING_PROCESS_V1.md and tools/operating_process_lock.py --measure\n"
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
