"""PreToolUse guard for the two things git cannot refuse by itself.

  * LIVE-CHECKOUT PROTECTION: the production primary (`EdWebConsole`, `.git` a directory)
    is `main == origin/main` and never edited in place. An Edit/Write of app code inside it,
    a shell write (`cp`/`sed -i`/`tee`/redirect) into it, a linked worktree reaching into it,
    and any git verb that moves it off main are refused at the moment of the command.
  * MAIN REF: main is the branch the production checkout runs, and every checkout of the
    repository shares it, so a git command that writes `refs/heads/main` is refused from ANY
    checkout (`update-ref`, `branch -f/-d/-D/-m/-M/-c/-C` naming main, a fetch refspec into
    main, a local `push . X:main`). main moves only by a PR merged on GitHub, then
    `git pull --ff-only` in production. A push to GitHub's main is the operator's
    (operator_yes_guard).
  * TREE-DESTRUCTIVE GIT (`operating_process_lock.reset_guard_violations`, the ONE owner):
    `reset --hard`, `checkout -- <path>`, `clean -f`, `push --force` and every `stash` but
    `stash list` on any target, and the reset/restore class on product paths.
  * PIPED COMMITS: `git commit | tail` reports the filter's exit code and hides a
    failed hook; refused before it runs.

Exit 2 BLOCKS. No env kill-switch. No Stop path. Reads nothing but the payload.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

import tools.operating_process_lock as OPL  # noqa: E402
from tools.shell_parse import (  # noqa: E402 — the ONE shell reader
    Statement,
    _join_dir,
    git_repo,
    git_subcommand,
    normalize_repo,
    read,
)
from tools.pretooluse_guard import checkout_path, production_path  # noqa: E402
from tools.hook_chain import BASH_TOOLS, MUTATING_TOOLS  # noqa: E402 — the ONE roster of each class

#: The file-mutating tool class is decided ONCE (tools.hook_chain.MUTATING_TOOLS, Cursor's
#: StrReplace/Delete included) and imported here; no private copy.
_EDIT_TOOLS = MUTATING_TOOLS


#: Keys across the two continua that carry an edit target path.
_EDIT_TARGET_KEYS = ("file_path", "notebook_path", "path")


def _primary_worktree_root(repo: Path) -> Path | None:
    """The PRIMARY working tree root when `repo` is a LINKED worktree; None when `repo`
    IS the primary (its .git is a directory) or the layout is unreadable.

    Pure file logic, no subprocess: a linked worktree's `.git` is a FILE reading
    `gitdir: <primary>/.git/worktrees/<name>`; the primary root is the path above `.git`.
    """
    dotgit = repo / ".git"
    if not dotgit.is_file():
        return None
    try:
        text = dotgit.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(r"^gitdir:\s*(.+?)\s*$", text, re.M)
    if not m:
        return None
    gitdir = Path(m.group(1))
    # <primary>/.git/worktrees/<name> -> <primary>
    for parent in gitdir.parents:
        if parent.name == ".git":
            return parent.parent
    return None


#: Git subcommands that move HEAD, create/re-point/delete a branch, or write history in the
#: checkout they run against. On the production primary these are refused; reads, fetch, the
#: fast-forward-to-origin/main update, and return-to-main are allowed (_prod_forbidden_git_reason).
_PROD_MOVE_SUBCOMMANDS = frozenset(
    {
        "commit",
        "reset",
        "rebase",
        "cherry-pick",
        "revert",
        "am",
        "merge",
        "pull",
        "checkout",
        "switch",
        "branch",
    }
)
#: `git branch` listings that read, aimed at production: `--list` (`-l`) and `--contains`
_BRANCH_LISTING = frozenset({"-l", "--list", "--contains"})


def _prod_forbidden_git_reason(words: tuple[str, ...]) -> str | None:
    """For a git statement already known to TARGET the production primary, return WHY it is
    forbidden there, or None if it is an allowed production operation (its subcommand and
    arguments classified). ALLOWED on production: reads/fetch; `git merge|pull --ff-only
    origin/main` (the merge-then-fast-forward update, invariant #5); `git checkout|switch main`
    (return to main); `git checkout -- <path>` file-restore (left to the destructive-git rail)."""
    sub, args = git_subcommand(words)
    if not sub:
        return None
    if sub not in _PROD_MOVE_SUBCOMMANDS:
        return None  # status/log/diff/show/add/fetch/worktree/stash/... allowed
    if sub in ("checkout", "switch"):
        if "--" in args:
            return None  # file-restore, not a branch move
        creates = any(a in ("-b", "-B", "-c", "-C") for a in args)
        refs = [a for a in args if not a.startswith("-")]
        if not creates and refs == ["main"]:
            return None  # return-to-main recovery is sanctioned
        if creates:
            return f"`git {sub} -b` creates/moves onto a new branch"
        return f"`git {sub} {refs[0] if refs else ''}`".rstrip() + " moves the checkout off main"
    if sub in ("merge", "pull"):
        ff = "--ff-only" in args
        refs = [a for a in args if not a.startswith("-")]
        if ff and refs in ([], ["origin/main"], ["origin", "main"]):
            return None  # the fast-forward-to-origin/main production update
        return f"`git {sub}` (only `--ff-only origin/main` is allowed on production)"
    if sub == "branch":
        mutating = any(
            a
            in (
                "-m",
                "-M",
                "-c",
                "-C",
                "-d",
                "-D",
                "-f",
                "--force",
                "--move",
                "--copy",
                "--delete",
                "--edit-description",
            )
            for a in args
        )
        lists = any(
            a.split("=")[0] in _BRANCH_LISTING for a in args
        )  # a pattern or a commit, not a name
        creates = not lists and any(not a.startswith("-") for a in args)
        return "`git branch` creates/moves/deletes a branch" if (mutating or creates) else None
    return f"`git {sub}` writes history / moves HEAD in the checkout"


def prod_checkout_git_move_violations(statements: list[Statement]) -> list[str]:
    """PREVENT (not merely detect) an assigned agent MOVING or committing to the PRODUCTION
    checkout (live-checkout invariant #1/#4). The production checkout is the PRIMARY working
    tree of this repo (its `.git` is a directory; linked dev worktrees have a `.git` FILE).

    EVERY git invocation in a chained command is judged independently against the production
    primary: a harmless leading `git status` (or a `git -C <dev-worktree>`) cannot launder a
    later checkout/switch/branch/commit/merge/reset aimed at the primary. A verb that would move
    HEAD off main, create/re-point a branch, or write history in the primary BLOCKs; dev
    worktrees are unconstrained. Refused at the moment of the command. Not subject-disableable."""
    primary = _primary_worktree_root(REPO) or REPO
    primary_norm = normalize_repo(primary)
    out: list[str] = []
    for st in statements:
        reason = _prod_forbidden_git_reason(st.words)
        if reason and git_repo(st) == primary_norm:  # a git aimed at a dev worktree is not refused
            out.append(
                f"PROD_CHECKOUT_LOCK (live-checkout invariant): {reason} in the "
                f"PRODUCTION checkout {primary}. That checkout is production ONLY — always "
                f"main == origin/main. Do this in the separate dev worktree and land via PR; "
                f"production updates by fast-forward to origin/main. See "
                f"AGENTS.md."
            )
    return out


_MAIN_REFS = (
    "main",
    "heads/main",
    "refs/heads/main",
)  # git resolves a destination `heads/main` to refs/heads/main
_BRANCH_WRITE_FLAGS = frozenset(
    {"-f", "--force", "-d", "-D", "--delete", "-m", "-M", "--move", "-c", "-C", "--copy"}
)


def _writes_main(words: tuple[str, ...]) -> bool:
    """One git statement writes refs/heads/main."""
    sub, args = git_subcommand(words)
    refs = [a for a in args if not a.startswith("-")]
    if sub == "update-ref":
        return bool(refs) and refs[0] == "refs/heads/main"
    if sub == "branch":
        return any(a in _BRANCH_WRITE_FLAGS for a in args) and any(r in _MAIN_REFS for r in refs)
    if sub in ("fetch", "push"):
        if sub == "push" and refs[:1] != ["."]:
            return False  # a push to a remote: operator_yes_guard's
        return any(r.split(":", 1)[1] in _MAIN_REFS for r in refs[1:] if ":" in r)
    return False


def main_ref_write_violations(statements: list[Statement]) -> list[str]:
    """A git command that writes refs/heads/main, from any checkout: every checkout shares the
    branch the production checkout runs, so the checkout a command runs in cannot protect it."""
    return [
        f"MAIN_REF_LOCK: `{st.text}` writes refs/heads/main, the branch the production "
        f"checkout runs, shared by every checkout. main moves only by a PR merged on GitHub, "
        f"then `git pull --ff-only` in production."
        for st in statements
        if _writes_main(st.words)
    ]


def production_checkout_edit_violations(tool_input: dict, repo: Path = REPO) -> list[str]:
    """An Edit or Write whose target belongs to the production checkout, the live one. From a
    linked worktree: any file inside the production checkout that is not under this worktree's
    own root (a worktree nested at `<primary>/.claude/worktrees/<name>` owns its files). From the
    production checkout itself: its app code (`production_path`). The topology is file logic
    only (`_primary_worktree_root`); a target that cannot be placed raises, and hook_chain refuses
    the event."""
    linked_to = _primary_worktree_root(repo)
    primary = linked_to or repo
    out: list[str] = []
    for key in _EDIT_TARGET_KEYS:
        raw = tool_input.get(key)
        if not raw or not isinstance(raw, str):
            continue
        if linked_to is None:
            resolved = production_path(raw, repo, primary)
        else:
            resolved = checkout_path(raw, repo, primary)
            if resolved is not None and resolved.is_relative_to(repo.resolve()):
                resolved = None
        if resolved is not None:
            out.append(
                f"PROD_CHECKOUT_EDIT: {resolved} belongs to the PRODUCTION checkout {primary}, the "
                f"live one. Make the change in a dev worktree and land it by PR. See AGENTS.md."
            )
    return out


def _shell_write_dest_paths(st: Statement) -> list[str]:
    """Destination file operand(s) a shell statement WRITES: a `>` / `>>` redirect on ANY command
    (e.g. `printf x > static/index.html`, `echo x > static/app.js`), PLUS the material
    file-mutating verbs cp/mv/install/rsync/ln/tee/sed -i/perl -i/truncate/dd of=. The caller
    filters to app code inside the production primary, so a non-app operand (a sed script, a
    redirect to a .log) is harmlessly ignored."""
    dests: list[str] = st.writes
    verb = st.program
    if not verb:
        return dests
    args = list(st.words[1:])
    positionals = [a for a in args if not a.startswith("-")]
    if verb in ("cp", "mv", "install", "rsync", "ln"):
        dests += positionals[-1:]  # DEST is the last operand; sources are reads
    elif verb in ("tee", "truncate"):
        dests += positionals
    elif verb in ("sed", "gsed", "perl"):
        # in-place: -i / -i.bak / a combined short flag carrying 'i' (perl -pi, sed -ni) /
        # --in-place
        if any(
            (a.startswith("-") and not a.startswith("--") and "i" in a)
            or a == "--in-place"
            or a.startswith("--in-place=")
            for a in args
        ):
            dests += positionals  # in-place edit of every file operand
    elif verb == "dd":
        dests += [a[3:] for a in args if a.startswith("of=")]
    elif verb in ("curl", "wget"):
        # a download that lands on a path is a write: curl -o FILE / --output FILE, wget -O FILE
        for flag, nxt in zip(args, args[1:]):
            if flag in ("-o", "--output", "-O", "--output-document"):
                dests.append(nxt)
    elif verb in ("awk", "gawk"):
        if any(a == "inplace" or a.startswith("inplace") for a in args):
            dests += positionals
    # An explicit write-intent flag handed to ANY command — a repo codemod invoked as
    # `python tools/rewrite.py --write server.py`, `ruff check --fix server.py`, a formatter.
    # The operands AFTER the flag are what it rewrites; operands before it (the script being
    # RUN) are reads. LONG FORMS ONLY: a bare `-i` collides with grep/sort/pip, and sed's own
    # in-place flag is handled by its branch above.
    for idx, a in enumerate(args):
        name, _, inline = a.partition("=")
        if name not in ("--write", "--in-place", "--inplace", "--fix", "--apply", "--output"):
            continue
        if inline:
            dests.append(inline)
        dests += [t for t in args[idx + 1 :] if not t.startswith("-")]
        break
    dests += _ps_write_dest_paths(st)
    return dests


#: PowerShell write-cmdlet destination parameter, keyed by cmdlet name (lower-case). Copy-Item
#: and Move-Item read their first positional (the source, `-Path`) and write their SECOND
#: (`-Destination`); Set-Content/Add-Content/Out-File write their only positional (`-Path` /
#: `-FilePath`). A write landing directly in the PRODUCTION checkout never reaches a commit or
#: CI, so this rail is its only guard; in a dev worktree ruff and pytest catch a mangled write
#: once it is committed.
_PS_DEST_PARAM = {
    "set-content": "-path",
    "add-content": "-path",
    "out-file": "-filepath",
    "copy-item": "-destination",
    "move-item": "-destination",
}


def _ps_write_dest_paths(st: Statement) -> list[str]:
    """Destination path a PowerShell write cmdlet targets in one statement, named or positional.

    A documented limit: a destination built from a bare `$variable` (no literal path token) is
    not resolvable by this or any static table."""
    verb = st.program
    dest_flag = _PS_DEST_PARAM.get(verb)
    if not dest_flag:
        return []
    args = list(st.words[1:])
    for i, a in enumerate(args):
        if a.lower() == dest_flag and i + 1 < len(args):
            return [args[i + 1]]
    positionals = [a for a in args if not a.startswith("-")]
    if verb in ("copy-item", "move-item"):
        return positionals[1:2]  # first positional is -Path (the source, a read)
    return positionals[:1]


def production_checkout_shell_app_write_violations(statements: list[Statement]) -> list[str]:
    """PREVENT a materially-equivalent SHELL edit to app code in the PRODUCTION checkout — the
    Bash companion to production_checkout_edit_violations (Edit/Write) and to the universal
    shell source-write bans (redirect/heredoc/-c payload in operator_law_guard). For EACH segment
    of a chained command (cwd tracked, so a leading `cd` cannot mislocate a later write), blocks
    a `>`/`>>` redirect or cp/mv/install/tee/sed -i/perl -i/truncate/dd whose destination resolves
    to a production app file (server.py, *.py, static/*.html|*.js, ...) INSIDE the production
    primary — whichever session runs it. This closes the redirect-to-static gap the universal
    .py-only redirect ban misses. Dev-worktree paths resolve outside and stay free. Not
    subject-disableable."""
    primary = _primary_worktree_root(REPO) or REPO
    out: list[str] = []
    for st in statements:  # each destination against its statement's cwd
        for dest in _shell_write_dest_paths(st):
            resolved = production_path(_join_dir(st.cwd or str(primary), dest), primary, primary)
            if resolved is not None:
                out.append(
                    f"PROD_CHECKOUT_EDIT (shell): a shell command "
                    f"writes {resolved} — app code in the PRODUCTION checkout {primary}. "
                    f"Development does not modify the live checkout by ANY means; make the change "
                    f"in the separate dev worktree and land via PR. "
                    f"See AGENTS.md."
                )
    return out


def pretooluse_block(tool: str, tool_input: dict, payload_cwd: str = "") -> list[str]:
    out: list[str] = []
    if tool in _EDIT_TOOLS:
        out.extend(production_checkout_edit_violations(tool_input))
    if tool in BASH_TOOLS:  # one roster (hook_chain.BASH_TOOLS)
        cmd = tool_input.get("command") or ""
        ps = tool == "PowerShell"
        statements = read(cmd, payload_cwd or "", ps)
        # piped commits mask hook failures as exit 0 — block BEFORE it runs.
        out.extend(OPL.commit_pipe_violations(cmd, ps))
        # the tree-destructive git CLASS, soft forms included, blocks BEFORE the tree is touched.
        out.extend(OPL.reset_guard_violations(cmd, ps))
        # Live-checkout invariant #1/#4: PREVENT a git branch-move/commit/reset/merge that
        # TARGETS the production checkout, at the moment of the command (not just at next launch).
        # Every git invocation in the chain is judged on its own — no laundering by a harmless
        # first.
        out.extend(prod_checkout_git_move_violations(statements))
        out.extend(main_ref_write_violations(statements))
        # Live-checkout invariant #4: a materially-equivalent SHELL write to production app code
        # (cp/mv/sed -i/tee/...) is blocked too, not only Edit/Write tool calls.
        out.extend(production_checkout_shell_app_write_violations(statements))
    return out


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.stderr.write(
            "BLOCKED by operating process lock: the hook payload is not readable "
            "JSON, so the tool call cannot be judged. Unreadable is not clean.\n"
        )
        return 2
    if not isinstance(payload, dict):
        sys.stderr.write("BLOCKED by operating process lock: the hook payload is not an object.\n")
        return 2

    tool = payload.get("tool_name") or ""
    ti = payload.get("tool_input") or {}
    payload_cwd = str(payload.get("cwd") or "")

    if tool in _EDIT_TOOLS or tool in BASH_TOOLS:
        bad = pretooluse_block(tool, ti, payload_cwd)
    else:
        return 0  # no Stop path

    if not bad:
        return 0
    sys.stderr.write(
        "BLOCKED by operating process lock.\n\n"
        + "".join(f"  {b}\n" for b in bad)
        + "\nSee AGENTS.md\n"
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
