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
  * THE LOCKS' SETTINGS. `gh` is allowed by a list: pull requests, runs and reads. `gh api` takes
    read options only, and every word must be written out; ENF-13 lists what this does not reach.
  * PYTHON FROM STDIN. On Windows an empty heredoc or </dev/null looks like a console to
    `python -`, and Python 3.13's REPL retries forever on the invalid handle. A python that reads
    its program from stdin (`-`, or no script, -c or -m) is refused wherever it runs; a script file
    or `python -c` does the same job.
  * SED EDITS. AGENTS.md: never edit source through a script. A sed that writes a file, in place
    (`-i`, `-i.bak`, `-ni`, `--in-place`) or by redirecting its output to a file (/dev/null, NUL
    and $null are not files), is refused with what to use instead: the Edit and Write tools. A sed
    that only prints is allowed. A sed script's own `w` command is not detected.
  * A CHANGE OF FOLDER. The hooks are found relative to the session's folder, so a `cd` that moves
    it breaks every guard for the rest of the session. `cd`, `chdir`, `pushd`, `popd` and
    PowerShell's `Set-Location`, `Push-Location`, `Pop-Location` and `sl` are refused in every
    shell; a command names its folder instead (`git -C`, an absolute path, or `cwd=` in python).
  * UNSEEN COMMANDS (the guards fail closed). What the reader cannot see into is refused, with a
    message to write it plainly: a program built at run time (a `$` or substitution in a bash
    program word, PowerShell `& $x` / `. $x` / `& (...)`, a script block made from text), text piped
    into a shell, cmd or node, a PowerShell -EncodedCommand, and Invoke-Expression.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

from tools.hook_chain import BASH_TOOLS  # the ONE shell-tool roster
from tools.shell_parse import (  # the ONE shell reader
    PYTHON,
    Statement,
    git_parts,
    git_subcommand,
    parse_python,
    python_code,
    read,
    reads_stdin,
    unseen,
)

REPO = Path(__file__).resolve().parent.parent

#: The gitignored tree with no history. A path SEGMENT: `AppData/`, `mydata/`, `_data/`
#: do not match; `data/x`, `./data/x`, `C:/repo/data/x` do.
_PROTECTED_TREE = re.compile(r"(?:^|[\\/\"'=(,\s])data[\\/]", re.I)
#: The tree itself as a shell argument: `data`, `./data`, `C:/repo/data`.
_TREE_ROOT = re.compile(r"(?:^|[\\/])data[\\/]?$", re.I)
#: Shell commands that delete, move or rename their arguments.
_SHELL_REMOVERS = frozenset(
    {
        "rm",
        "del",
        "erase",
        "rmdir",
        "rd",
        "remove-item",
        "ri",
        "unlink",
        "mv",
        "move",
        "move-item",
        "mi",
        "ren",
        "rename",
        "rename-item",
        "truncate",
    }
)
#: icacls flags that remove or override a file's protection (adding a deny is protection).
_ACL_LOOSENERS = ("/remove", "/reset", "/grant", "/setowner", "/inheritance")
#: Python calls that delete, move, rename or overwrite a path.
_PY_REMOVERS = frozenset(
    {
        "remove",
        "unlink",
        "rmtree",
        "rmdir",
        "removedirs",
        "rename",
        "replace",
        "move",
        "truncate",
        "write_text",
        "write_bytes",
    }
)


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
        strings = [
            c.value for c in ast.walk(n) if isinstance(c, ast.Constant) and isinstance(c.value, str)
        ]
        if name in _PY_REMOVERS and any(_protected(s) for s in strings):
            return True
        if (
            name == "open"
            and strings
            and _protected(strings[0])
            and any(s[:1] in ("w", "a") and len(s) <= 3 for s in strings[1:])
        ):
            return True
    return False


def _destroys_protected(st: Statement) -> bool:
    """The statement deletes, moves, overwrites or unprotects a file under data/. A python's
    `-c` code and the stdin text it reads are parsed as Python. A copy INTO a protected tree is a
    restore and stays legal."""
    name, args = st.program, list(st.words[1:])
    paths = [a for a in args if not a.startswith("-")]
    if name in _SHELL_REMOVERS and any(_protected(a) or _TREE_ROOT.search(a) for a in paths):
        return True
    if (
        name == "find"
        and ("-delete" in args or "-exec" in args or "-execdir" in args)
        and any(
            _protected(a) or _TREE_ROOT.search(a)
            for a in args[: next((i for i, a in enumerate(args) if a.startswith("-")), len(args))]
        )
    ):
        return True
    if (
        name == "icacls"
        and any(_protected(a) for a in args)
        and any(a.lower().startswith(_ACL_LOOSENERS) for a in args)
    ):
        return True
    if any(_protected(t) for t in st.writes):
        return True
    if PYTHON.fullmatch(name):
        return any(_python_violation(c) for c in python_code(st))
    return False


#: Blind staging: `-A`, `--all`, `-u`, `--update`, `*`, `.` are the same action in other flags.
_BLIND = frozenset({"-A", "--all", "-u", "--update", "*", "."})


def _blind_stage(st: Statement) -> bool:
    sub, args = git_subcommand(st.words)
    args = args[1:] if args[:1] == ["--"] else args
    return sub == "add" and bool(args) and args[0] in _BLIND


def _disables_a_lock(st: Statement) -> bool:
    """Lock-disable routes: git's own (`--no-verify`, `-n` on commit, `core.hooksPath`) and
    pre-commit's own (`SKIP=<hook-id>`, `$env:SKIP=`, `pre-commit uninstall`)."""
    git_globals, sub, args = git_parts(st.words)
    skip = next(
        (e.split("=", 1)[1] for e in st.env if re.match(r"(?:\$env:)?skip=", e, re.I)), None
    )
    if skip == "" and st.words:  # `$env:SKIP = 'x'`
        skip = st.words[0]
    return (
        "--no-verify" in st.words
        or any(
            "hookspath" in w.lower()
            for w in (*git_globals, *(args if sub == "config" else ()), *st.env)
        )
        or (sub == "commit" and "-n" in args)
        or bool(skip and re.match(r"[\w,\-]", skip))
        or [w.lower() for w in st.words[:2]] == ["pre-commit", "uninstall"]
    )


def _takes_an_unsafe_fix(st: Statement) -> bool:
    """Whether a ruff run asks for an unsafe fix.

    The flag, or an inline `--config` setting that turns unsafe fixes on or marks one safe
    (`unsafe-fixes`, `extend-safe-fixes`).
    """
    if not any(Path(w).name.lower().removesuffix(".exe") == "ruff" for w in st.words):
        return False
    return any(
        w == "--unsafe-fixes"
        or w.startswith("--unsafe-fixes=")
        or (w != "--no-unsafe-fixes" and ("unsafe-fixes" in w or "safe-fixes" in w))
        for w in st.words
    )


#: all of `gh` the agent may run, group by group; `gh api` only reads (_GH_API_READS)
_GH_ALLOWED = {
    "issue": {"list", "view"},
    "pr": {
        "checks",
        "close",
        "comment",
        "create",
        "diff",
        "edit",
        "list",
        "merge",
        "ready",
        "update-branch",
        "view",
    },
    "repo": {"view"},
    "run": {"download", "list", "rerun", "view", "watch"},
    "workflow": {"list", "view"},
}
_GH_API_READS = frozenset(
    {
        "--cache",
        "--include",
        "--jq",
        "--paginate",
        "--silent",
        "--slurp",
        "--template",
        "-i",
        "-q",
        "-t",
    }
)


#: a word written out: in single quotes, in double quotes with nothing to expand, or plain
_GH_LITERAL = re.compile(r"""'[^']*'|"[^"$`%^]*"|[^'"$`{}()@%^*?\[~]+""")


def _gh_refused(st: Statement) -> bool:
    """Return whether a `gh` is outside what the agent may run.

    The list says what is allowed, because a list of what is not allowed always misses a spelling.
    A word the shell would still expand, or input from a pipe, is refused: the guard must read
    every word to judge it. The locks stand on the sign-in, variables, environments, branch
    protection and pending approvals, and none of them is on the list.
    """
    if st.program != "gh":
        return False
    fed = (
        st.upstream is not None
        or st.heredoc is not None
        or any(op.startswith("<") for op, _target in st.redirects)
    )
    if fed or not all(_GH_LITERAL.fullmatch(word) for word in st.raw[1:]):
        return True
    if len(st.words) < 2:
        return False
    group, *args = st.words[1:]
    if any(a.startswith("--admin") for a in args):
        return True
    if group == "auth":
        return args != ["status"]
    if group == "api":
        flags = [a.split("=", 1)[0] for a in args if a.startswith("-")]
        return not _GH_API_READS.issuperset(flags)
    if group in ("--help", "--version", "help"):
        return bool(args)
    return not args or args[0] not in _GH_ALLOWED.get(group, ())


#: an option that makes sed edit its files in place: -i, -i.bak, -ni, -Ei, --in-place[=SUF]
_SED_IN_PLACE = re.compile(r"^(?:-[A-Za-z]*i|--in-place(?:=|$))")
#: redirects of the statement's output (not 2> / &>, which carry no sed output)
_OUTPUT = frozenset({">", ">>", ">|", "1>", "1>>", "1>|"})
_NOT_A_FILE = frozenset({"/dev/null", "nul", "$null"})
#: every command that changes the shell's folder, in bash, cmd and PowerShell
_FOLDER_CHANGERS = frozenset(
    {"cd", "chdir", "pushd", "popd", "set-location", "push-location", "pop-location", "sl"}
)


def _sed_writes(st: Statement) -> list[str]:
    """How a sed statement writes a file; empty for any other statement or a sed that only
    prints."""
    if st.program != "sed":
        return []
    flag = next((a for a in st.words[1:] if _SED_IN_PLACE.match(a)), None)
    return ([f"in place, {flag}"] if flag else []) + [
        f"output redirected to {t}"
        for op, t in st.redirects
        if op in _OUTPUT and t.lower() not in _NOT_A_FILE
    ]


def bash_violations(cmd: str | None, powershell: bool = False) -> list[str]:
    """Every host-wide ban that fires on `cmd` (a PowerShell command when `powershell`).
    Applicability is per rule, never an early return (a foreign-repository target
    exempts nothing host-wide); no rule reads a repository."""
    statements = read(cmd or "", powershell=powershell)
    out: list[str] = []
    if any(_blind_stage(st) for st in statements):
        out.append(
            "ACTION BLOCKED: blind staging (git add -A/--all/.) sweeps another agent's "
            "in-flight files into a commit. Stage EXPLICIT paths — a commit asserts "
            "authorship of everything in it."
        )
    if any(_destroys_protected(st) for st in statements):
        out.append(
            "ACTION BLOCKED: this deletes, moves or truncates something under data/. That "
            "tree is gitignored -- there is NO history and NO undo. Test destructive "
            "behaviour against a COPY in a temp directory, never the real artefact. "
            "Restores INTO it stay legal; removal from it is operator-only."
        )
    if any(_disables_a_lock(st) for st in statements):
        out.append("ACTION BLOCKED: this disables a mechanical lock. Only the operator may.")
    if any(_takes_an_unsafe_fix(st) for st in statements):
        out.append(
            "ACTION BLOCKED: ruff's unsafe fixes change what code does; none is taken, in any "
            'file (AGENTS.md "Fix what you find").'
        )
    if any(_gh_refused(st) for st in statements):
        out.append(
            "ACTION BLOCKED: this `gh` is outside what the agent may run. Write every word out, "
            "or ask the operator."
        )
    if any(PYTHON.fullmatch(st.program) and reads_stdin(st) for st in statements):
        out.append(
            "ACTION BLOCKED: this python reads its program from stdin (`python -`, a heredoc, "
            "a pipe or </dev/null). On Windows an empty heredoc or </dev/null looks like a "
            "console and Python 3.13's REPL retries forever. Put the code in a script file and "
            "run it, or use `python -c`."
        )
    sed = [w for st in statements for w in _sed_writes(st)]
    if sed:
        out.append(
            f"ACTION BLOCKED: this command edits a file with sed ({'; '.join(sed)}). "
            "AGENTS.md: never "
            "edit source through a script. Make the change with the Edit tool (or Write for a new "
            "file), one edit at a time. A sed that only prints (sed -n '5p' f, sed 's/a/b/' f) is "
            "allowed."
        )
    if any(st.program in _FOLDER_CHANGERS for st in statements):
        out.append(
            "ACTION BLOCKED: this changes the shell's folder (cd, pushd, Set-Location or "
            "Push-Location). The hooks are found from the session's folder, so moving it breaks "
            "every guard. Name the folder in the command instead: `git -C <path>`, an absolute "
            "path, or `cwd=` in a python subprocess."
        )
    hidden = list(filter(None, (unseen(st) for st in statements)))
    if hidden:
        out.append(
            f"ACTION BLOCKED: the guards cannot see what this runs ({'; '.join(hidden)}). "
            "Write the "
            "command plainly: the program and its arguments as literal words — no $variable or "
            "substitution as the program, no text piped into a shell or interpreter, no "
            "-EncodedCommand, no Invoke-Expression."
        )
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
        return 0  # file edits carry no shell action to judge
    cmd = (payload.get("tool_input") or {}).get("command") or ""
    bad = bash_violations(cmd, powershell=payload.get("tool_name") == "PowerShell")
    if bad:
        sys.stderr.write(
            "BLOCKED — OPERATOR LAW: ban the ACTION, not the word.\n\n"
            + "\n".join(f"    {b}" for b in bad)
            + "\n"
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
