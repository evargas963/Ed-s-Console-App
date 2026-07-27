"""FRONT-END enforcement of the mechanical locks — blocks the EDIT, not just the commit (RC-66).

WHY THIS EXISTS. Every lock in tools/check_institutional_correctness.py runs at PRE-COMMIT. The
operator's law is explicitly FRONT-LOADED: "the RC row is opened at DISCOVERY, before the fix...
this law lives on the front end of coding and fixing end to end, not on the back end." Enforcing
at commit means the wrong change is already written by the time anything objects, and the RC row
degrades into retroactive paperwork. On 2026-07-26 that gap let a CSS patch land on static/
index.html with no root-cause row and no root-cause analysis — the patch did not even work — and
only the operator caught it. `.claude/settings.json` had `"hooks": {}`: nothing ran before a tool.

This runs as a PreToolUse hook on Edit/Write/NotebookEdit. Exit 2 BLOCKS the tool call.

Scope: the whole continuum — backend .py, frontend .html/.js/.css, SQL, config. Not just Python,
because the violation that triggered this was in the frontend.

Contract:
  * Editing a PRODUCTION file requires a root-cause row opened in THIS working tree first
    (a `| RC-` line in governance/root_cause_log.md that is not in HEAD).
  * Editing governance/, docs/, reports/, or tests/ is always allowed — that is HOW you open the
    row and lock the fix.
  * ED_PRETOOLUSE_GUARD=off disables it. That is deliberate and visible: an operator may switch it
    off, an agent may not silently route around it.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RC_LOG = "governance/root_cause_log.md"

#: Editing these is how you COMPLY (open the row, write the test, record evidence) — never blocked.
ALWAYS_ALLOWED_PREFIXES = (
    "governance/", "docs/", "reports/", "tests/", ".claude/", "calibration/",
)
#: Production surfaces across the whole continuum, not just backend.
PRODUCTION_SUFFIXES = (".py", ".html", ".js", ".css", ".sql", ".ts", ".jsx", ".tsx")


def _rel(p: str) -> str:
    try:
        return Path(p).resolve().relative_to(REPO).as_posix()
    except (ValueError, OSError):
        return Path(p).as_posix()


def _git(args: list[str]) -> str | None:
    try:
        r = subprocess.run(["git", *args], cwd=str(REPO), capture_output=True,
                           text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _has_new_rc_row() -> bool:
    """True when the working tree adds a `| RC-` row not present at HEAD.

    Covers staged AND unstaged, because the row is written the moment a defect is found —
    long before anything is staged.
    """
    head = _git(["show", f"HEAD:{RC_LOG}"])
    if head is None:
        return True                      # no git context / new repo -> never a false block
    head_ids = {ln.split("|")[1].strip() for ln in head.splitlines()
                if ln.startswith("| RC-") and "|" in ln[2:]}
    try:
        cur = (REPO / RC_LOG).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return True
    cur_ids = {ln.split("|")[1].strip() for ln in cur.splitlines()
               if ln.startswith("| RC-") and "|" in ln[2:]}
    if cur_ids - head_ids:
        return True                      # a brand-new RC id exists
    # A REOPENED row (status flipped back to OPEN) also counts as opening a root cause.
    diff = _git(["diff", "HEAD", "--", RC_LOG]) or ""
    return any(ln.startswith("+| RC-") for ln in diff.splitlines())


def main() -> int:
    if os.environ.get("ED_PRETOOLUSE_GUARD", "").strip().lower() in ("off", "0", "false"):
        return 0
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0                         # unreadable hook input is never a block
    tool = payload.get("tool_name") or ""
    if tool not in ("Edit", "Write", "NotebookEdit", "MultiEdit"):
        return 0
    fp = (payload.get("tool_input") or {}).get("file_path") or ""
    if not fp:
        return 0
    rel = _rel(fp)
    if rel.startswith(ALWAYS_ALLOWED_PREFIXES):
        return 0
    if not rel.endswith(PRODUCTION_SUFFIXES):
        return 0
    if _has_new_rc_row():
        return 0

    sys.stderr.write(
        "BLOCKED by the front-loaded recursive-5-why law (RC-66).\n\n"
        f"  You are editing PRODUCTION file: {rel}\n"
        "  No new root-cause row exists in governance/root_cause_log.md.\n\n"
        "The law is FRONT-LOADED (operator, non-negotiable): the INSTANT you find an issue you\n"
        "open its RC row FIRST, recurse each cause to a named ROOT, then fix end-to-end. A row\n"
        "written after the fix is retroactive paperwork, not analysis — and the fix is usually a\n"
        "patch, which is separately banned.\n\n"
        "Do this instead:\n"
        "  1. Add a `| RC-<n> | OPEN | <today> | <due> | defect | (1)->(2)->(3)->(4)->(5) ROOT: ... | plan |`\n"
        "     row to governance/root_cause_log.md (that file is never blocked).\n"
        "  2. Then make this edit, and ship a test that locks it.\n\n"
        "This mirrors check_recursive_five_why_front_loaded, but at EDIT time rather than commit\n"
        "time — the whole continuum, backend and frontend.\n"
    )
    return 2                             # exit 2 = block the tool call


if __name__ == "__main__":
    sys.exit(main())
