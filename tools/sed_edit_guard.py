"""SED EDIT GUARD: no file is edited with sed (AGENTS.md, Authority: "Never edit source through
a script: edits are made one at a time, as written"). PreToolUse for shell commands.

A sed command that writes a file is refused: in place (`-i`, `-i.bak`, `-ni`, `--in-place`) or
its output redirected to a file (`> f`, `>> f`; /dev/null, NUL and $null are not files). That
holds for every statement the command runs, as tools/shell_parse.read reads them (behind a
keyword, a wrapper or a subshell, as `find -exec sed`, inside a shell's command string or a
heredoc fed to a shell). A sed that only prints is allowed. The message says what to use instead:
the Edit and Write tools.

Limits: what shell_parse.read cannot see; a sed script's own `w` command (`sed -n '1,5w out' f`)
is not detected.
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
from tools.shell_parse import read  # noqa: E402

#: an option that makes sed edit its files in place: -i, -i.bak, -ni, -Ei, --in-place[=SUF]
IN_PLACE = re.compile(r"^(?:-[A-Za-z]*i|--in-place(?:=|$))")
#: redirects of the statement's output (not 2> / &>, which carry no sed output)
OUTPUT = frozenset({">", ">>", ">|", "1>", "1>>", "1>|"})
NOT_A_FILE = frozenset({"/dev/null", "nul", "$null"})

MESSAGE = ("BLOCKED: this command edits a file with sed ({what}). AGENTS.md: never edit source "
           "through a script. Make the change with the Edit tool (or Write for a new file), one "
           "edit at a time. A sed that only prints (sed -n '5p' f, sed 's/a/b/' f) is allowed.\n")


def edits(cmd: str, powershell: bool = False) -> list[str]:
    """How each sed in `cmd` (a PowerShell command when `powershell`) writes a file; empty when
    none does."""
    out = []
    for st in read(cmd, powershell=powershell):
        if st.program != "sed":
            continue
        flag = next((a for a in st.words[1:] if IN_PLACE.match(a)), None)
        if flag:
            out.append(f"in place, {flag}")
        out += [f"output redirected to {t}" for op, t in st.redirects if op in OUTPUT and t.lower() not in NOT_A_FILE]
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
    found = edits(str((payload.get("tool_input") or {}).get("command") or ""),
                  payload.get("tool_name") == "PowerShell")
    if found:
        sys.stderr.write(MESSAGE.format(what="; ".join(found)))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
