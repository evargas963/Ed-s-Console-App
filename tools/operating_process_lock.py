"""Operating-process mechanical lock: two predicates, one owner each, consumed by
tools/process_lock_guard.py at PreToolUse.

  (a) tree-destructive git — THE one owner of that class, universal hard forms included;
  (b) pipe-masked commits.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# The ONE shell reader (tools/shell_parse.py, stdlib-only): the rules below judge each git
# statement a command runs on its own words.
from tools.shell_parse import git_subcommand, read  # noqa: E402

#: Wipe-protected paths (the reset guard's reach): the one writer and the guards.
PROTECTED_PATHS: tuple[str, ...] = (
    "db.py",
    "tools/hook_chain.py",
    "tools/pretooluse_guard.py",
    "tools/operator_law_guard.py",
    "tools/operating_process_lock.py",
    "tools/process_lock_guard.py",
)

#: The reset guard's class: tree-destructive git, not just `reset --hard`. The hard forms (reset --hard,
#: checkout -- <any path>, clean -f, push --force without lease, short -f included, and every git
#: stash but `stash list`) are `_hard` below and refuse on any target. The class rule covers the
#: reset/restore/checkout--/clean
#: family: a statement running a destructive verb AND touching a protected/product path (or a
#: bare, whole-tree form) is refused at PreToolUse in every session wired to process_lock_guard.
#: git's global options (`git -C <other> ...`) are skipped; the class rule is judged per
#: statement, so a safe first statement exempts nothing chained after it; `git reset --soft`
#: (HEAD only) is safe.

#: The product paths that must never be wiped; with PROTECTED_PATHS, the class rule's whole reach.
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


def _hard(sub: str, args: list[str]) -> bool:
    """A git subcommand that discards work whatever it names."""
    return (
        (sub == "reset" and "--hard" in args)
        or (sub == "checkout" and args[:1] == ["--"] and len(args) > 1)
        or (sub == "clean" and any(re.match(r"-[a-z]*f", a, re.I) for a in args))
        or (sub == "stash" and args[:1] != ["list"])
        or (
            sub == "push"
            and any(
                (a.startswith("--force") and not a.startswith("--force-with-lease"))
                or re.fullmatch(r"-[a-zA-Z]*f[a-zA-Z]*", a)
                for a in args
            )
        )
    )


def _safe(sub: str, args: list[str]) -> bool:
    """A form of the class that cannot reach the index or the worktree, or only reads."""
    first = args[0] if args else ""
    return (
        (sub == "reset" and first == "--soft")
        or (sub == "restore" and first == "--staged" and "--worktree" not in args)
        or (sub == "checkout" and first == "-b")
        or (sub == "clean" and bool(re.match(r"-\S*n", first)))
    )


def _reset_class_violation(words: tuple[str, ...]) -> list[str]:
    """The CLASS rule for ONE statement: a chain cannot launder a later wipe."""
    sub, args = git_subcommand(words)
    if not (
        sub in ("reset", "restore", "clean") or (sub == "checkout" and "--" in args[:-1])
    ) or _safe(sub, args):
        return []
    seg = " ".join(words)
    touched = [p for p in PROTECTED_PATHS + PRODUCT_WIPE_PROTECTED if p in seg]
    bare = not any(tok in seg for tok in (" -- ", ".py", ".html", ".json"))
    if touched or bare:
        return [
            "RESET_GUARD: tree-destructive git "
            f"({'paths: ' + ', '.join(sorted(set(touched))[:4]) if touched else 'bare/whole-tree form'}) "
            "can discard operator work. No setting or file here can allow it."
        ]
    return []


def reset_guard_violations(command: str, powershell: bool = False) -> list[str]:
    """The reset guard: BLOCK tree-destructive git — the ONE owner of that question.

    Two clauses, one predicate. The HARD forms (`reset --hard`, `checkout -- <any path>`,
    `clean -f`, `push --force`/`-f`, every `stash` but `stash list`) discard work whatever they
    name, so they refuse on sight, on ANY target (host-wide; the checkout in front of the command
    is irrelevant). The CLASS forms (the wider reset/restore/checkout--/clean family) refuse when
    they touch a protected/product path or take a bare whole-tree shape, judged PER STATEMENT so a
    safe first statement cannot launder a later one.

    Not subject-disableable: no env token or repo file can authorize a wipe.
    `git reset --soft`, `git restore --staged` (index-only), `git stash list`,
    `git checkout -b` and `push --force-with-lease` stay legal. Text a command only carries (a
    commit message, a heredoc nothing runs) is not a statement.
    """
    gits = [st.words for st in read(command or "", powershell=powershell) if st.program == "git"]
    if any(_hard(*git_subcommand(words)) for words in gits):
        return [
            "RESET_GUARD: destructive git can discard operator work — "
            "reset --hard / checkout -- <path> / clean -f / push --force or -f / stash are refused on "
            "any target (`--force-with-lease` is the safe form). Hand it to the operator. No "
            "setting or file here can allow it."
        ]
    for words in gits:
        hit = _reset_class_violation(words)
        if hit:
            return hit
    return []


#: the output filters whose exit code replaces a commit's; a pipe into anything else passes
_MASKING_FILTERS = frozenset(
    {"tail", "head", "cat", "tee", "grep", "findstr", "out-null", "select-object"}
)


def commit_pipe_violations(cmd: str, powershell: bool = False) -> list[str]:
    """A `git commit` piped into a filter (tail/head/grep/Out-Null/...) reports
    the FILTER's exit code and truncates hook output, so a failed commit reads as exit 0.
    Commits run UNPIPED;
    long hooks go to a background task whose full output is read back. Escape:
    '# pipe-ok: <reason>' (operator-reviewed). A `|` inside a quoted -m message is not a pipe."""
    if not cmd or "# pipe-ok:" in cmd:
        return []
    for st in read(cmd, powershell=powershell):
        up = st.upstream if st.program in _MASKING_FILTERS else None
        while up is not None and git_subcommand(up.words)[0] != "commit":
            up = up.upstream
        if up is not None:
            return [
                "PIPE_MASKED_COMMIT: `git commit` piped into a filter — the filter's exit "
                "code replaces the commit's and hook failures vanish. Run the "
                "commit UNPIPED (background task for long hooks), then verify via "
                "`git show --stat`. Escape: '# pipe-ok: <reason>'."
            ]
    return []
