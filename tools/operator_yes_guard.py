"""OPERATOR YES GUARD: the actions an agent takes only with the operator's yes (CLAUDE.md rule 6).
PreToolUse for shell commands.

  * Starting, stopping or restarting the capture daemon or the console, merging a pull request
    and pushing to main change production. Both processes run as python/pythonw, so a stop by
    process id, of a python image, of a pipe's processes, or of the machine is put to the operator.

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
#: programs that start or open what they are given (wmic and the CIM/WMI methods with Create), and
#: shells that run the command they are given
STARTERS = ("start", "start-process", "saps", "invoke-item", "ii", "explorer", "wmic", "invoke-cimmethod",
            "invoke-wmimethod")
SHELLS = ("cmd", "powershell", "pwsh", "bash", "sh", "call", "invoke-expression", "iex")
#: programs that stop a process; the daemon and the console both run as python/pythonw, so a stop
#: by process id, of a python image, or of whatever a pipe hands it, may stop either
STOPPERS = ("stop-process", "spps", "taskkill", "kill", "tskill", "pskill")
#: programs that stop every process (the machine)
MACHINE_STOPPERS = ("stop-computer", "restart-computer", "shutdown")
#: process objects removed or terminated through WMI/CIM
WMI_STOPS = ("remove-ciminstance", "remove-wmiobject")
MERGE = re.compile(r"\bgh\s+pr\s+merge\s+(\d+)|/pulls/(\d+)/merge\b", re.I)
PUSH_MAIN = re.compile(r"\bgit\b[^\n;&|]*\bpush\b[^\n;&|]*?(?:\s|:)main\b", re.I)
#: a quoted string (a backslash escapes inside double quotes), a word, or a statement separator
_TOKEN = re.compile(r"\"(?:\\.|[^\"\\])*\"|'[^']*'|&&|\|\||[;&|]|[^\s;&|]+")
#: a PowerShell here-string, data like a heredoc body
_HERE_STRING = re.compile(r"@(['\"])\r?\n.*?\r?\n\1@", re.S)


def _statements(cmd: str) -> "list[tuple[list[str], bool]]":
    """Each statement the shell runs in `cmd`: its (program, args) tokens and whether a pipe hands
    it its input. Split at ; & | && || and line ends outside quotes, leading VAR=val and wrappers
    skipped (segment_head)."""
    out = []
    for line in shell_executed_part(_HERE_STRING.sub(" HERESTRING ", cmd)).splitlines():
        stmt: "list[str]" = []
        piped = False
        for tok in [*_TOKEN.findall(line), ";"]:
            if tok in (";", "&", "|", "&&", "||"):
                _name, toks = segment_head(" ".join(stmt))
                out += [(toks, piped)] if toks else []
                stmt, piped = [], tok == "|"
            else:
                stmt.append(tok)
    return out


def _stops(toks: "list[str]", piped: bool, cmd: str) -> bool:
    """Whether the statement `toks` may stop the daemon or the console: a stopper given a process
    id, a python image, a pipe's processes or the daemon's or console's name; a stop of the
    machine; a process killed through its .Kill() method, WMI or CIM."""
    name = program_name(toks[0])
    args = [t.strip("\"'").lower() for t in toks[1:]]
    text = " ".join(toks).lower()
    if name in MACHINE_STOPPERS or ".kill(" in text:
        return True
    if name in STOPPERS:
        return (piped or any(a.isdigit() or a in ("-id", "/pid") for a in args)
                or any(program_name(a).startswith("python") for a in args)
                or any(n in cmd.lower() for n in (*PROCESS_NAMES, *LAUNCHERS)))
    if name == "wmic":
        return "process" in args and any(a in ("delete", "terminate") for a in args)
    if name in ("invoke-cimmethod", "invoke-wmimethod"):
        return "terminate" in args
    if name in WMI_STOPS:
        return piped or "win32_process" in text
    return False


def _starts(toks: "list[str]") -> bool:
    """Whether the statement `toks` (its program first) runs a launcher, launch.py, the console's
    uvicorn or the capture daemon. A quoted phrase in the program's place is a string the shell
    prints, not a program."""
    if toks[0][:1] in "\"'" and " " in toks[0] and not toks[0].strip("\"'").lower().endswith((".bat", ".cmd", ".exe")):
        return False
    name = program_name(toks[0]).removesuffix(".bat").removesuffix(".cmd")
    args = [t.strip("\"'") for t in toks[1:]]
    named = any(n in " ".join(toks).lower() for n in (*LAUNCHERS, *PROCESS_NAMES, "launch.py"))
    if name in LAUNCHERS or name == "uvicorn":
        return True
    if name == "py" or name.startswith("python"):
        return bool(args) and (program_name(args[0]) == "launch.py"
                               or (args[0] == "-m" and len(args) > 1 and any(n in args[1] for n in PROCESS_NAMES)))
    if name in SHELLS:
        return any(_starts(s) for s, _piped in _statements(" ".join(a for a in args if not a.startswith(("-", "/")))))
    if name == "schtasks":
        return "/run" in (a.lower() for a in args)
    # a starter, or .NET's Process.Start, given a launcher, launch.py or a production process
    return named and (name in STARTERS or "::start(" in toks[0].lower())


def _shell_reasons(cmd: str) -> list[str]:
    out = []
    statements = _statements(cmd)
    if any(_stops(s, piped, cmd) or _starts(s) for s, piped in statements):
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
