"""OPERATOR YES GUARD: the actions an agent takes only with the operator's yes (CLAUDE.md rules
5 and 6). PreToolUse for file edits and shell commands.

  * A test that already exists on origin/main (any file under tests/) is not edited, moved or
    deleted. New tests are free.
  * Starting, stopping or restarting the capture daemon or the console, merging a pull request
    and pushing to main change production.
  * A database under data/ (`data/*.db`) is written only with the operator's yes (AGENTS.md Records
    stand): an Edit or Write of the file, and a shell command naming one through a program that can
    open it (python, sqlite3) unless the command opens it read-only (`mode=ro`, `-readonly`).

For each of these the hook answers "ask": Claude Code shows the operator the action with Allow
and Deny, and the agent cannot answer for them. Everything else passes untouched.

Limits: shell commands are judged on what they run; code inside `python -c` or a heredoc body is
data to the shell parser and is not judged here, except that a database path named anywhere in the
command counts. A command that opens one database read-only and another writable is not told apart.
The Edit and Write tools are judged in full.
"""
from __future__ import annotations

import json
import re
import subprocess
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
DATA_DB = re.compile(r"(?:^|[\\/\s\"'=:])(data[\\/][^\\/\s\"'?;&|]+\.db)\b", re.I)
DB_PROGRAMS = frozenset({"python", "python3", "py", "sqlite3"})
READ_ONLY = ("mode=ro", "-readonly")


def _test_path(arg: str) -> str | None:
    """`tests/...` as git names it, for an argument that points into a tests/ folder."""
    p = arg.strip("\"'").replace("\\", "/")
    i = p.find("tests/")
    return p[i:] if i >= 0 and (i == 0 or p[i - 1] == "/") else None


def _on_main(rel: str) -> bool:
    try:
        return subprocess.run(["git", "cat-file", "-e", f"origin/main:{rel}"], cwd=str(REPO),
                              capture_output=True, timeout=15, check=False).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return True          # cannot tell: treat it as an existing test


def _existing_test(arg: str) -> str | None:
    rel = _test_path(arg)
    return rel if rel and _on_main(rel) else None


def _changes_test(rel: str) -> str:
    return f"changes {rel}, a test that exists on main (rule 5: tests are not changed to pass)"


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
        out += [_changes_test(rel) for rel in filter(None, map(_existing_test, targets))]
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
        rel = _existing_test(path)
        db = DATA_DB.search(path)
        return ([_changes_test(rel)] if rel else []) + \
            ([f"writes {db.group(1)}, a database under data/ (Records stand)"] if db else [])
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
