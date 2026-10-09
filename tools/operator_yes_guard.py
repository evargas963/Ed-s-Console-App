"""OPERATOR YES GUARD: the actions an agent takes only with the operator's yes (CLAUDE.md rule 6).
PreToolUse for shell commands.

  * Starting, stopping or restarting the capture daemon or the console, merging a pull request
    and pushing to main change production.

For each of these the hook answers "ask": Claude Code shows the operator the action with Allow
and Deny, and the agent cannot answer for them. Everything else passes untouched.

Limits: shell commands are judged on what they run; code inside `python -c` or a heredoc body is
data to the shell parser and is not judged here.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.hook_chain import BASH_TOOLS  # noqa: E402

#: the production processes and what starts them
PROCESS_NAMES = ("streaming.capture", "uvicorn", "server:app")
LAUNCHERS = ("start_capture_daemon", "start_ed_console")
#: launch.py run by a Python (naming the file, as `git add launch.py` does, is not running it)
LAUNCH_PY = re.compile(r"python[\w.]*[\"']?\s+(?:\S*[\\/])?launch\.py\b", re.I)
PROCESS_VERBS = ("stop-process", "taskkill", "kill ", "start-process", "restart")
MERGE = re.compile(r"\bgh\s+pr\s+merge\s+(\d+)|/pulls/(\d+)/merge\b", re.I)
PUSH_MAIN = re.compile(r"\bgit\b[^\n;&|]*\bpush\b[^\n;&|]*?(?:\s|:)main\b", re.I)


def _shell_reasons(cmd: str) -> list[str]:
    out = []
    low = cmd.lower()
    if (any(n in low for n in PROCESS_NAMES) and any(v in low for v in PROCESS_VERBS)) \
            or any(n in low for n in LAUNCHERS) or LAUNCH_PY.search(cmd):
        out.append("starts, stops or restarts the daemon or the console (rule 6: production)")
    for m in MERGE.finditer(cmd):
        out.append(f"merges pull request {m.group(1) or m.group(2)} (rule 6: production)")
    if PUSH_MAIN.search(cmd):
        out.append("pushes to main (rule 6: production)")
    return out


def reasons(payload: dict) -> list[str]:
    """Why the action in `payload` needs the operator's yes; empty when it does not."""
    if payload.get("tool_name") in BASH_TOOLS:
        return _shell_reasons(str((payload.get("tool_input") or {}).get("command") or ""))
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
