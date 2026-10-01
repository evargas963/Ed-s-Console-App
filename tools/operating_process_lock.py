"""Operating-process mechanical lock: the tree-destructive git actions (`git reset`, `git stash`,
`checkout --`, `clean -f`, force push) and pipe-masked commits, consumed by
tools/process_lock_guard.py at PreToolUse. The rules live in `AGENTS.md` § Authority.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# The ONE shell segmenter (tools/shell_parse.py, stdlib-only, BEDROCK 2026-09-06): the class
# rule below judges each chained statement on its own (RC-525), and a second splitter here
# would be one truth with two answers.
from tools.shell_parse import iter_command_segments  # noqa: E402

#: Wipe-protected paths: the one writer and the guards.
PROTECTED_PATHS: tuple[str, ...] = (
    "db.py",
    "tools/hook_chain.py",
    "tools/pretooluse_guard.py",
    "tools/operator_law_guard.py",
    "tools/operating_process_lock.py",
    "tools/process_lock_guard.py",
)

#: LOCK-2 (RC-231): the tree-destructive git CLASS, not just `reset --hard`. Three wipes on
#: 2026-08-03 (RC-210 x2, RC-229) used soft forms the literal-match ban never saw. A command
#: matching a destructive verb AND touching a protected/product path (or bare, whole-tree
#: forms) BLOCKS at PreToolUse in EVERY session wired to process_lock_guard.
#: BEDROCK 2026-09-06: ONE owner. The universal hard forms (reset --hard, checkout -- <any
#: path>, clean -f, push --force without lease) used to live as a second regex in
#: operator_law_guard, "deliberately split, both firing" — two rules answering one question.
#: They are `_UNIVERSAL_DESTRUCTIVE_RE` below and refuse regardless of target; the class rule
#: covers the full reset/restore/checkout--/clean/stash verb family on protected/bare targets.
#:
#: RC-525 (ported from #221's row 508, re-measured on ac3f78fb 2026-09-06): three holes and one
#: over-block. `git -C <other> reset --hard` passed because the global-option skip admitted
#: only flags, not a flag WITH its argument; `git push -f` passed because only the long
#: spelling was named; `git restore --staged x && git reset --mixed HEAD~1` passed because the
#: safe list was searched across the WHOLE command, so one safe statement exempted everything
#: chained after it. The globals prefix admits an option with its argument; the push clause
#: admits flags after the refspec and the short `-f`; the class rule is judged PER SEGMENT.
_GIT_GLOBAL_WITH_ARG: tuple[str, ...] = (
    "-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env")
_GIT_GLOBALS = (
    r"(?:(?:" + "|".join(__import__("re").escape(o) for o in _GIT_GLOBAL_WITH_ARG)
    + r")(?:=\S+|\s+\S+)\s+|-\S+\s+)*")
_UNIVERSAL_DESTRUCTIVE_RE = __import__("re").compile(
    r"\bgit\s+" + _GIT_GLOBALS + r"(?:"
    r"reset\b"
    r"|stash\b(?!\s+(?:list|show)\b)"
    r"|checkout\s+--\s"
    r"|clean\s+-[a-z]*f"
    r"|push\s+(?:[^|;&]*\s)?(?:--force|-[a-zA-Z]*f[a-zA-Z]*(?=\s|$))"
    r")",
    __import__("re").I)
_RESET_GUARD_RE = __import__("re").compile(
    r"\bgit\s+" + _GIT_GLOBALS
    + r"(reset\b|restore\b|checkout\s+(?:\S+\s+)*--\s|clean\b|stash\b)",
    __import__("re").I)
_RESET_GUARD_SAFE_RE = __import__("re").compile(
    r"\bgit\s+" + _GIT_GLOBALS
    + r"(restore\s+--staged\b(?!.*--worktree)|stash\s+(?:list|show)\b|checkout\s+-b\b"
    r"|clean\s+(?:-\S*n\S*\b|--dry-run\b))",
    __import__("re").I)

#: RC-252: the STATIC inventory of what must never be wiped, independent of any mission.
#: LOCK-2 originally drew its targeted reach from PROTECTED_PATHS plus the ACTIVE mission's
#: scope_paths — so protection contracted whenever a mission narrowed, which is what a good
#: mission does. Under axiom-brand-landing-v1 that left `git restore -- static/chart.html`,
#: `git checkout -- server.py` and `git restore -- math_levels.py` all silent. Mission scope
#: is gone (2026-08-24 teardown); this static inventory alone defines LOCK-2 reach.
PRODUCT_WIPE_PROTECTED: tuple[str, ...] = (
    "db.py",
    "server.py",
    "time_et.py",
    "math_exposure_core.py",
    "math_levels.py",
    "liquidity_value_engine.py",
    "liquidity_models.py",
    "static/",
    "calibration/",
    "features/",
    "tools/",
)


#: RC-253: a command that pipes its heredoc INTO an interpreter is one where the body IS the
#: instruction, so the body must still be judged. Everywhere else a heredoc is data.
_INTERPRETER_RE = __import__("re").compile(
    r"(?:^|[|;&]\s*)(?:bash|sh|zsh|pwsh|powershell|cmd|eval|xargs|source|\.)\b",
    __import__("re").I)
_HEREDOC_RE = __import__("re").compile(
    r"<<-?\s*(['\"]?)([A-Za-z_]\w*)\1\s*?\n.*?^\2\s*$",
    __import__("re").S | __import__("re").M)
_MESSAGE_PAYLOAD_RE = __import__("re").compile(
    r"(-m|--message|--file|-F)\s+('[^']*'|\"[^\"]*\")")


def _strip_command_payloads(cmd: str) -> str:
    """RC-253: judge the ACTION, not the data the command carries (RC-93).

    A commit message that quotes `git reset --hard` is prose about an incident; the command
    itself touches nothing. Left unstripped, LOCK-2 fired hardest on the most precise incident
    write-ups — taxing exactly the honesty the ledger depends on. Heredoc bodies handed to an
    interpreter are NOT stripped: there the body is the instruction.
    """
    if _INTERPRETER_RE.search(cmd):
        return cmd
    return _MESSAGE_PAYLOAD_RE.sub(r"\1 <payload>", _HEREDOC_RE.sub("<heredoc>", cmd))


def _judged_segments(cmd: str) -> list[str]:
    """The statements of a payload-stripped command, each judged on its own (RC-525).

    `iter_command_segments` is the ONE splitter; it drops heredoc bodies as data. When the
    command hands a heredoc to an interpreter, `_strip_command_payloads` has already kept the
    body because there the body IS the instruction (RC-253), so its lines are segmented too.
    Falls back to the whole command, which fails CLOSED: one big segment blocks at least as
    much as its parts.
    """
    try:
        segs = [seg for _cwd, seg in iter_command_segments(cmd, "")]
        if _INTERPRETER_RE.search(cmd):
            for line in cmd.splitlines():
                segs.extend(seg for _cwd, seg in iter_command_segments(line, ""))
    except (OSError, ValueError):
        segs = []
    return segs or [cmd]


def _reset_class_violation(seg: str) -> list[str]:
    """The CLASS rule for ONE statement (RC-525): a chain cannot launder a later wipe."""
    if not _RESET_GUARD_RE.search(seg) or _RESET_GUARD_SAFE_RE.search(seg):
        return []
    touched = [p for p in PROTECTED_PATHS + PRODUCT_WIPE_PROTECTED if p in seg]
    bare = not any(tok in seg for tok in (" -- ", ".py", ".html", ".json"))
    if touched or bare:
        return [
            "RESET_GUARD: tree-destructive git "
            f"({'paths: ' + ', '.join(sorted(set(touched))[:4]) if touched else 'bare/whole-tree form'}) "
            "is refused (AGENTS.md § Authority)."
        ]
    return []


def reset_guard_violations(command: str) -> list[str]:
    """Refuse tree-destructive git; the one owner of that question.

    Two clauses, one predicate. The hard forms (every `git reset`, every `git stash` but
    `list`/`show`, `checkout -- <any path>`, `clean -f`, every force push, `--force-with-lease`
    included) refuse on sight, on any target. The class forms (the wider
    reset/restore/checkout--/clean/stash family) refuse when they touch a protected or product
    path or take a bare whole-tree shape, judged per statement so a safe first statement cannot
    launder a later one. No env token or repo file disables it. `git restore --staged`
    (index-only) and `git checkout -b` stay legal.
    """
    cmd = _strip_command_payloads(command or "")
    if _UNIVERSAL_DESTRUCTIVE_RE.search(cmd):
        return [
            "RESET_GUARD: git reset, stash, checkout -- <path>, clean -f and every force push "
            "are refused on any target (AGENTS.md § Authority)."
        ]
    for seg in _judged_segments(cmd):
        hit = _reset_class_violation(seg)
        if hit:
            return hit
    return []


_QUOTED_STRING_RE = re.compile(r"\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'")


def commit_pipe_violations(cmd: str) -> list[str]:
    """RC-234: a `git commit` piped into a filter (tail/head/grep/Out-Null/...) reports
    the FILTER's exit code and truncates hook output — twice this masked a failed landing
    as exit 0 (F401 hidden, t6+t12 slice silently not on HEAD). Commits run UNPIPED;
    long hooks go to a background task whose full output is read back. Escape:
    '# pipe-ok: <reason>' (operator-reviewed). Pipes inside the quoted -m message are
    legal — quoted strings are stripped before the scan."""
    if not cmd or "# pipe-ok:" in cmd:
        return []
    stripped = _QUOTED_STRING_RE.sub("", cmd).replace("||", "&&")
    # SIMPLICITY REHAB 2026-08-24 (T2-6): the ban binds the OBSERVED defect class — a
    # commit piped into an output FILTER whose exit code replaces the commit's
    # (tail/head/cat/tee/grep/findstr/Out-Null/Select-Object were the measured maskers).
    # A pipe into anything else on the segment passes.
    masking_filter = re.compile(
        r"\|\s*(?:tail|head|cat|tee|grep|findstr|Out-Null|Select-Object)\b", re.I)
    for seg in re.split(r"&&|;|\n", stripped):
        if re.search(r"\bgit\s+commit\b", seg, re.I) and masking_filter.search(seg):
            return [
                "PIPE_MASKED_COMMIT: `git commit` piped into a filter: the filter's exit "
                "code replaces the commit's and hook failures vanish. Run the commit "
                "unpiped (a background task for long hooks), then verify with "
                "`git show --stat`. Escape: '# pipe-ok: <reason>'."
            ]
    return []
