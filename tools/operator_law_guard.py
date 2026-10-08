"""OPERATOR LAW GUARD — three host-wide ACTION bans on shell commands (RC-93: ban the action,
never the word). PreToolUse for the shell-command tools (`hook_chain.BASH_TOOLS`); exit 2 blocks.

What survives, and the concrete failure each prevents (KEEP/MERGE/DELETE, 2026-09-10):

  * UNRECOVERABLE-TREE DESTRUCTION (RC-273). `.gitignore` excludes data/ and backups/,
    so the 27 GB database has no history at all. The agent destroyed it TWICE in ten minutes
    (`mv` to exercise a missing-file branch, `rm -f` while testing the ACL meant to prevent the
    first). The live database files carry an OS deny-delete (file) plus deny-delete-contents
    (folder) -- measured 2026-09-26 with a canary in the real data/ folder: delete and rename
    refused. This rule stops an attempt early, with a reason, judged on what the command RUNS.
  * BLIND STAGING. `git add -A` / `-u` / `.` / `*` swept another agent's in-flight files into a
    commit twice in one day (a 530 KB runtime log; audit scratch). A commit asserts authorship of
    everything in it; stage explicit paths.
  * LOCK DISABLE. `--no-verify`, `-n`, `core.hooksPath`, `SKIP=<hook>` and `pre-commit uninstall`
    bypass the pre-commit battery the operator asked for. Required CI would still catch the
    result, but only after the commit exists; refusing the bypass in session is cheap and blocks
    nothing legitimate.

What was DELETED, and why (nothing replaced it):
  * the no-grep rule: it blocked read-only stdout filters three times in one session — governance
    obstructing inspection; the rule's stated value (read files whole) is a working style, not a
    protection.
  * heredoc / redirect / `-c` payload / PowerShell source-write bans: they existed because shell
    writes once mangled escapes; ruff and pytest at commit and in CI catch a mangled file, and the
    retired mockup-approval registry they also guarded is gone.
  * the CLOSE-a-row-needs-a-verification-this-turn rule and its transcript readers: every ledger
    row a delta closes has its cited command EXECUTED by required CI (tools/check_delta_adds_no_debt.py);
    a transcript-derived turn ledger was a second, weaker judge of the same fact — and the last
    transcript reader on the PreToolUse path (RC-544 class).
  * the `ED_*_GUARD=off` spellings in the lock-disable regex: no such switch exists (RC-450).
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.hook_chain import BASH_TOOLS  # noqa: E402 — the ONE shell-tool roster (RC-520)
from tools.shell_parse import (  # noqa: E402 — the ONE shell parser
    iter_command_segments, segment_head, shell_executed_part)

#: RC-273 — the gitignored trees with no history. A path SEGMENT: `AppData/`, `mydata/`, `_data/`
#: do not match; `data/x`, `./data/x`, `C:/repo/data/x` do.
_PROTECTED_TREE = re.compile(r"(?:^|[\\/\"'=(,\s])(?:data|backups)[\\/]", re.I)
#: The tree itself as a shell argument: `data`, `./backups`, `C:/repo/data`.
_TREE_ROOT = re.compile(r"(?:^|[\\/])(?:data|backups)[\\/]?$", re.I)
#: Shell commands that delete, move or rename their arguments.
_SHELL_REMOVERS = frozenset({"rm", "del", "erase", "rmdir", "rd", "remove-item", "ri", "unlink",
                             "mv", "move", "move-item", "mi", "ren", "rename", "rename-item",
                             "truncate"})
#: icacls flags that remove or override a file's protection (adding a deny is protection).
_ACL_LOOSENERS = ("/remove", "/reset", "/grant", "/setowner", "/inheritance")
#: Python calls that delete, move, rename or overwrite a path.
_PY_REMOVERS = frozenset({"remove", "unlink", "rmtree", "rmdir", "removedirs", "rename", "replace",
                          "move", "truncate", "write_text", "write_bytes"})
_PY_HEADS = frozenset({"python", "python3", "py"})
_SH_HEADS = frozenset({"bash", "sh", "zsh", "pwsh", "powershell"})
_HEREDOC = re.compile(r"^(?P<line>[^\n]*?)<<-?\s*(['\"]?)(?P<tag>\w+)\2(?P<rest>[^\n]*)\n"
                      r"(?P<body>.*?)^\s*(?P=tag)\s*$", re.S | re.M)
_PY_C = re.compile(r"(?:^|[\s;&|(])(?:python3?|py)(?:\.exe)?\b[^\n;&|]*?\s-c\s+"
                   r"(\"(?:\\.|[^\"])*\"|'[^']*')", re.I)
_REDIRECT = re.compile(r"(?:^|[^<>&0-9])>{1,2}\s*(\"[^\"]*\"|'[^']*'|[^\s;&|]+)")


def _protected(arg: str) -> bool:
    return bool(_PROTECTED_TREE.search(" " + arg.strip("\"'")))


def _python_violation(code: str) -> bool:
    """A call that deletes, moves or overwrites a path inside a protected tree. Code that does not
    parse cannot run, so it removes nothing."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
        strings = [c.value for c in ast.walk(n) if isinstance(c, ast.Constant) and isinstance(c.value, str)]
        if name in _PY_REMOVERS and any(_protected(s) for s in strings):
            return True
        if name == "open" and strings and _protected(strings[0]) and \
                any(s[:1] in ("w", "a") and len(s) <= 3 for s in strings[1:]):
            return True
    return False


def _shell_violation(script: str) -> bool:
    """A command that runs and deletes, moves, overwrites or unprotects a protected-tree path."""
    for _cwd, seg in iter_command_segments(script):
        head, toks = segment_head(seg)
        args = [t.strip("\"'") for t in toks[1:]]
        paths = [a for a in args if not a.startswith("-")]
        if head in _SHELL_REMOVERS and any(_protected(a) or _TREE_ROOT.search(a) for a in paths):
            return True
        if head == "find" and ("-delete" in args or "-exec" in args or "-execdir" in args) and any(
                _protected(a) or _TREE_ROOT.search(a) for a in args[:next(
                    (i for i, a in enumerate(args) if a.startswith("-")), len(args))]):
            return True
        if head == "cmd" and len(toks) > 2 and toks[1].lower() in ("/c", "/k") and \
                _shell_violation(" ".join(toks[2:]).strip("\"")):
            return True
        if head == "icacls" and any(_protected(a) for a in args) and \
                any(a.lower().startswith(_ACL_LOOSENERS) for a in args):
            return True
        if any(_protected(m.group(1)) for m in _REDIRECT.finditer(seg)):
            return True
    return False


def _protected_path_violation(raw: str) -> bool:
    """True when a command would delete, move, overwrite or unprotect a file under data/ or
    backups/ -- judged on what RUNS, never on text that only mentions those paths.

    The shell command itself is parsed (heredoc bodies and quoted -c payloads are data there). A
    heredoc body is judged by what receives it: a Python interpreter's is parsed as Python, a
    shell's as shell; text a heredoc writes into a file is content. `python -c` code is parsed as
    Python. A copy INTO a protected tree is a restore and stays legal."""
    if not raw:
        return False
    if _shell_violation(raw):
        return True
    for m in _PY_C.finditer(raw):
        if _python_violation(m.group(1)[1:-1].replace('\\"', '"')):
            return True
    for m in _HEREDOC.finditer(raw):
        heads = {segment_head(part)[0] for part in (m.group("line") + m.group("rest")).split("|")}
        if heads & _PY_HEADS and _python_violation(m.group("body")):
            return True
        if heads & _SH_HEADS and _protected_path_violation(m.group("body")):
            return True
    return False


#: Blind staging: `-A`, `--all`, `-u`, `--update`, `*`, `.` are the same action in other flags.
_BLIND_STAGE = re.compile(
    r"\bgit\s+add\s+(?:--\s+)?(?:-A\b|--all\b|-u\b|--update\b|\*|\.(?:\s|$))")

#: Lock-disable routes: git's own (`--no-verify`, `-n` on commit, `core.hooksPath`) and
#: pre-commit's own (`SKIP=<hook-id>`, `$env:SKIP=`, `pre-commit uninstall`) — RC-541.
_SKIP_HOOKS = re.compile(
    r"--no-verify"
    r"|hooksPath"
    r"|\bgit\s+commit\b[^\n]*?(?:\s-n\b)"
    r"|(?:^|[\s;&|(])(?:\$env:)?SKIP\s*=\s*['\"]?[A-Za-z0-9_,\-]"
    r"|\bpre-commit\s+uninstall\b",
    re.I)


def bash_violations(cmd: str, ledger=None, payload_cwd: str = "") -> list[str]:
    """Every host-wide ban that fires on `cmd`. Applicability is per rule, never an early
    return (RC-258: a foreign-repository target exempts nothing host-wide). `ledger` and
    `payload_cwd` are accepted for the suites' call shape; no rule reads a repository."""
    raw = cmd or ""
    cmd = shell_executed_part(raw)
    out: list[str] = []
    if _BLIND_STAGE.search(cmd):
        out.append("ACTION BLOCKED: blind staging (git add -A/--all/.) swept another agent's "
                   "in-flight files into a commit twice on 2026-07-28. Stage EXPLICIT paths — "
                   "a commit asserts authorship of everything in it.")
    if _protected_path_violation(raw):
        out.append("ACTION BLOCKED (RC-273): this deletes, moves or truncates something under "
                   "data/ or backups/. Those trees are gitignored -- there is NO "
                   "history and NO undo. The agent destroyed the 27GB database twice in ten "
                   "minutes this way, both times while 'just testing'. Test destructive "
                   "behaviour against a COPY in a temp directory, never the real artefact. "
                   "Restores INTO these trees stay legal; removal from them is operator-only.")
    if _SKIP_HOOKS.search(cmd):
        out.append("ACTION BLOCKED: this disables a mechanical lock. Only the operator may.")
    return out


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.stderr.write("BLOCKED: invalid hook payload — unmeasurable is not compliant.\n")
        return 2
    if not isinstance(payload, dict):
        sys.stderr.write("BLOCKED: the hook payload is not an object.\n")
        return 2
    if payload.get("tool_name") not in BASH_TOOLS:
        return 0                          # file edits carry no shell action to judge
    cmd = (payload.get("tool_input") or {}).get("command") or ""
    bad = bash_violations(cmd, [], str(payload.get("cwd") or ""))
    if bad:
        sys.stderr.write("BLOCKED (RC-93) — OPERATOR LAW: ban the ACTION, not the word.\n\n"
                         + "\n".join(f"    {b}" for b in bad) + "\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
