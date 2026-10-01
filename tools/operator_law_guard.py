"""Four host-wide action bans on shell commands, judged on the action a command runs, never on a
word in other text. PreToolUse for the shell-command tools (`hook_chain.BASH_TOOLS`); exit 2
blocks. The rules live in `AGENTS.md` § Authority.

  * Deleting, moving, overwriting or unprotecting anything under data/ or backups/ (gitignored:
    no history, no undo). A copy into those trees (a restore) is allowed.
  * Blind staging: `git add -A` / `--all` / `-u` / `.` / `*`.
  * Disabling the commit hooks: `--no-verify`, `-n` on commit, `core.hooksPath`, `SKIP=<hook>`,
    `pre-commit uninstall`, removing `.git/hooks`.
  * A push to main: main changes only through a PR.
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
        if head in _SHELL_REMOVERS and any(_protected(a) for a in args if not a.startswith("-")):
            return True
        if head in ("icacls", "icacls.exe") and any(_protected(a) for a in args) and \
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
    r"\bgit\b[^\n;&|]*\b(?:commit|push|merge|rebase|am|cherry-pick|revert)\b[^\n;&|]*\s--no-verify\b"
    r"|\bgit\b[^\n;&|]*\bconfig\b(?![^\n;&|]*\s--(?:get|get-all|list|show-origin)\b)[^\n;&|]*\bcore\.hooksPath\b"
    r"|\bgit\s+-c\s+core\.hooksPath\s*="
    r"|\bgit\s+commit\b[^\n]*?(?:\s-n\b)"
    r"|(?:^|[\s;&|(])(?:\$env:)?SKIP\s*=\s*['\"]?[A-Za-z0-9_,\-]"
    r"|\bpre[-_]commit\s+uninstall\b"
    r"|\b(?:rm|del|erase|rmdir|rd|remove-item|ri|mv|move|move-item)\b[^\n;&|]*\.git[\\/]hooks\b",
    re.I)

#: A push to main.
_PUSH_TO_MAIN = re.compile(
    r"\bgit\b[^\n;&|]*\bpush\b[^\n;&|]*(?:\s|:|refs/heads/)(?:main|master)(?=\s|$|[;&|])",
    re.I)


def bash_violations(cmd: str) -> list[str]:
    """Every host-wide ban that fires on `cmd`. Applicability is per rule, never an early
    return: a foreign-repository target exempts nothing host-wide. No rule reads a repository."""
    raw = cmd or ""
    cmd = shell_executed_part(raw)
    out: list[str] = []
    if _BLIND_STAGE.search(cmd):
        out.append("ACTION BLOCKED: blind staging (git add -A/--all/-u/.). Stage named paths "
                   "(AGENTS.md § Authority).")
    if _protected_path_violation(raw):
        out.append("ACTION BLOCKED: this deletes, moves or truncates something under data/ or "
                   "backups/, which have no history and no undo. Test against a copy in a temp "
                   "directory; a restore into these trees is allowed (AGENTS.md § Authority).")
    if _SKIP_HOOKS.search(cmd):
        out.append("ACTION BLOCKED: this disables a mechanical lock, the commit hooks "
                   "(AGENTS.md § Authority).")
    if _PUSH_TO_MAIN.search(cmd):
        out.append("ACTION BLOCKED: main changes only through a PR (AGENTS.md § Authority). "
                   "Push a branch and open one.")
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
    bad = bash_violations(cmd)
    if bad:
        sys.stderr.write("BLOCKED:\n\n"
                         + "\n".join(f"    {b}" for b in bad) + "\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
