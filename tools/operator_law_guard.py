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
# RC-186 self-audit finding (2026-08-02): the enumerated list covered only the four *_GUARD
# names, so the mockup lock's ED_UI_MOCKUP_LOCK=off escape was silently agent-usable the day it
# shipped. Generalized: ANY ED_*_GUARD/ED_*_LOCK=off is a lock-disable action — operator-only.
# RC-189 GUN 2 (Cursor audit v1): the generalization kept the single unquoted-POSIX SHAPE while
# this host's agent shell is PowerShell. Widened to quoted values, spaced assignment, $env:,
# Set-Item/New-Item on the env: drive, and [Environment]::SetEnvironmentVariable. The negative
# lookahead keeps ED_*_GUARD_TIMEOUT-style names out; grant vars (ED_UI_MOCKUP_APPROVE=1) and
# non-disable values ('on', '1') never match.
# Cursor v2 residuals sealed (RC-189): `${env:NAME}` braces, `PSVariable.Set`, and a COMPUTED
# value (`("o"+"ff")`) — a lock variable has no legitimate computed assignment, so ANY
# parenthesized/expression value is refused outright rather than pattern-matching its pieces.
_SKIP_HOOKS = re.compile(
    r"--no-verify"
    r"|(?:\$\{?env:)?ED_[A-Z_]*(?:_GUARD|_LOCK)(?![A-Z0-9_])['\"\s\]\}]*=\s*"
    r"(?:['\"]?\s*(?:off|false|0)\b|\()"
    r"|(?:Set-Item|New-Item|SetEnvironmentVariable|PSVariable)[^\n]{0,80}?"
    r"ED_[A-Z_]*(?:_GUARD|_LOCK)(?![A-Z0-9_])[^\n]{0,60}?['\"\s,(](?:off|false|0)\b",
    re.I)
#: RC-189 GUN 1 — the approval registry and the operator grant are OPERATOR CHANNELS. Shell
#: access to either (read, write, heredoc, -c payload — RAW command text, deliberately wider
#: than shell_executed_part, because heredocs and payloads ARE the write channels that dodge
#: the Edit/Write hook) is refused outright: the registry is read with the Read tool and
#: mutated only through Edit/Write, where the RC-189 provenance hook judges it.
#: Cursor v2: the contiguous-token ban lost to string concatenation, so the scan (a) first
#: strips the LEGITIMATE code-path spellings (the lock module and its test file), then
#: (b) matches FRAGMENTS of the registry name and grant var. Deep concatenation of fragments
#: is backstopped by the constructed-write bans below: a write whose target is not a literal
#: safe-data path is refused no matter what it spells.
_APPROVAL_ALLOWED_SPELLINGS = re.compile(
    r"(?:tools[/\\])?(?:test_)?ui_mockup_lock(?:_v1)?(?:\.py)?", re.I)
_APPROVAL_FRAGMENT = re.compile(
    r"ui_mockup|mockup_approv|approvals\.json|ED_UI_MOCKUP", re.I)


def _approval_channel_violation(raw: str) -> bool:
    return bool(_APPROVAL_FRAGMENT.search(_APPROVAL_ALLOWED_SPELLINGS.sub("", raw)))


def _safe_data_target(target: str) -> bool:
    """A write target is safe only as a string LITERAL with a data extension, and never the
    approval registry or anything under .claude/ (Cursor v2: a literal .json there is the
    registry-forge / grant-mint channel wearing a legal extension). Other governance data
    files stay heredoc-legal — governance-row edits are HOW agents comply (battery contract)."""
    if not _DATA_TARGET_LITERAL.match(target):
        return False
    return not re.search(r"\.claude[/\\]|ui_mockup|approvals\.json", target, re.I)


#: Cursor v2: `python -c "p='gov'+'ernance/...'; open(p,'w')"` — the -c payload is stripped
#: from the executed-part scan as data, but the WRITE it performs is an action. Payload writes
#: obey the same E-37 rule as heredocs: literal safe-data targets only. This also closes the
#: compounding escape `python -c "open('static/chart.html','w')"` — .html is not a data
#: extension, so a production-surface write from a payload is refused.
_C_PAYLOAD = re.compile(r"-c\s+(['\"])((?:\\.|(?!\1).)*)\1", re.S)


def _payload_write_violation(raw: str) -> bool:
    for pm in _C_PAYLOAD.finditer(raw):
        body = pm.group(2)
        for m in _HEREDOC_WRITE_SITE.finditer(body):
            if m.group(3):
                return True
            target = (m.group(1) or "").strip()
            if m.group(2) is not None:
                tm = re.search(r"\(\s*(['\"][^'\"]+['\"])\s*\)\s*$", m.group(2))
                target = tm.group(1) if tm else ""
            if not _safe_data_target(target):
                return True
    return False


#: Cursor v2: PowerShell write cmdlets with a CONSTRUCTED destination (Join-Path, $(),
#: string concat) or a destination in the governance/.claude trees or with a production
#: suffix dodge every token ban by never spelling the name. Source and governance mutations
#: go through Edit/Write, where the hooks judge them.
_PS_WRITE_BAD = re.compile(
    r"(?:Copy-Item|Move-Item|Set-Content|Add-Content|Out-File)\b[^\n;|]{0,160}?"
    r"(?:Join-Path|\$\(|['\"]\s*\+|governance[/\\]|\.claude[/\\]|"
    r"\.(?:py|html|js|css|ts|sql)\b)", re.I)
_GIT_COMMIT = re.compile(r"\bgit\s+commit\b", re.I)
#: 2026-07-28: `git add -A` swept another agent's in-flight files into MY commits twice in one
#: day (a 530KB runtime log; audit scratch). In a two-agent worktree, blind staging asserts
#: authorship over work the committer never saw.
#: v18 widened: `*`, `-- .`, and `-u` are the same blind action wearing other flags.
_BLIND_STAGE = re.compile(
    r"\bgit\s+add\s+(?:--\s+)?(?:-A\b|--all\b|-u\b|--update\b|\*|\.(?:\s|$))")
#: 2026-07-28 (E-15 class, 4th recurrence today): writing SOURCE files through shell-heredoc
#: python scripts keeps mangling escapes (literal \n breaking string literals, backspace bytes
#: in regexes). The Edit/Write tools are the sanctioned path for source; heredoc scripts stay
#: legal for governance-row edits and data tasks. The scan looks at the RAW command because the
#: banned ACTION is the write performed by the interpreter the shell launches.
#: v18 widened; GRADUATED 2026-07-29 (E-37): the stated variable-path escape was demonstrated
#: the SAME DAY it was written down — a heredoc broke a test file through
#: `p='tests/x.py'; io.open(p,'w')`, exactly the named boundary. Per the graduation clause:
#: every heredoc file-write is now inspected; it is legal ONLY when the opened path is a
#: string LITERAL ending in a data extension (.md/.json/.jsonl/.txt/.csv/.log). A variable
#: path cannot be verified from the command text, so it is refused outright.
_HEREDOC_WRITE_SITE = re.compile(
    r"(?:(?:io\.)?open\(\s*([^,)]+?)\s*,\s*['\"][wa]b?['\"]"
    r"|([A-Za-z_][\w.()'\"/\\-]*)\.write_text\("
    r"|\.py(['\"])\s*\)\s*\.open\(\s*(['\"])[wa]\4)", re.S)
_DATA_TARGET_LITERAL = re.compile(r"^['\"][^'\"]+\.(?:md|json|jsonl|txt|csv|log)['\"]$")


def _heredoc_write_violation(raw: str) -> bool:
    """True when a heredoc body performs a file-write whose target is not a verifiable
    safe-data string literal (E-37 graduation; Cursor v2 tightened governance/.claude out
    of the legal target set — see _safe_data_target)."""
    hd = re.search(r"<<-?\s*(['\"]?)(\w+)\1(.*?)^\s*\2\s*$", raw, re.S | re.M)
    if not hd:
        return False
    body = hd.group(3)
    for m in _HEREDOC_WRITE_SITE.finditer(body):
        if m.group(3):                       # Path('x.py').open('w') — source, always banned
            return True
        target = (m.group(1) or "").strip()
        if m.group(2) is not None:           # <expr>.write_text( — target is the expr's path
            pm = re.search(r"\(\s*(['\"][^'\"]+['\"])\s*\)\s*$", m.group(2))
            target = pm.group(1) if pm else ""
        if not _safe_data_target(target):
            return True
    return False
#: v19: `cat > foo.py <<EOF` writes source through the SHELL itself — no interpreter involved,
#: so the heredoc rule never saw it. Any shell redirect INTO a .py file is the same banned
#: action (writing source outside Edit/Write); .py targets only, so log/json redirects stay legal.
_SHELL_REDIRECT_SOURCE = re.compile(r"(?:^|[^&\d])>{1,2}\s*[^\s;|&<>]+\.py\b")


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
    # Strip quoted -m payloads (commit/tag messages): the FIRST live run of the blind-stage
    # rule blocked a commit whose MESSAGE described the ban — message text is data, and a
    # guard that fires on descriptions is the word-policing failure again (same lesson as
    # heredocs, same day it was written).
    cmd = re.sub(r"-m\s+(['\"])(?:\\.|(?!\1).)*\1", " -m MESSAGE ", cmd, flags=re.S)
    return cmd


def bash_violations(cmd: str, ledger: list[dict]) -> list[str]:
    raw = cmd
    cmd = shell_executed_part(cmd)
    out: list[str] = []
    if _BLIND_STAGE.search(cmd):
        out.append("ACTION BLOCKED: blind staging (git add -A/--all/.) swept another agent's "
                   "in-flight files into a commit twice on 2026-07-28. Stage EXPLICIT paths — "
                   "a commit asserts authorship of everything in it.")
    if _heredoc_write_violation(raw):
        out.append("ACTION BLOCKED (E-37 graduation): heredoc file-writes are legal ONLY to a "
                   "string-LITERAL data target (.md/.json/.jsonl/.txt/.csv/.log). Variable "
                   "paths and source files are refused — the variable-path escape broke a test "
                   "file the same day it was written down as a boundary. Use Edit/Write.")
    if _SHELL_REDIRECT_SOURCE.search(cmd):
        out.append("ACTION BLOCKED: shell redirect into a .py file writes source outside the "
                   "Edit/Write tools (v19: `cat > x.py <<EOF` walked around the heredoc rule). "
                   "Same action, same ban; non-source redirects stay legal.")
    if _GREP_AGAINST_FILES.search(cmd):
        out.append("ACTION BLOCKED: shell grep/rg pointed at repo FILES. Standing law "
                   "(2026-05-22): read files end-to-end or use structural/AST analysis. Filtering "
                   "a command's own stdout is allowed; searching the codebase is not.")
    if _DESTRUCTIVE_GIT.search(cmd):
        out.append("ACTION BLOCKED: destructive git can discard operator work. Hand it to the "
                   "operator.")
    if _SKIP_HOOKS.search(cmd):
        out.append("ACTION BLOCKED: this disables a mechanical lock. Only the operator may.")
    if _approval_channel_violation(raw):
        out.append("ACTION BLOCKED (RC-189): shell access to the mockup-approval registry or "
                   "the operator grant variable. Self-approve through a shell write was "
                   "Cursor's top break. Read the registry with the Read tool; mutate it only "
                   "through Edit/Write (the provenance hook judges those); the grant is set by "
                   "the operator outside agent channels.")
    if _payload_write_violation(raw):
        out.append("ACTION BLOCKED (RC-189 v2): a -c payload performs a file-write whose "
                   "target is not a literal safe-data path (constructed paths and "
                   "governance/.claude/source targets are how self-approve dodged the token "
                   "ban). Use the Edit/Write tools — the hooks judge those.")
    if _PS_WRITE_BAD.search(cmd):
        out.append("ACTION BLOCKED (RC-189 v2): PowerShell write cmdlet with a constructed, "
                   "governance/.claude, or production-suffix destination. Use the Edit/Write "
                   "tools — a destination the command never spells cannot be audited.")
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


#: RC-125 (operator law, 2026-07-29): "you must always probe the live session before you
#: provide any answers." A live-session probe is a command that touches the RUNNING system or
#: its data — the console API, the DB, or a rendered-page probe. Tests and gates verify CODE;
#: they do not observe the live session, so they deliberately do not satisfy this.
#: First live firing (2026-07-29 08:31 ET): the rule blocked a turn whose probe was a DIRECT
#: Schwab chain poll — the strongest observation possible — because the vendor-call spellings
#: were missing from this list. Widened the same minute.
_LIVE_PROBE = re.compile(
    r"127\.0\.0\.1|/api/|urlopen|DB_PATH|sqlite3|option_chain|snapshots|"
    r"ticker_journey_probe|playwright|get_chain|get_quote|schwab", re.I)


def _has_live_probe(ledger: list[dict]) -> bool:
    return any(_LIVE_PROBE.search(e.get("detail", ""))
               for e in ledger if e.get("kind") == "bash")


#: RC-190 (operator non-negotiable, 2026-08-02, "self audit is a non negotiable universally
#: repo wide"): a turn that changed ANY production surface must have RUN the per-turn self
#: adversarial audit — tools/turn_self_audit.py re-derives the turn's blast radius and re-runs
#: the attack suites against it, leaving a JSONL record. Ordinary pytest is verification;
#: it does not satisfy the audit, whose artifact is this tool's ledger entry.
_TURN_SELF_AUDIT = re.compile(r"turn_self_audit\.py", re.I)


def _has_turn_self_audit(ledger: list[dict]) -> bool:
    return any(_TURN_SELF_AUDIT.search(e.get("detail", ""))
               for e in ledger if e.get("kind") == "bash")


#: RC-203 (operator non-negotiable, 2026-08-02: "always research and then act... at an
#: institutional/mit/bloomberg manner... universal throughout the entire repo"): the audit
#: record of a production-editing turn must NAME the reference researched before acting.
#: The drag-clamp defect shipped because view machinery was invented while the reference
#: implementation (chart.html clampView) sat in the same repo; the bubble layer shipped
#: against the recorded spec (direction doc §3.3) without re-reading it. Research is an
#: ACTION with an artifact — the named reference in the audit ledger — so it can be forced.
def _latest_audit_lacks_research(log: Path | None = None) -> bool:
    """True when latest same-turn audit fails full research_violation (RC-203/RC-205).

    Empty string used to be the only test; a non-resolving vibe string must also BLOCK."""
    if log is None:
        log = Path(__file__).resolve().parent.parent / "reports" / "turn_self_audit_log.jsonl"
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    except OSError:
        return False
    if not lines:
        return False
    try:
        rec = json.loads(lines[-1])
    except ValueError:
        return False
    import time as _time
    if _time.time() - float(rec.get("ts_utc", 0) or 0) > 12 * 3600:
        return False
    changed = list(rec.get("changed") or [])
    if not changed:
        return False
    try:
        from tools.turn_self_audit import research_violation
    except ImportError:
        from turn_self_audit import research_violation  # type: ignore
    return research_violation(str(rec.get("research", "") or ""), changed) is not None


def stop_violations(ledger: list[dict]) -> list[str]:
    out: list[str] = []
    edits = _production_edits(ledger)
    if edits and not _has_verification(ledger):
        out.append(f"ACTION BLOCKED: this turn changed production code and ran NOTHING. "
                   f"Edited: {', '.join(sorted(set(edits))[:6])}. Execute the affected tests or "
                   f"a live probe before ending the turn.")
    if edits and not _has_turn_self_audit(ledger):
        out.append("ACTION BLOCKED (RC-190): this turn changed production code and the "
                   "per-turn self adversarial audit never RAN. Universal, repo-wide, "
                   "non-negotiable: run `.venv/Scripts/python.exe tools/turn_self_audit.py` "
                   "(add --tests for surfaces the stem scan cannot match), fix what it finds, "
                   "then end the turn.")
    if edits and _has_turn_self_audit(ledger) and _latest_audit_lacks_research():
        out.append("ACTION BLOCKED (RC-203): the turn's self-audit record names NO research. "
                   "Operator law: research THEN act, institutional level, universal. Re-run "
                   "`tools/turn_self_audit.py --research '<the spec/reference consulted and "
                   "what it settled>'` — a concrete artifact (path, §section, URL).")
    # RC-125: every answer stands on a same-turn observation of the live session — the morning
    # of 2026-07-29 was lost to an answer reasoned from a screenshot while the live payload sat
    # one command away. Absolute by operator order: probe first, then answer.
    if not _has_live_probe(ledger):
        out.append("ACTION BLOCKED (RC-125): no live-session probe ran this turn. Operator law: "
                   "always probe the live session before providing any answer — query the "
                   "console API, the DB, or run a rendered-page probe, paste what it said, "
                   "then answer.")
    return out


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
