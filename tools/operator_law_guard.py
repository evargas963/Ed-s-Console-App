"""OPERATOR LAW GUARD — three host-wide ACTION bans on shell commands (RC-93: ban the action,
never the word). PreToolUse for the shell-command tools (`hook_chain.BASH_TOOLS`); exit 2 blocks.

What survives, and the concrete failure each prevents (KEEP/MERGE/DELETE, 2026-09-10):

  * UNRECOVERABLE-TREE DESTRUCTION (RC-273). `.gitignore` excludes data/, backups/ and models/,
    so the 27 GB database has no history at all. The agent destroyed it TWICE in ten minutes
    (`mv` to exercise a missing-file branch, `rm -f` while testing the ACL meant to prevent the
    first). An OS ACL cannot carry this — the account owns the file and can rewrite the DACL
    (proven with a canary). Nothing native protects an untracked file from `rm`.
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

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.hook_chain import BASH_TOOLS  # noqa: E402 — the ONE shell-tool roster (RC-520)
from tools.shell_parse import shell_executed_part  # noqa: E402 — the ONE shell parser

#: RC-273 — the trees that are gitignored and therefore UNRECOVERABLE. Path-SEGMENT anchored:
#: `AppData/`, `mydata/`, `_data/` do not match; `foo/data/`, `"data/`, `>data/` do.
_PROTECTED_TREE = r"(?<![A-Za-z0-9_.-])(?:data|backups|models)[\\/]"
_PROTECTED_DESTRUCTIVE = re.compile(
    r"(?:\brm\b|\bdel\b|\berase\b|\brmdir\b|Remove-Item|\bunlink\b|shutil\.rmtree"
    r"|os\.remove|os\.unlink|\.unlink\(|\btruncate\b)"
    r"[^\n;|&]{0,200}?" + _PROTECTED_TREE
    + r"|(?:\bmv\b|\bmove\b|Move-Item|shutil\.move|os\.rename|os\.replace)\s+"
      r"[^\n;|&]{0,40}?" + _PROTECTED_TREE
    + r"|>\s*[^\n;|&>]{0,80}?" + _PROTECTED_TREE,
    re.I)


def _protected_path_violation(raw: str) -> bool:
    """True when a command would delete, move or truncate an unrecoverable artefact.

    Reads the RAW command text, heredocs and payloads included, because those are the
    channels that dodge the Edit/Write hook. A commit does not touch the working tree (a
    message DESCRIBING the incident contains the command text); a COPY INTO a protected tree
    is a restore and stays legal — removal is what has no undo.
    """
    if not raw:
        return False
    if re.search(r"\bgit\s+commit\b", raw, re.I):
        return False
    if re.search(r"\b(?:cp|copy|Copy-Item)\b", raw, re.I) and not re.search(
            r"(?:\brm\b|\bdel\b|Remove-Item|\bmv\b|Move-Item)", raw, re.I):
        return False
    return bool(_PROTECTED_DESTRUCTIVE.search(raw))


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
                   "data/, backups/ or models/. Those trees are gitignored -- there is NO "
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
