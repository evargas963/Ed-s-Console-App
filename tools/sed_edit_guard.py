"""SED EDIT GUARD: no file is edited with sed (AGENTS.md, Authority: "Never edit source through
a script: edits are made one at a time, as written"). PreToolUse for shell commands.

A sed command that writes a file is refused: in place (`-i`, `-i.bak`, `-ni`, `--in-place`) or
its output redirected to a file (`> f`, `>> f`; /dev/null, NUL and $null are not files). That
holds wherever sed runs in the command: any statement of a chain, behind a wrapper (env, xargs,
sudo), as `find -exec sed`, and inside a `bash -c` / `sh -c` / `pwsh -Command` payload. A sed
that only prints is allowed. The message says what to use instead: the Edit and Write tools.

Limits: a heredoc body is data to the shell parser and is not judged (a heredoc fed to a shell,
`bash <<EOF`, can still run sed); a sed script's own `w` command (`sed -n '1,5w out' f`) is not
detected.
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
from tools.shell_parse import iter_command_segments, segment_head  # noqa: E402

#: an option that makes sed edit its files in place: -i, -i.bak, -ni, -Ei, --in-place[=SUF]
IN_PLACE = re.compile(r"^(?:-[A-Za-z]*i|--in-place(?:=|$))")
#: a redirect of the statement's output to a file (not 2> / &>, which carry no sed output)
REDIRECT = re.compile(r"(?:^|[^<>&0-9])>{1,2}\s*(\"[^\"]*\"|'[^']*'|[^\s;&|]+)")
NOT_A_FILE = frozenset({"/dev/null", "nul", "$null"})
#: a shell run with a command string: bash -c "...", sh -lc '...', pwsh -Command "..."
SHELL_PAYLOAD = re.compile(
    r"\b(?:bash|sh|zsh|dash|pwsh|powershell)(?:\.exe)?\b[^\n;&|]*?\s-(?:[a-z]*c|Command)\s+"
    r"(?:\"((?:\\.|[^\"\\])*)\"|'([^']*)')", re.I)

MESSAGE = ("BLOCKED: this command edits a file with sed ({what}). AGENTS.md: never edit source "
           "through a script. Make the change with the Edit tool (or Write for a new file), one "
           "edit at a time. A sed that only prints (sed -n '5p' f, sed 's/a/b/' f) is allowed.\n")


def _sed_args(head: str, toks: list[str]) -> "list[str] | None":
    """The arguments of the sed this statement runs, or None when it runs no sed."""
    if Path(head).name.lower().removesuffix(".exe") == "sed":
        return [t.strip("\"'") for t in toks[1:]]
    for i, t in enumerate(toks[:-1]):                       # find ... -exec sed ... ;
        if t in ("-exec", "-execdir") and Path(toks[i + 1].strip("\"'")).name.lower().removesuffix(".exe") == "sed":
            return [a.strip("\"'") for a in toks[i + 2:]]
    return None


def edits(cmd: str, cwd: str = "") -> list[str]:
    """How each sed in `cmd` writes a file; empty when none does."""
    out = []
    for _cwd, seg in iter_command_segments(cmd, cwd):
        head, toks = segment_head(seg)
        args = _sed_args(head, toks)
        if args is None:
            continue
        flag = next((a for a in args if IN_PLACE.match(a)), None)
        if flag:
            out.append(f"in place, {flag}")
        targets = [m.group(1).strip("\"'") for m in REDIRECT.finditer(seg)]
        out += [f"output redirected to {t}" for t in targets if t.lower() not in NOT_A_FILE]
    for m in SHELL_PAYLOAD.finditer(cmd):
        out += edits(m.group(1) if m.group(1) is not None else m.group(2), cwd)
    return out


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.stderr.write("BLOCKED: invalid hook payload.\n")
        return 2
    if not isinstance(payload, dict):
        sys.stderr.write("BLOCKED: the hook payload is not an object.\n")
        return 2
    if payload.get("tool_name") not in BASH_TOOLS:
        return 0
    tool_input = payload.get("tool_input") or {}
    found = edits(str(tool_input.get("command") or ""), str(payload.get("cwd") or ""))
    if found:
        sys.stderr.write(MESSAGE.format(what="; ".join(found)))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
