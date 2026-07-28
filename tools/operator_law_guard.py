"""OPERATOR LAW GUARD — bans ACTIONS, not words (RC-93).

OPERATOR 2026-07-27: "i don't want you to ban the terms i want you to ban the actions. non
negotiable."

He is right, and the first version of this file was wrong. It matched phrases — assumption words,
completion words — which is word-policing: any agent can rephrase around a list and the underlying
behaviour is untouched. Worse, it fired on its own author for DOCUMENTING the list, which would
have suppressed the lock inventory the operator had just asked for.

WHAT AN ACTION BAN LOOKS LIKE. The laws are about doing things without proof, so the enforcement
is: the ACTION cannot proceed unless the PROOF already ran. That requires knowing what ran, so this
guard keeps a per-turn LEDGER of every command executed, written at PreToolUse and cleared at Stop.

  PreToolUse(Bash|PowerShell)
      * records the command in the turn ledger
      * BLOCKS: grep/rg against repo files (2026-05-22 law), destructive git, and any command
        that disables a lock
      * BLOCKS `git commit` when the ledger holds NO verification command this turn — committing
        without having run the gate or the tests is the action, not the claim about it
  PreToolUse(Edit|Write|MultiEdit)
      * BLOCKS writing status CLOSED into governance/root_cause_log.md when the ledger holds no
        verification command this turn. Closing a root cause IS the assertion that it is fixed;
        the assertion is an action and it needs the evidence to exist first.
  Stop
      * BLOCKS ending a turn that CHANGED production code and ran no test/gate at all. Editing
        the money path and stopping without executing anything is the action.
      * clears the ledger for the next turn

Nothing here inspects prose. A turn may say whatever it likes; it may not DO these things without
the proof having run. Escape: ED_OPERATOR_LAW_GUARD=off — visible, operator-only.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# ── the turn ledger ───────────────────────────────────────────────────────────────────────
def _ledger_path(session_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id or "nosession")[:80]
    return Path(tempfile.gettempdir()) / f"ed_turn_ledger_{safe}.jsonl"


def _record(session_id: str, kind: str, detail: str) -> None:
    try:
        with _ledger_path(session_id).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"kind": kind, "detail": detail[:600]}) + "\n")
    except OSError:
        pass


def _ledger(session_id: str) -> list[dict]:
    p = _ledger_path(session_id)
    if not p.exists():
        return []
    out = []
    try:
        for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                out.append(json.loads(line))
            except (json.JSONDecodeError, ValueError):
                continue
    except OSError:
        return []
    return out


def _clear(session_id: str) -> None:
    try:
        _ledger_path(session_id).unlink(missing_ok=True)
    except OSError:
        pass


# ── what counts as PROOF HAVING RUN ───────────────────────────────────────────────────────
#: A command that produces evidence about this repo's behaviour: the test suite, a gate, a
#: checker, an audit, or a live probe. Reading a file is not proof; executing something is.
_VERIFICATION = re.compile(
    r"\b(?:pytest|check_[a-z_]+\.py|tools/[a-z_]+_audit\.py|tools/[a-z_]+_report\.py|"
    r"code_health_panel\.py|data_faucet_audit|repo_exposure_audit|ruff\s+check|mypy|"
    r"node\s+--check|urllib\.request|127\.0\.0\.1:8000)\b", re.I)

_PRODUCTION_SUFFIX = (".py", ".html", ".js", ".css", ".ts", ".sql")
_NON_PRODUCTION = ("tests/", "tests\\", "governance/", "governance\\", "docs/", "reports/",
                   ".claude/", "calibration/")

_GREP_AGAINST_FILES = re.compile(
    r"(?:^|[|;&]\s*)(?:grep|rg|egrep|fgrep)\b(?![^|;&\n]*\|)[^|;&\n]*?"
    r"(?:\*\.|\.py\b|\.md\b|\.html\b|\.js\b|\.json\b|\.yaml\b|-r\b|-R\b|--include|"
    r"-t\s+\w+|--type|--glob|\s\.$|\s\./)", re.I)
_DESTRUCTIVE_GIT = re.compile(
    r"\bgit\s+(?:reset\s+--hard|checkout\s+--\s|clean\s+-[a-z]*f|push\s+--force(?!-with-lease))", re.I)
_SKIP_HOOKS = re.compile(r"--no-verify|ED_PRETOOLUSE_GUARD=off|ED_STOP_GUARD=off|"
                         r"ED_PROOF_ONLY_GUARD=off|ED_OPERATOR_LAW_GUARD=off", re.I)
_GIT_COMMIT = re.compile(r"\bgit\s+commit\b", re.I)


def _has_verification(ledger: list[dict]) -> bool:
    return any(_VERIFICATION.search(e.get("detail", "")) for e in ledger if e.get("kind") == "bash")


def _production_edits(ledger: list[dict]) -> list[str]:
    out = []
    for e in ledger:
        if e.get("kind") != "edit":
            continue
        p = e.get("detail", "").replace("\\", "/")
        if any(seg in p for seg in _NON_PRODUCTION):
            continue
        if p.endswith(_PRODUCTION_SUFFIX):
            out.append(p)
    return out


def shell_executed_part(cmd: str) -> str:
    """Only what the SHELL will run. Heredoc bodies and `-c` payloads are DATA.

    The guard blocked its own negative-control suite the first time it ran, because that suite
    passes strings like a destructive-git command as TEST FIXTURES inside a python heredoc. The
    shell never executes them — the interpreter receives them as text. Scanning data as if it
    were commands makes the guard fire on anything that merely DESCRIBES a banned action, which
    is the word-policing failure the operator rejected, reappearing one layer down.
    """
    # Strip heredoc bodies:  <<'TAG' ... TAG   /   <<TAG ... TAG
    cmd = re.sub(r"<<-?\s*(['\"]?)(\w+)\1.*?^\s*\2\s*$", " <<HEREDOC ", cmd,
                 flags=re.S | re.M)
    # Strip a quoted -c payload:  python -c "..."   /   python -c '...'
    cmd = re.sub(r"-c\s+(['\"])(?:\\.|(?!\1).)*\1", " -c PAYLOAD ", cmd, flags=re.S)
    return cmd


def bash_violations(cmd: str, ledger: list[dict]) -> list[str]:
    cmd = shell_executed_part(cmd)
    out: list[str] = []
    if _GREP_AGAINST_FILES.search(cmd):
        out.append("ACTION BLOCKED: shell grep/rg pointed at repo FILES. Standing law "
                   "(2026-05-22): read files end-to-end or use structural/AST analysis. Filtering "
                   "a command's own stdout is allowed; searching the codebase is not.")
    if _DESTRUCTIVE_GIT.search(cmd):
        out.append("ACTION BLOCKED: destructive git can discard operator work. Hand it to the "
                   "operator.")
    if _SKIP_HOOKS.search(cmd):
        out.append("ACTION BLOCKED: this disables a mechanical lock. Only the operator may.")
    if _GIT_COMMIT.search(cmd) and not _has_verification(ledger):
        out.append("ACTION BLOCKED: committing without having RUN anything this turn. A commit "
                   "asserts the work is sound; run the gate, the tests, or a live probe first — "
                   "the proof must exist before the action, not in the message describing it.")
    return out


def edit_violations(path: str, new_text: str, ledger: list[dict]) -> list[str]:
    p = (path or "").replace("\\", "/")
    if not p.endswith("governance/root_cause_log.md"):
        return []
    if not re.search(r"\|\s*CLOSED\s*\|", new_text or ""):
        return []
    if _has_verification(ledger):
        return []
    return ["ACTION BLOCKED: closing a root-cause row without having RUN a verification this "
            "turn. Closing IS the assertion that the defect is fixed. Run the test that locks it, "
            "or the gate, or a live probe — then close."]


def stop_violations(ledger: list[dict]) -> list[str]:
    edits = _production_edits(ledger)
    if edits and not _has_verification(ledger):
        return [f"ACTION BLOCKED: this turn changed production code and ran NOTHING. "
                f"Edited: {', '.join(sorted(set(edits))[:6])}. Execute the affected tests or a "
                f"live probe before ending the turn."]
    return []


def main() -> int:
    if os.environ.get("ED_OPERATOR_LAW_GUARD", "").strip().lower() in ("off", "0", "false"):
        return 0
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    sid = payload.get("session_id") or ""
    tool = payload.get("tool_name") or ""
    ti = payload.get("tool_input") or {}
    ledger = _ledger(sid)

    if tool in ("Bash", "PowerShell"):
        cmd = ti.get("command") or ""
        bad = bash_violations(cmd, ledger)
        if bad:
            sys.stderr.write("BLOCKED (RC-93) — OPERATOR LAW: ban the ACTION, not the word.\n\n"
                             + "\n".join(f"    {b}" for b in bad) + "\n")
            return 2
        _record(sid, "bash", cmd)
        return 0

    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        path = ti.get("file_path") or ""
        body = ti.get("new_string") or ti.get("content") or ""
        bad = edit_violations(path, body, ledger)
        if bad:
            sys.stderr.write("BLOCKED (RC-93) — OPERATOR LAW: ban the ACTION, not the word.\n\n"
                             + "\n".join(f"    {b}" for b in bad) + "\n")
            return 2
        _record(sid, "edit", path)
        return 0

    # Stop
    if payload.get("stop_hook_active") is True:
        _clear(sid)
        return 0
    bad = stop_violations(ledger)
    if bad:
        sys.stderr.write("BLOCKED (RC-93) — OPERATOR LAW: ban the ACTION, not the word.\n\n"
                         + "\n".join(f"    {b}" for b in bad)
                         + "\n\nRun it, then end the turn.\n")
        return 2
    _clear(sid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
