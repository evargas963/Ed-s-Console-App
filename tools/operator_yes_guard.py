"""OPERATOR YES GUARD: the actions an agent takes only with the operator's yes (CLAUDE.md rules
5 and 6). PreToolUse for file edits and shell commands; exit 2 blocks.

  * A test that already exists on origin/main (any file under tests/) is not edited, moved or
    deleted. New tests are free. A test that seems wrong is reported, not changed.
  * Restarting or stopping the capture daemon or the console, merging a pull request and
    pushing to main change production.

The operator says yes by adding a line, dated today (ET), to `.claude/operator_yes.txt` in the
checkout the session runs in:

    2026-10-04 test tests/test_data_path_rules_v1.py
    2026-10-04 restart
    2026-10-04 merge 445
    2026-10-04 push main

A line counts only on its date. The agent never writes or names that file: an edit of it, or a
shell command that mentions it, is refused.

Limits: shell commands are judged on what they run; code inside `python -c` or a heredoc body is
data to the shell parser and is not judged here. The Edit and Write tools are judged in full.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.hook_chain import BASH_TOOLS, MUTATING_TOOLS  # noqa: E402
from tools.shell_parse import iter_command_segments, segment_head  # noqa: E402

APPROVALS = REPO / ".claude" / "operator_yes.txt"
APPROVALS_NAME = "operator_yes"
ET = ZoneInfo("America/New_York")
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


def approvals_for(text: str, today: date) -> set[str]:
    """The operator's yeses that count today: each line `YYYY-MM-DD <action>` dated today."""
    out = set()
    for line in text.splitlines():
        stamp, _, action = line.strip().partition(" ")
        if stamp == today.isoformat() and action.strip():
            out.add(" ".join(action.split()))
    return out


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


def _locked_test(arg: str, yes: set[str]) -> str | None:
    rel = _test_path(arg)
    if rel and _on_main(rel) and f"test {rel}" not in yes:
        return rel
    return None


def _file_violations(tool_input: dict, yes: set[str], today: date) -> list[str]:
    path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or tool_input.get("path") or "")
    if APPROVALS_NAME in path.replace("\\", "/").rsplit("/", 1)[-1]:
        return ["the operator's yes file is written only by the operator"]
    rel = _locked_test(path, yes)
    return [f"{rel} exists on main: an existing test is changed only with the operator's yes "
            f"(a line `{today.isoformat()} test {rel}`); if it seems wrong, stop and say so"] if rel else []


def _shell_violations(cmd: str, cwd: str, yes: set[str], today: date) -> list[str]:
    out = []
    low = cmd.lower()
    if APPROVALS_NAME in low:
        out.append("the operator's yes file is written and read only by the operator")
    for _cwd, seg in iter_command_segments(cmd, cwd):
        head, toks = segment_head(seg)
        args = [t for t in toks[1:] if not t.startswith("-")]
        targets = []
        if head in WRITERS and not (head == "sed" and "-i" not in toks and "--in-place" not in toks):
            targets = args
        elif head == "git" and len(toks) > 1 and toks[1] in GIT_WRITERS:
            targets = args[1:]
        targets += [m.group(1) for m in REDIRECT.finditer(seg)]
        for t in targets:
            rel = _locked_test(t, yes)
            if rel:
                out.append(f"{rel} exists on main: an existing test is changed only with the "
                           f"operator's yes (a line `{today.isoformat()} test {rel}`)")
    touches_process = any(n in low for n in PROCESS_NAMES) and any(v in low for v in PROCESS_VERBS)
    if (touches_process or any(n in low for n in LAUNCHERS)) and "restart" not in yes:
        out.append("starting, stopping or restarting the daemon or the console changes production: "
                   f"the operator's yes is a line `{today.isoformat()} restart`")
    for m in MERGE.finditer(cmd):
        pr = m.group(1) or m.group(2)
        if f"merge {pr}" not in yes:
            out.append(f"merging pull request {pr} changes main: the operator's yes is a line "
                       f"`{today.isoformat()} merge {pr}`")
    if PUSH_MAIN.search(cmd) and "push main" not in yes:
        out.append(f"pushing to main changes production: the operator's yes is a line "
                   f"`{today.isoformat()} push main`")
    return out


def judge(payload: dict, today: date, approvals_text: str) -> list[str]:
    """Every action in `payload` that needs the operator's yes and does not have it today."""
    yes = approvals_for(approvals_text, today)
    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input") or {}
    if tool in MUTATING_TOOLS:
        return _file_violations(tool_input, yes, today)
    if tool in BASH_TOOLS:
        return _shell_violations(str(tool_input.get("command") or ""), str(payload.get("cwd") or ""),
                                 yes, today)
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
    text = APPROVALS.read_text(encoding="utf-8") if APPROVALS.exists() else ""
    bad = judge(payload, datetime.now(ET).date(), text)
    if bad:
        sys.stderr.write("BLOCKED: this needs the operator's yes (CLAUDE.md rules 5 and 6). Ask the "
                         "operator in chat; do not work around it.\n\n"
                         + "\n".join(f"    {b}" for b in bad) + "\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
