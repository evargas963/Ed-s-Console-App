"""OPERATOR YES GUARD: the actions an agent takes only with the operator's yes (CLAUDE.md rule 6).
PreToolUse for shell commands.

  * Starting, stopping or restarting the capture daemon or the console, merging a pull request
    and pushing to main change production.

For each of these the hook answers "ask": Claude Code shows the operator the action with Allow
and Deny, and the agent cannot answer for them. Everything else passes untouched.

Limits: shell commands are judged on the program each statement runs, never on names it only
mentions (a read, a diff or a search naming a launcher passes); code inside `python -c` or a
heredoc body is data to the shell parser and is not judged here.
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
from tools.shell_parse import program_name, segment_head, shell_executed_part  # noqa: E402

#: the production processes and what starts them
PROCESS_NAMES = ("streaming.capture", "uvicorn", "server:app")
LAUNCHERS = ("start_capture_daemon", "start_ed_console")
#: programs that start the program they are given, and shells that run the command they are given
STARTERS = ("start", "start-process", "saps")
SHELLS = ("cmd", "powershell", "pwsh", "bash", "sh", "call")
#: programs that stop a process: they stop the daemon or console when the command names it
STOPPERS = ("stop-process", "spps", "taskkill", "kill")
MERGE = re.compile(r"\bgh\s+pr\s+merge\s+(\d+)|/pulls/(\d+)/merge\b", re.I)
PUSH_MAIN = re.compile(r"\bgit\b[^\n;&|]*\bpush\b[^\n;&|]*?(?:\s|:)main\b", re.I)
#: a quoted string (a backslash escapes inside double quotes), a word, or a statement separator
_TOKEN = re.compile(r"\"(?:\\.|[^\"\\])*\"|'[^']*'|&&|\|\||[;&|]|[^\s;&|]+")
#: a PowerShell here-string, data like a heredoc body
_HERE_STRING = re.compile(r"@(['\"])\r?\n.*?\r?\n\1@", re.S)


def _statements(cmd: str) -> "list[list[str]]":
    """Each statement the shell runs in `cmd`, as (program, args) tokens: split at ; & | && || and
    line ends outside quotes, leading VAR=val and wrappers skipped (segment_head)."""
    out = []
    for line in shell_executed_part(_HERE_STRING.sub(" HERESTRING ", cmd)).splitlines():
        stmt: "list[str]" = []
        for tok in [*_TOKEN.findall(line), ";"]:
            if tok in (";", "&", "|", "&&", "||"):
                _name, toks = segment_head(" ".join(stmt))
                out += [toks] if toks else []
                stmt = []
            else:
                stmt.append(tok)
    return out


def _starts(toks: "list[str]") -> bool:
    """Whether the statement `toks` (its program first) runs a launcher, launch.py, the console's
    uvicorn or the capture daemon. A quoted phrase in the program's place is a string the shell
    prints, not a program."""
    if toks[0][:1] in "\"'" and " " in toks[0] and not toks[0].strip("\"'").lower().endswith((".bat", ".cmd", ".exe")):
        return False
    name = program_name(toks[0]).removesuffix(".bat").removesuffix(".cmd")
    args = [t.strip("\"'") for t in toks[1:]]
    if name in LAUNCHERS or name == "uvicorn":
        return True
    if name.startswith("python"):
        return bool(args) and (program_name(args[0]) == "launch.py"
                               or (args[0] == "-m" and len(args) > 1 and any(n in args[1] for n in PROCESS_NAMES)))
    if name in SHELLS:
        return any(_starts(s) for s in _statements(" ".join(a for a in args if not a.startswith(("-", "/")))))
    if name in STARTERS:
        return any(n in " ".join(args).lower() for n in (*LAUNCHERS, *PROCESS_NAMES, "launch.py"))
    return False


def _shell_reasons(cmd: str) -> list[str]:
    out = []
    statements = _statements(cmd)
    stops = any(program_name(s[0]) in STOPPERS for s in statements) and any(
        n in cmd.lower() for n in (*PROCESS_NAMES, *LAUNCHERS))
    if stops or any(_starts(s) for s in statements):
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
