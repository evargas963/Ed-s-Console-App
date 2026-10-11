"""OPERATOR LAW GUARD — host-wide bans on what a shell command does (the action, never a word it
mentions). PreToolUse for the shell-command tools (`hook_chain.BASH_TOOLS`); exit 2 blocks. Each is
judged on the statements the command runs, as tools/shell_parse.read reads them; text in quotes and
a heredoc nothing runs are data.

  * THE DATA TREE. `.gitignore` excludes data/, so the database there has no history and no undo.
    A command that deletes, moves, overwrites or unprotects a path under it is refused, judged on
    what the command runs; a restore into it stays legal.
  * BLIND STAGING. `git add -A` / `-u` / `.` / `*` sweeps another agent's in-flight files into a
    commit; stage explicit paths.
  * LOCK DISABLE. `--no-verify`, `-n`, `core.hooksPath`, `SKIP=<hook>` and `pre-commit uninstall`
    bypass the pre-commit checks; refusing the bypass in session blocks nothing legitimate.
  * PYTHON FROM STDIN. On Windows an empty heredoc or </dev/null looks like a console to
    `python -`, and Python 3.13's REPL retries forever on the invalid handle. A python that reads
    its program from stdin (`-`, or no script, -c or -m) is refused wherever it runs; a script file
    or `python -c` does the same job.
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
from tools.shell_parse import PYTHON, Statement, git_parts, git_subcommand, parse_python, read  # noqa: E402 — the ONE shell reader

#: RC-273 — the gitignored tree with no history. A path SEGMENT: `AppData/`, `mydata/`, `_data/`
#: do not match; `data/x`, `./data/x`, `C:/repo/data/x` do.
_PROTECTED_TREE = re.compile(r"(?:^|[\\/\"'=(,\s])data[\\/]", re.I)
#: The tree itself as a shell argument: `data`, `./data`, `C:/repo/data`.
_TREE_ROOT = re.compile(r"(?:^|[\\/])data[\\/]?$", re.I)
#: Shell commands that delete, move or rename their arguments.
_SHELL_REMOVERS = frozenset({"rm", "del", "erase", "rmdir", "rd", "remove-item", "ri", "unlink",
                             "mv", "move", "move-item", "mi", "ren", "rename", "rename-item",
                             "truncate"})
#: icacls flags that remove or override a file's protection (adding a deny is protection).
_ACL_LOOSENERS = ("/remove", "/reset", "/grant", "/setowner", "/inheritance")
#: Python calls that delete, move, rename or overwrite a path.
_PY_REMOVERS = frozenset({"remove", "unlink", "rmtree", "rmdir", "removedirs", "rename", "replace",
                          "move", "truncate", "write_text", "write_bytes"})


def _protected(arg: str) -> bool:
    return bool(_PROTECTED_TREE.search(" " + arg.strip("\"'")))


def _python_violation(code: str) -> bool:
    """A call that deletes, moves or overwrites a path inside a protected tree. Code that does not
    parse cannot run, so it removes nothing."""
    tree = parse_python(code)
    if tree is None:
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


def _protected_path_violation(cmd: str) -> bool:
    """`cmd` runs a statement that deletes, moves, overwrites or unprotects a file under data/."""
    return any(_destroys_protected(st) for st in read(cmd or ""))


def _destroys_protected(st: Statement) -> bool:
    """The statement deletes, moves, overwrites or unprotects a file under data/. A python's
    `-c` code and the stdin text it reads are parsed as Python. A copy INTO a protected tree is a
    restore and stays legal."""
    name, args = st.program, list(st.words[1:])
    paths = [a for a in args if not a.startswith("-")]
    if name in _SHELL_REMOVERS and any(_protected(a) or _TREE_ROOT.search(a) for a in paths):
        return True
    if name == "find" and ("-delete" in args or "-exec" in args or "-execdir" in args) and any(
            _protected(a) or _TREE_ROOT.search(a) for a in args[:next(
                (i for i, a in enumerate(args) if a.startswith("-")), len(args))]):
        return True
    if name == "icacls" and any(_protected(a) for a in args) and \
            any(a.lower().startswith(_ACL_LOOSENERS) for a in args):
        return True
    if any(_protected(t) for t in st.writes):
        return True
    if PYTHON.fullmatch(name):
        code = [args[i + 1] for i, a in enumerate(args[:-1]) if a == "-c"]
        return any(_python_violation(c) for c in [*code, *([st.stdin] if st.stdin else [])])
    return False


#: python options that read no program (versions, help, the py launcher's listings)
_PY_INFO = frozenset({"-V", "-VV", "--version", "-h", "--help", "-0", "-0p", "--list", "--list-paths"})
#: python options whose next argument is their value, not a script
_PY_VALUE_OPTIONS = frozenset({"-W", "-X"})


def _reads_program_from_stdin(st: Statement) -> bool:
    """A python that takes its program from stdin: `-`, or no script, -c or -m."""
    if not PYTHON.fullmatch(st.program):
        return False
    args, i = st.words[1:], 0
    while i < len(args):
        a = args[i]
        if a == "-":
            return True
        if a.startswith(("-c", "-m")) or a in _PY_INFO or not a.startswith("-"):
            return False
        i += 2 if a in _PY_VALUE_OPTIONS else 1
    return True


#: Blind staging: `-A`, `--all`, `-u`, `--update`, `*`, `.` are the same action in other flags.
_BLIND = frozenset({"-A", "--all", "-u", "--update", "*", "."})


def _blind_stage(st: Statement) -> bool:
    sub, args = git_subcommand(st.words)
    args = args[1:] if args[:1] == ["--"] else args
    return sub == "add" and bool(args) and args[0] in _BLIND


def _disables_a_lock(st: Statement) -> bool:
    """Lock-disable routes: git's own (`--no-verify`, `-n` on commit, `core.hooksPath`) and
    pre-commit's own (`SKIP=<hook-id>`, `$env:SKIP=`, `pre-commit uninstall`) — RC-541."""
    git_globals, sub, args = git_parts(st.words)
    skip = next((e.split("=", 1)[1] for e in st.env if re.match(r"(?:\$env:)?skip=", e, re.I)), None)
    if skip == "" and st.words:          # `$env:SKIP = 'x'`
        skip = st.words[0]
    return ("--no-verify" in st.words
            or any("hookspath" in w.lower() for w in (*git_globals, *(args if sub == "config" else ()), *st.env))
            or (sub == "commit" and "-n" in args)
            or bool(skip and re.match(r"[\w,\-]", skip))
            or [w.lower() for w in st.words[:2]] == ["pre-commit", "uninstall"])


def bash_violations(cmd: str, ledger=None, payload_cwd: str = "", powershell: bool = False) -> list[str]:
    """Every host-wide ban that fires on `cmd` (a PowerShell command when `powershell`).
    Applicability is per rule, never an early return (RC-258: a foreign-repository target
    exempts nothing host-wide). `ledger` and `payload_cwd` are accepted for the suites' call
    shape; no rule reads a repository."""
    statements = read(cmd or "", powershell=powershell)
    out: list[str] = []
    if any(_blind_stage(st) for st in statements):
        out.append("ACTION BLOCKED: blind staging (git add -A/--all/.) sweeps another agent's "
                   "in-flight files into a commit. Stage EXPLICIT paths — a commit asserts "
                   "authorship of everything in it.")
    if any(_destroys_protected(st) for st in statements):
        out.append("ACTION BLOCKED: this deletes, moves or truncates something under data/. That "
                   "tree is gitignored -- there is NO history and NO undo. Test destructive "
                   "behaviour against a COPY in a temp directory, never the real artefact. "
                   "Restores INTO it stay legal; removal from it is operator-only.")
    if any(_disables_a_lock(st) for st in statements):
        out.append("ACTION BLOCKED: this disables a mechanical lock. Only the operator may.")
    if any(_reads_program_from_stdin(st) for st in statements):
        out.append("ACTION BLOCKED: this python reads its program from stdin (`python -`, a heredoc, "
                   "a pipe or </dev/null). On Windows an empty heredoc or </dev/null looks like a "
                   "console and Python 3.13's REPL retries forever. Put the code in a script file and "
                   "run it, or use `python -c`.")
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
    bad = bash_violations(cmd, [], str(payload.get("cwd") or ""), payload.get("tool_name") == "PowerShell")
    if bad:
        sys.stderr.write("BLOCKED (RC-93) — OPERATOR LAW: ban the ACTION, not the word.\n\n"
                         + "\n".join(f"    {b}" for b in bad) + "\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
