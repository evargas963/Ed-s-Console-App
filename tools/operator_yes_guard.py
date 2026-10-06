"""OPERATOR YES GUARD: the actions an agent takes only with the operator's yes (CLAUDE.md rule 6).
PreToolUse for file edits and shell commands.

  * Starting, stopping or restarting the capture daemon or the console, merging a pull request
    and pushing to main change production.
  * Writes of a database under data/ (`data/*.db`, its -wal, -shm, -journal): the forms
    tests/test_operator_yes_guard_v1.py covers. This is not a complete barrier; the known gaps
    are listed in ENF-20 (ACTIVE_PROGRAM.md).

For each of these the hook answers "ask": Claude Code shows the operator the action with Allow
and Deny, and the agent cannot answer for them. Everything else passes untouched, tests included.

Limits: shell commands are judged on what they run; code inside `python -c` or a heredoc body is
data to the shell parser and is not judged here; for databases, what is judged is what the tests
cover, and the gaps are in ENF-20. The Edit and Write tools are judged in full.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.hook_chain import BASH_TOOLS, MUTATING_TOOLS  # noqa: E402
from tools.shell_parse import iter_command_segments, segment_head  # noqa: E402

#: shell heads that write, move or delete the paths they are given
WRITERS = frozenset({"rm", "del", "erase", "rmdir", "rd", "remove-item", "ri", "unlink", "mv",
                     "move", "move-item", "mi", "ren", "rename", "rename-item", "cp", "copy",
                     "copy-item", "cpi", "set-content", "sc", "add-content", "ac", "out-file",
                     "clear-content", "tee", "tee-object", "truncate", "sed", "perl"})
GIT_WRITERS = frozenset({"rm", "mv", "restore", "checkout"})
REDIRECT = re.compile(r"(?:^|[^<>&0-9])>{1,2}\s*(\"[^\"]*\"|'[^']*'|[^\s;&|]+)")
#: the production processes and what starts them
PROCESS_NAMES = ("streaming.capture", "uvicorn", "server:app")
LAUNCHERS = ("start_capture_daemon", "start_ed_console")
PROCESS_VERBS = ("stop-process", "taskkill", "kill ", "start-process", "restart")
MERGE = re.compile(r"\bgh\s+pr\s+merge\s+(\d+)|/pulls/(\d+)/merge\b", re.I)
PUSH_MAIN = re.compile(r"\bgit\b[^\n;&|]*\bpush\b[^\n;&|]*?(?:\s|:)main\b", re.I)
#: a database file under data/, and the programs that open one
DATA_DB = re.compile(r"(?:^|[\\/\s\"'=:])(data[\\/][^\\/\s\"'?;&|]+\.db(?:-wal|-shm|-journal)?)\b", re.I)
#: the writers whose last path is the one written (the others are read)
COPIERS = frozenset({"cp", "copy", "copy-item", "cpi"})
DB_PROGRAMS = frozenset({"python", "python3", "py", "sqlite3"})
READ_ONLY = ("mode=ro", "-readonly")


def _shell_reasons(cmd: str, cwd: str) -> list[str]:
    out = []
    for _cwd, seg in iter_command_segments(cmd, cwd):
        head, toks = segment_head(seg)
        args = [t for t in toks[1:] if not t.startswith("-")]
        targets = []
        if head in WRITERS and not (head == "sed" and "-i" not in toks and "--in-place" not in toks):
            targets = args
        elif head == "git" and len(toks) > 1 and toks[1] in GIT_WRITERS:
            targets = args[1:]
        targets += [m.group(1) for m in REDIRECT.finditer(seg)]
        written = [args[-1]] if head in COPIERS and args else targets      # a copy writes its destination
        out += [f"writes {m.group(1)}, a database under data/ (Records stand)"
                for m in filter(None, (DATA_DB.search(" " + t.strip("\"'")) for t in written))]
    low = cmd.lower()
    if (any(n in low for n in PROCESS_NAMES) and any(v in low for v in PROCESS_VERBS)) \
            or any(n in low for n in LAUNCHERS):
        out.append("starts, stops or restarts the daemon or the console (rule 6: production)")
    for m in MERGE.finditer(cmd):
        out.append(f"merges pull request {m.group(1) or m.group(2)} (rule 6: production)")
    if PUSH_MAIN.search(cmd):
        out.append("pushes to main (rule 6: production)")
    db = DATA_DB.search(cmd)
    heads = {segment_head(seg)[0].removesuffix(".exe") for _cwd, seg in iter_command_segments(cmd, cwd)}
    if db and not any(r in low for r in READ_ONLY) and (heads & DB_PROGRAMS or "sqlite3" in low):
        out.append(f"may write {db.group(1)}, a database under data/ (Records stand)")
    return out


def reasons(payload: dict) -> list[str]:
    """Why the action in `payload` needs the operator's yes; empty when it does not."""
    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input") or {}
    if tool in MUTATING_TOOLS:
        path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or tool_input.get("path") or "")
        db = DATA_DB.search(path)
        return [f"writes {db.group(1)}, a database under data/ (Records stand)"] if db else []
    if tool in BASH_TOOLS:
        return _shell_reasons(str(tool_input.get("command") or ""), str(payload.get("cwd") or ""))
    return []


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.stderr.write("BLOCKED: invalid hook payload.\n")
        return 2
    if not isinstance(payload, dict):
        sys.stderr.write("BLOCKED: the hook payload is not an object.\n")
        return 2
    why = reasons(payload)
    if why:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": "Needs the operator's yes: " + "; ".join(why)}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
