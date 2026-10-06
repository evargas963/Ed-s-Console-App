"""OPERATOR YES GUARD: the actions an agent takes only with the operator's yes (CLAUDE.md rule 6).
PreToolUse for file edits and shell commands.

  * Merging a pull request: `gh pr merge` in any form (any options, a number, a URL, a branch or
    nothing; `-R`; gh by path or `.exe`), and the merge API (`/pulls/N/merge`, `mergePullRequest`).
  * Pushing to main: any refspec whose destination is main (`main`, `+main`, `HEAD:main`,
    `HEAD:refs/heads/main`), `--all`/`--mirror`, and a push of the current branch (no refspec,
    or `HEAD`) while that branch is main or cannot be read.
  * Starting, stopping or restarting the capture daemon or the console: a launcher
    (start_capture_daemon, start_ed_console), a run of their module (`-m uvicorn`,
    `-m streaming.capture`, `uvicorn ...`), or a start/stop verb (Stop-Process, taskkill, kill,
    Start-Process, restart, ...) in a command that names python, uvicorn, server:app or
    streaming.capture. A stop by process id alone names neither and passes (ENF-20).
  * A database under data/ (`data/*.db`, its -wal, -shm, -journal): a shell command that names
    one anywhere, its `-c` code, heredoc bodies and variables included (or names one relative to
    a `cd` into data/), asks unless every statement in it is a known read: ls, grep, cat, dir,
    Get-Item, `sqlite3 -readonly`, or a statement whose every database it names is opened
    `?mode=ro`. An Edit or Write of one asks. A command that writes one without naming it
    passes (ENF-20).

For each of these the hook answers "ask": Claude Code shows the operator the action with Allow
and Deny, and the agent cannot answer for them. Everything else passes untouched, tests included.
Merges and pushes are also read inside a shell's command string (bash -c, cmd /c,
powershell -Command, Invoke-Expression) and heredocs handed to a shell.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.hook_chain import BASH_TOOLS, MUTATING_TOOLS  # noqa: E402
from tools.shell_parse import (  # noqa: E402
    iter_command_segments, iter_git_invocations, segment_data, segment_head)

#: the production processes by name, the verbs that start or stop a process, and the runs that
#: start one with no verb
PROCESS = re.compile(r"streaming\.capture|uvicorn|server:app|\bpythonw?(?:3[\d.]*)?(?:\.exe)?\b", re.I)
PROCESS_VERB = re.compile(r"\b(?:stop-process|spps|kill|pkill|killall|taskkill|start-process|saps|restart)\b",
                          re.I)
START = re.compile(r"start_capture_daemon|start_ed_console|-m\s+(?:uvicorn|streaming\.capture)\b"
                   r"|(?:^|[\s\\/;&|\"'])uvicorn(?:\.exe)?[\"']?\s", re.I)
MERGE_API = re.compile(r"/pulls/(\d+)/merge\b|\bmergePullRequest\b", re.I)
#: a push refspec whose destination is main
MAIN_REF = re.compile(r"^\+?(?:[^:]*:)?(?:refs/heads/)?main$", re.I)
#: programs that run the command string or heredoc they are handed
SHELLS = frozenset({"bash", "sh", "zsh", "dash", "cmd", "powershell", "pwsh", "invoke-expression", "iex",
                    "eval"})
#: a database file under data/
DATA_DB = re.compile(r"(?:^|[\\/\s\"'=:])(data[\\/][^\\/\s\"'?;&|]+\.db(?:-wal|-shm|-journal)?)\b", re.I)
#: programs that only read the paths they are given
READERS = frozenset({"ls", "grep", "cat", "dir", "get-item", "gi"})
REDIRECT = re.compile(r"(?:^|[^<>&0-9])>{1,2}")


def _database(cwd: str, path: str) -> "re.Match | None":
    """The database under data/ that `path` names when a statement in `cwd` uses it."""
    return DATA_DB.search(" " + os.path.join(cwd, path.strip("\"'")))


def _unwrap(data: str) -> str:
    """The text a shell runs from one piece of statement data: a `-c` string's inside, a
    heredoc's body; a message is run by nothing."""
    if data.startswith("<<"):
        return "\n".join(data.splitlines()[1:-1])
    m = re.match(r"-c\s+(['\"])(.*)\1\Z", data, re.S)
    return m.group(2) if m else ""


def _statements(cmd: str, cwd: str):
    """(cwd, statement, program, tokens) for every statement of `cmd`, and of every command
    string or heredoc a shell in it is handed (`bash -c "..."`, `cmd /c ...`,
    `powershell -Command "..."`, `Invoke-Expression "..."`, `bash <<EOF`)."""
    for seg_cwd, seg in iter_command_segments(cmd, cwd):
        head, toks = segment_head(seg)
        head = head.removesuffix(".exe")
        yield seg_cwd, seg, head, toks
        if head not in SHELLS:
            continue
        inner = [_unwrap(d) for d in segment_data(cmd, seg)]
        inner += [t[1:-1] for t in toks[1:] if len(t) > 1 and t[0] in "\"'" and t[-1] == t[0]]
        if len(toks) > 2 and toks[1].lower() in ("/c", "/k"):
            inner.append(" ".join(toks[2:]))
        for text in filter(None, inner):
            yield from _statements(text, seg_cwd)


def _branch(repo: str) -> str:
    """The branch checked out in `repo`; "" when it cannot be read."""
    if not repo:
        return ""
    dotgit = Path(repo) / ".git"
    try:
        if dotgit.is_file():
            m = re.search(r"^gitdir:\s*(.+?)\s*$", dotgit.read_text(encoding="utf-8"), re.M)
            dotgit = Path(m.group(1)) if m else dotgit
        head = (dotgit / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return head.removeprefix("ref: refs/heads/")


def _merge(toks: list[str]) -> "str | None":
    """The pull request a `gh` statement merges ("" when gh picks it), or None when it merges none."""
    low = [t.strip("\"'").lower() for t in toks]
    hits = [i for i in range(1, len(low) - 1) if low[i] == "pr" and low[i + 1] == "merge"]
    if not hits:
        return None
    target = next((t for t in low[hits[0] + 2:] if not t.startswith("-")), "")
    m = re.search(r"(?:^|/pull/)(\d+)$", target)
    return m.group(1) if m else ""


def _pushes_main(seg: str, cwd: str, toks: list[str]) -> bool:
    low = [t.strip("\"'") for t in toks]
    i = 1
    while i < len(low) and low[i].startswith("-"):      # git's own options, -C/-c with their value
        i += 2 if low[i] in ("-C", "-c", "--git-dir", "--work-tree", "--namespace") else 1
    if i >= len(low) or low[i] != "push":
        return False
    args = low[i + 1:]
    if "--all" in args or "--mirror" in args:
        return True
    refs = [a for a in args if not a.startswith("-")][1:]
    if any(MAIN_REF.match(r) for r in refs):
        return True
    if refs and not any(r.lstrip("+") in ("HEAD", "@") for r in refs):
        return False
    repo = next((r for r, _seg in iter_git_invocations(seg, cwd)), "")
    return _branch(repo) in ("main", "")


def _names(cmd: str, seg_cwd: str, seg: str, toks: list[str]) -> list[tuple[re.Match, bool]]:
    """(database under data/, opened ?mode=ro) for each one a statement names: in its arguments
    and the code or heredoc it is handed, resolved against the directory a `cd` put in effect."""
    data = segment_data(cmd, seg)
    text = " ".join([*toks[1:], *data])
    words = toks[1:] + re.findall(r"[\w.:-]+\.db(?:-wal|-shm|-journal)?(?:\?mode=ro)?", " ".join(data))
    return ([(m, text[m.end():].startswith("?mode=ro")) for m in DATA_DB.finditer(text)]
            + [(m, "?mode=ro" in t) for t in words for m in [_database(seg_cwd, t)] if m])


def _database_reason(cmd: str, cwd: str) -> list[str]:
    """Ask when the command names a database under data/, unless every statement only reads."""
    stmts = []
    for seg_cwd, seg in iter_command_segments(cmd, cwd):
        head, toks = segment_head(seg)
        toks = toks[:next((i for i, t in enumerate(toks) if t.startswith("#")), len(toks))]
        stmts.append((seg, head.removesuffix(".exe"), toks, _names(cmd, seg_cwd, seg, toks)))
    named = DATA_DB.search(cmd) or next((m for *_x, names in stmts for m, _ro in names), None)
    if not named:
        return []
    for seg, head, toks, names in stmts:
        if head in READERS and not REDIRECT.search(seg) or (head == "sqlite3" and "-readonly" in toks):
            continue
        written = [m for m, ro in names if not ro]
        if written or not names or REDIRECT.search(seg):
            return [f"may write {(written or [named])[0].group(1)}, a database under data/ (rule 6: production)"]
    return []


def _shell_reasons(cmd: str, cwd: str) -> list[str]:
    out = _database_reason(cmd, cwd)
    if START.search(cmd) or (PROCESS.search(cmd) and PROCESS_VERB.search(cmd)):
        out.append("starts, stops or restarts the daemon or the console (rule 6: production)")
    for m in MERGE_API.finditer(cmd):
        out.append(f"merges pull request {m.group(1) or '(GraphQL mergePullRequest)'} (rule 6: production)")
    for seg_cwd, seg, head, toks in _statements(cmd, cwd):
        pr = _merge(toks) if head == "gh" else None
        if pr is not None:
            out.append(f"merges pull request {pr or '(the one gh picks)'} (rule 6: production)")
        if head == "git" and _pushes_main(seg, seg_cwd, toks):
            out.append("pushes to main (rule 6: production)")
    return out


def reasons(payload: dict) -> list[str]:
    """Why the action in `payload` needs the operator's yes; empty when it does not."""
    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input") or {}
    if tool in MUTATING_TOOLS:
        path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or tool_input.get("path") or "")
        db = DATA_DB.search(path)
        return [f"writes {db.group(1)}, a database under data/ (rule 6: production)"] if db else []
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
