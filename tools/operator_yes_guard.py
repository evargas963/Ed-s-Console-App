"""OPERATOR YES GUARD: the actions an agent takes only with the operator's yes (CLAUDE.md rule 6).
PreToolUse for shell commands, judged on the program each statement runs, never on names a
command only mentions (a read, a diff or a search naming a launcher passes):

  * A start, stop or restart of the capture daemon or the console asks (Claude Code's Allow/Deny)
    during regular market hours and while the session is unknown, and passes otherwise. The
    session is time_et.session_label on Schwab's /markets answer for the day, as the daemon
    recorded it (stream_markets_raw).
  * A merge and a restart or shutdown of the machine ask; a push to main is refused.

Limits: code inside `python -c`, a heredoc body or a here-string is data, not judged here.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import time_et  # noqa: E402
from db_authority import canonical_stream_db_path  # noqa: E402
from tools.hook_chain import BASH_TOOLS  # noqa: E402
from tools.shell_parse import program_name, segment_head, shell_executed_part  # noqa: E402

PASS, ASK, DENY = "pass", "ask", "deny"
#: what a production process's command carries, and what starts one
MARKS = ("streaming.capture", "uvicorn", "server:app", "start_capture_daemon", "start_ed_console", "launch.py")
STARTERS = ("start", "start-process", "saps", "invoke-item", "ii", "explorer")     # start what they are given
SHELLS = ("cmd", "powershell", "pwsh", "bash", "sh", "call", "invoke-expression", "iex")   # run a command
STOPPERS = ("stop-process", "spps", "taskkill", "kill")
MACHINE = ("stop-computer", "restart-computer", "shutdown")
API_MERGE = re.compile(r"/pulls/(\d+)/merge\b", re.I)
#: a quoted string (a backslash escapes inside double quotes), a word, or a statement separator
_TOKEN = re.compile(r"\"(?:\\.|[^\"\\])*\"|'[^']*'|&&|\|\||[;&|{}]|[^\s;&|{}]+")
_HERE_STRING = re.compile(r"@(['\"])\r?\n.*?\r?\n\1@", re.S)


def market_session(now: datetime, db: Path) -> str:
    """time_et.session_label at `now` from Schwab's newest 200 answer to /markets for that ET date
    in the stream database `db`; UNKNOWN when none is held or the database cannot be read."""
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2) as conn:
            row = conn.execute("SELECT native_json FROM stream_markets_raw WHERE date = ? AND status = 200 "
                               "ORDER BY ts_recv DESC LIMIT 1", (now.astimezone(time_et.ET).date().isoformat(),)).fetchone()
    except sqlite3.Error as e:
        sys.stderr.write(f"operator_yes_guard: the market session is unknown: {e}\n")
        return time_et.UNKNOWN
    if row is None:
        return time_et.UNKNOWN
    time_et.record_markets(json.loads(row[0]))
    return time_et.session_label(now)


def _statements(cmd: str) -> "list[list[str]]":
    """Each statement the shell runs in `cmd` as (program, args) tokens, split at ; & | && || { }
    outside quotes and at line ends, leading VAR=val and wrappers skipped (segment_head)."""
    out = []
    for line in shell_executed_part(_HERE_STRING.sub(" HERESTRING ", cmd)).splitlines():
        stmt: "list[str]" = []
        for tok in [*_TOKEN.findall(line), ";"]:
            if tok in (";", "&", "|", "&&", "||", "{", "}"):
                out += [segment_head(" ".join(stmt))[1]] if stmt else []
                stmt = []
            elif stmt or tok not in ("do", "then", "else"):        # a shell keyword is not a program
                stmt.append(tok)
    return [s for s in out if s]


def _starts(toks: "list[str]") -> bool:
    """Whether the statement runs a launcher, launch.py, uvicorn or the daemon's module, directly,
    through a shell or through a starter. A quoted phrase in the program's place is printed text."""
    if toks[0][:1] in "\"'" and " " in toks[0] and not toks[0].strip("\"'").lower().endswith((".bat", ".exe")):
        return False
    name = program_name(toks[0]).removesuffix(".bat").removesuffix(".cmd")
    args = [t.strip("\"'") for t in toks[1:]]
    if name in ("start_capture_daemon", "start_ed_console", "uvicorn"):
        return True
    if name == "py" or name.startswith("python"):
        return bool(args) and (program_name(args[0]) == "launch.py"
                               or (args[0] == "-m" and len(args) > 1 and any(m in args[1] for m in MARKS)))
    if name in SHELLS:
        return any(_starts(s) for s in _statements(" ".join(a for a in args if not a.startswith(("-", "/")))))
    return name in STARTERS and any(m in " ".join(args).lower() for m in MARKS)


def decide(payload: dict, now: datetime, db: Path) -> "tuple[str, list[str]]":
    """The answer (PASS, ASK or DENY) to the action in `payload` at `now`, with its reasons."""
    if payload.get("tool_name") not in BASH_TOOLS:
        return PASS, []
    cmd = str((payload.get("tool_input") or {}).get("command") or "")
    asks, denies = [], []
    for toks in _statements(cmd):
        name, args = program_name(toks[0]), [t.strip("\"'") for t in toks[1:]]
        if _starts(toks) or (name in STOPPERS and any(m in cmd.lower() for m in MARKS)):
            session = market_session(now, db)
            if session in (time_et.RTH, time_et.UNKNOWN):
                asks.append(f"starts or stops the daemon or the console in session {session} (rule 6: production)")
        elif name in MACHINE:
            asks.append("restarts or shuts down the machine (rule 6: production)")
        elif name == "gh" and (args[:2] == ["pr", "merge"] or any(API_MERGE.search(a) for a in args)):
            asks.append("merges a pull request (rule 6: production)")
        elif name == "git" and "push" in args and any(a == "main" or a.endswith(":main") for a in args):
            denies.append("pushes to main: main moves only by a pull request merged on GitHub")
    return (DENY, denies) if denies else (ASK, asks) if asks else (PASS, [])


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.stderr.write("BLOCKED: invalid hook payload.\n")
        return 2
    if not isinstance(payload, dict):
        sys.stderr.write("BLOCKED: the hook payload is not an object.\n")
        return 2
    answer, why = decide(payload, datetime.now(timezone.utc), canonical_stream_db_path())
    if answer == DENY:
        sys.stderr.write("BLOCKED (operator_yes_guard): " + "; ".join(why) + "\n")
        return 2
    if answer == ASK:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": "Needs the operator's yes: " + "; ".join(why)}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
