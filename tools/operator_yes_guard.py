"""OPERATOR YES GUARD: production actions and the operator's yes (CLAUDE.md rule 5). PreToolUse for
shell commands. Each command gets one answer, the strictest of its statements':

  * A start or a clean stop of the capture daemon or the console (a launcher, launch.py, its
    `stop`, uvicorn, the daemon's module) is put to the operator (Claude Code's Allow/Deny) during
    regular market hours (RTH) and while the session is unknown; in Pre-Market, After-Hours and
    Closed it passes. The session is time_et.session_label on Schwab's /markets answer for
    the day, as the daemon recorded it (stream_markets_raw); no answer held is unknown.
  * Killing the daemon, the console or launch.py from outside is refused: on Windows every such
    stop (Stop-Process with or without -Force, taskkill /F, kill, .Kill(), WMI/CIM) ends the
    process without its shutdown, so what the daemon holds in memory is lost. The clean stop is
    `python launch.py stop`. A stop by process id or image name is judged by what each target
    process runs (its command line) and where (the production checkout): a stop of nothing in
    production passes; a target whose
    command line cannot be read is put to the operator. A stop whose targets are chosen only when
    it runs (a variable, a pipe) is refused when the command names the daemon or the console, and
    put to the operator while either runs.
  * A stop or restart of the machine and a merge are put to the operator; a push to main and
    `gh alias set` (an alias could name a merge in other words) are refused. A merge (`_merges`) is `gh pr merge` with options anywhere, or a REST merge or a
    GraphQL mergePullRequest sent by `gh api`, curl, wget or Invoke-RestMethod/WebRequest, in any
    statement the command runs; a GraphQL request whose body is read from a file asks too. A merge
    clicked in a browser or run from a script file is not a shell command this guard sees
    (GITHUB-LOCK in ACTIVE_PROGRAM.md).

Limits: shell commands are judged on the statements they run, as tools/shell_parse.read reads them
(behind a keyword, a wrapper or a subshell, inside a shell's command string), never on names
they only mention (a read, a diff or a search naming a launcher passes); code inside `python -c`
or a heredoc a python reads is not judged here.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path

import psutil

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import runtime_layout  # noqa: E402
import time_et  # noqa: E402
from db_authority import canonical_stream_db_path  # noqa: E402
from tools.hook_chain import BASH_TOOLS  # noqa: E402
from tools.shell_parse import Statement, git_subcommand, program_name, read  # noqa: E402

PASS, ASK, DENY = "pass", "ask", "deny"
#: the production processes and what starts them
PROCESS_NAMES = ("streaming.capture", "uvicorn", "server:app")
LAUNCHERS = ("start_capture_daemon", "start_ed_console")
#: a command line that carries one of these is production's (launch.py among them)
PRODUCTION_MARKS = (*PROCESS_NAMES, *LAUNCHERS, "launch.py")
#: programs that start or open what they are given (wmic and the CIM/WMI methods with Create), and
#: shells that run the script file given as their first argument
STARTERS = ("start", "start-process", "saps", "invoke-item", "ii", "explorer", "wmic", "invoke-cimmethod",
            "invoke-wmimethod")
SHELLS = ("powershell", "pwsh", "bash", "sh")
#: programs that end a process from outside
STOPPERS = ("stop-process", "spps", "taskkill", "kill", "tskill", "pskill")
#: programs that stop or restart the machine
MACHINE_STOPPERS = ("stop-computer", "restart-computer", "shutdown")
#: process objects removed through WMI/CIM
WMI_STOPS = ("remove-ciminstance", "remove-wmiobject")
#: a merge through GitHub's API
API_MERGE = re.compile(r"/pulls/([^/\s'\"]+)/merge\b", re.I)
#: programs that send an HTTP request
HTTP_CLIENTS = ("curl", "wget", "invoke-restmethod", "irm", "invoke-webrequest", "iwr")
#: gh options that take a value (the value is not a subcommand)
GH_VALUE_OPTIONS = ("-R", "--repo", "--hostname", "-X", "--method", "-f", "-F", "--field", "--raw-field",
                    "-H", "--header", "--input", "-q", "--jq", "-t", "--template")
#: process ids and image names a stop names (Stop-Process -Id, taskkill /PID, ProcessId=N;
#: -Name, /IM, Get-Process <name>, Name='x.exe')
_PIDS = re.compile(r"(?:-id|/pid|processid\s*=)\s*['\"]?(\d[\d,\s]*)", re.I)
_NAMES = re.compile(r"(?:-name|-processname|/im|get-process)\s+['\"]?([\w.*]+)|\bname\s*(?:=|like)\s*['\"]([\w.*%]+)",
                    re.I)


def market_session(now: datetime, db: Path) -> str:
    """time_et.session_label at `now` from Schwab's newest 200 answer to /markets for that ET date
    in the stream database `db` (stream_markets_raw, as the daemon recorded it); UNKNOWN when
    none is held or the database cannot be read."""
    day = now.astimezone(time_et.ET).date().isoformat()
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2) as conn:
            row = conn.execute("SELECT native_json FROM stream_markets_raw WHERE date = ? AND status = 200 "
                               "ORDER BY ts_recv DESC LIMIT 1", (day,)).fetchone()
    except sqlite3.Error as e:
        sys.stderr.write(f"operator_yes_guard: the market session is unknown: {type(e).__name__}: {e}\n")
        return time_et.UNKNOWN
    if row is None:
        return time_et.UNKNOWN
    time_et.record_markets(json.loads(row[0]))
    return time_et.session_label(now)


def _launcher(word: str) -> str:
    return program_name(word).removesuffix(".bat").removesuffix(".cmd")


def _printed(st: Statement) -> bool:
    """Whether a PowerShell statement's program word is a quoted phrase or a here-string: a string
    PowerShell prints, not a program (bash runs a quoted program path)."""
    raw0 = st.raw[0]
    return st.powershell and (raw0[:2] in ("@'", '@"') or (raw0[:1] in "\"'" and " " in raw0
                                                and not st.words[0].lower().endswith((".bat", ".cmd", ".exe"))))


def _starts(st: Statement) -> bool:
    """Whether the statement `st` runs a launcher, launch.py (a start or its clean `stop`), the
    console's uvicorn or the capture daemon."""
    name = _launcher(st.words[0])
    args = list(st.words[1:])
    named = any(n in st.text.lower() for n in PRODUCTION_MARKS)
    if name in LAUNCHERS or name == "uvicorn":
        return True
    if name == "py" or name.startswith("python"):
        return bool(args) and (program_name(args[0]) == "launch.py"
                               or (args[0] == "-m" and len(args) > 1 and any(n in args[1] for n in PROCESS_NAMES)))
    if name in SHELLS:
        script = next((a for a in args if not a.startswith(("-", "/"))), "")
        return _launcher(script) in LAUNCHERS
    if name == "schtasks":
        return "/run" in (a.lower() for a in args)
    # a starter, or .NET's Process.Start, given a launcher, launch.py or a production process
    return named and (name in STARTERS or "::start(" in st.words[0].lower())


def _kills(st: Statement) -> bool:
    """Whether the statement `st` ends a process from outside: a stopper, a .Kill() call, wmic's
    delete or terminate, CIM/WMI's Terminate, a removed process object."""
    name = st.program
    args = [a.lower() for a in st.words[1:]]
    if name in STOPPERS or any(".kill(" in r.lower() and not r.startswith(("'", '"', "@'", '@"'))
                               for r in st.raw):                     # a quoted string or here-string is text
        return True
    if name == "wmic":
        return "process" in args and any(a in ("delete", "terminate") for a in args)
    if name in ("invoke-cimmethod", "invoke-wmimethod"):
        return "terminate" in args
    return name in WMI_STOPS and (st.upstream is not None or "win32_process" in " ".join(args))


#: the listings whose output, piped straight into a kill, are its targets
LISTINGS = ("get-process", "gps", "ps", "get-ciminstance", "gcim", "get-wmiobject", "gwmi")


def _targets(st: Statement, upstream: "list[str] | None") -> "tuple[list[psutil.Process], bool]":
    """The running processes a kill statement `st` reaches by the ids and image names it names
    (a stopper's bare ids and names among them), or that the listing piped straight into it
    names (`upstream`, its words as written: Get-Process, Get-CimInstance ...); and whether it
    also reaches processes chosen only when it runs: a target held in a variable ($ids,
    $_.ProcessId), a pipe from anything but a listing (a filter), or none named at all."""
    text = st.text
    later = (any(t.startswith("$") for t in st.words[1:] if upstream is None)
             or (upstream is not None and program_name(upstream[0]) not in LISTINGS))
    if upstream is not None and not later:
        text += " " + " ".join(upstream)
    pids = {int(p) for m in _PIDS.finditer(text) for p in re.split(r"[,\s]+", m.group(1)) if p}
    names = {(a or b).lower().removesuffix(".exe").replace("%", "*") for a, b in _NAMES.findall(text)}
    if st.program in STOPPERS:
        for arg in (t for t in st.words[1:] if not t.startswith(("-", "/", "$", "(", "@("))):
            for part in arg.split(","):
                pids.update([int(part)] if part.isdigit() else [])
                names.update([part.lower().removesuffix(".exe")] if part and not part.isdigit() else [])
    found = [psutil.Process(pid) for pid in pids if psutil.pid_exists(pid)]
    for p in psutil.process_iter(["name"]):
        image = (p.info["name"] or "").lower().removesuffix(".exe")
        if any(fnmatch(image, n) or (n.startswith("python") and image.startswith(n)) for n in names):
            found.append(p)
    return found, later or not (pids or names)


def _production_running() -> bool:
    """Whether the daemon, the console or launch.py runs on this machine now."""
    return any(_production(p) is not False for p in psutil.process_iter(["name"])
               if (p.info["name"] or "").lower().startswith("python"))


def _production(proc: psutil.Process) -> "bool | None":
    """Whether `proc` is the daemon, the console or launch.py: its command line carries one of
    their marks and it runs in the production checkout (runtime_layout.RUNTIME_ROOT, which every
    worktree resolves to; a worktree's test console is not production). None when either cannot
    be read."""
    try:
        line, cwd = " ".join(proc.cmdline()).lower(), Path(proc.cwd()).resolve()
    except psutil.NoSuchProcess:
        return False
    except psutil.AccessDenied:
        return None
    return any(m in line for m in PRODUCTION_MARKS) and cwd == runtime_layout.RUNTIME_ROOT.resolve()


def decide(payload: dict, now: datetime, db: Path) -> "tuple[str, list[str]]":
    """The answer to the action in `payload` at `now` (PASS, ASK or DENY), with its reasons; the
    market session is read from the stream database `db` (market_session)."""
    if payload.get("tool_name") not in BASH_TOOLS:
        return PASS, []
    cmd = str((payload.get("tool_input") or {}).get("command") or "")
    asks, denies = [], []
    statements = [st for st in read(cmd, powershell=payload.get("tool_name") == "PowerShell")
                  if st.words and not _printed(st)]
    # `$x = <listing>` with nothing piped after it: a kill naming $x reaches what the listing names
    listed = {st.env[-1][:-1].lower(): list(st.raw) for st in statements
              if st.env and st.env[-1].startswith("$") and st.env[-1].endswith("=")
              and not any(s.upstream is st for s in statements)}
    for st in statements:
        if st.program in MACHINE_STOPPERS:
            asks.append("stops or restarts the machine, and the daemon and console with it (CLAUDE.md rule 5: production)")
        elif _kills(st):
            upstream = list(st.upstream.raw) if st.upstream is not None and st.upstream.raw else next(
                (listed[v] for t in st.words[1:] for v in [t.lower().split(".")[0]] if v in listed), None)
            found, later = _targets(st, upstream)
            seen = [_production(p) for p in found]
            if any(seen) or (later and any(m in cmd.lower() for m in PRODUCTION_MARKS)):
                denies.append("kills the daemon, the console or launch.py: on Windows that skips its shutdown "
                              "and loses what the daemon holds; stop them with `python launch.py stop`")
            elif None in seen:
                asks.append("stops a process whose command line cannot be read (CLAUDE.md rule 5: production)")
            elif later and _production_running():
                asks.append("stops processes chosen only when it runs while the daemon or the console runs "
                            "(CLAUDE.md rule 5: production)")
        elif _starts(st):
            session = market_session(now, db)
            if session in (time_et.RTH, time_et.UNKNOWN):
                asks.append(f"starts or stops the daemon or the console while the market session is "
                            f"{session} (CLAUDE.md rule 5: production)")
        elif pr := _merges(st):
            asks.append(f"merges pull request {pr} (AGENTS.md Authority)")
        elif _pushes_main(st):
            denies.append("pushes to main: main moves only by a pull request merged on GitHub")
        elif st.program == "gh" and _gh_words(st)[:2] == ["alias", "set"]:
            denies.append("sets a gh alias: an alias can name a merge in words the merge check does not know")
    return (DENY, denies) if denies else (ASK, asks) if asks else (PASS, [])


def _gh_words(st: Statement) -> "list[str]":
    """A gh statement's subcommand words: its arguments without options and their values."""
    args = list(st.words[1:])
    return [a for i, a in enumerate(args) if not a.startswith("-") and not (i and args[i - 1] in GH_VALUE_OPTIONS)]


def _merges(st: Statement) -> str:
    """The pull request the statement `st` merges: `gh pr merge` with options anywhere, or a REST
    merge or GraphQL mergePullRequest sent by `gh api` or an HTTP client; "" if none."""
    name, args = st.program, list(st.words[1:])
    if name == "gh":
        words = _gh_words(st)
        if words[:2] == ["pr", "merge"]:
            return next((a for a in words[2:] if a.isdigit()), "the current branch's")
        if words[:1] != ["api"]:
            return ""
    elif name not in HTTP_CLIENTS:
        return ""
    if any("mergepullrequest" in a.lower() for a in args):
        return "a GraphQL mergePullRequest"
    if any("graphql" in a.lower() for a in args) and any(a.startswith("@") or "=@" in a or a == "--input" for a in args):
        return "a GraphQL request whose body is read from a file"            # its query is unseen
    return next((m.group(1) for a in args for m in [API_MERGE.search(a)] if m), "")


def _pushes_main(st: Statement) -> bool:
    """Whether the statement `st` is a git push whose refspec lands on main."""
    sub, args = git_subcommand(st.words)
    return (sub == "push"
            and any(a == "main" or a.endswith((":main", ":refs/heads/main")) or a == "+main" for a in args))


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
