"""Front-end hook for operating_process_lock (RC-217).

Runs on PreToolUse (Edit/Write/StrReplace/Bash). RC-471 removed the Stop registration;
stop_block() is retained for manual/test use. Exit 2 BLOCKS.
No env kill-switch: ED_PROCESS_LOCK_GUARD cannot disable this control (RC-450).
2026-08-24 teardown: the role/authority rails (writer_drift_lock, isolated-worktree
boundary, mission gating, GO closeout) are gone with Architecture A — what remains is
process integrity: index parity, LIVE-vs-DISK, destructive-git and piped-commit blocks.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import tools.operating_process_lock as OPL  # noqa: E402
from tools.operator_law_guard import (  # noqa: E402
    _msys_to_windows,
    _tokens,
    iter_command_segments,
    iter_git_invocations,
    normalize_repo,
    repo_root_of,
    shell_executed_part,
)
from tools.pretooluse_guard import classify_path  # noqa: E402

#: Cursor continuum tools that mutate files (RC-226: StrReplace/path were previously ignored).
_EDIT_TOOLS = (
    "Edit",
    "Write",
    "MultiEdit",
    "NotebookEdit",
    "StrReplace",
    "Delete",
)


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


def cross_checkout_edit_violations(tool_input: dict, repo: Path = REPO) -> list[str]:
    """RC-442(a), restored role-free (RC-477): a session running in a LINKED worktree may not
    Edit/Write a file inside the PRIMARY working tree — that is the live/production checkout,
    and endangering it from a side checkout is the exact 2026-08-20 hazard. The 2026-08-24
    teardown removed the role-based form of this rail with Architecture A; this form reads
    only the filesystem topology (which checkout am I, where does the target resolve) and
    names no agent. The primary session editing a linked worktree is not blocked — that is
    the operator-visible direction. Fail-open on unresolvable paths: this rail blocks only
    on an affirmative cross-checkout hit."""
    primary = _primary_worktree_root(repo)
    if primary is None:
        return []
    out: list[str] = []
    for key in _EDIT_TARGET_KEYS:
        raw = tool_input.get(key)
        if not raw or not isinstance(raw, str):
            continue
        try:
            target = Path(raw)
            if not target.is_absolute():
                target = repo / target
            resolved = target.resolve()
            resolved.relative_to(primary.resolve())
        except (OSError, ValueError):
            continue
        out.append(
            f"CROSS_CHECKOUT_EDIT (RC-442/RC-477): this session runs in the linked worktree "
            f"{repo} but targets {resolved} inside the PRIMARY working tree {primary} — the "
            f"live checkout. Edit it from its own session, or hand the change over via "
            f"branch/PR."
        )
    return out


#: Git subcommands that move HEAD, create/re-point/delete a branch, or write history in the
#: checkout they run against. On the production primary these are refused; reads, fetch, the
#: fast-forward-to-origin/main update, and return-to-main are allowed (_prod_forbidden_git_reason).
_PROD_MOVE_SUBCOMMANDS = frozenset({
    "commit", "reset", "rebase", "cherry-pick", "revert", "am",
    "merge", "pull", "checkout", "switch", "branch",
})
_GIT_GLOBAL_WITH_ARG = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace",
                                  "--super-prefix", "--exec-path"})


def git_subcommand(cmd: str) -> tuple[str, list[str]]:
    """`(subcommand, its args)` for one git invocation — `("", [])` when there is no git call.

    Stripping `git` and its GLOBAL options is the fiddly half: `-C <path>` and friends take a
    SEPARATE value, so "the first non-flag token" reads that PATH as the subcommand. Extracted
    from `_prod_forbidden_git_reason` (RC-512) so a second caller asking a different question
    of the same syntax reuses this instead of re-deriving it — ONE FAUCET.
    """
    toks = [t.strip("\"'") for t in _tokens(shell_executed_part(cmd or ""))]
    gi = next((i for i, t in enumerate(toks)
               if Path(t).name.lower() in ("git", "git.exe")), -1)
    if gi < 0:
        return "", []
    rest = toks[gi + 1:]
    i = 0
    while i < len(rest):                 # skip git GLOBAL options up to the subcommand
        t = rest[i]
        if any(t.startswith(p + "=") for p in _GIT_GLOBAL_WITH_ARG):
            i += 1
        elif t in _GIT_GLOBAL_WITH_ARG:
            i += 2                       # option + its separate value (e.g. `-C <path>`)
        elif t.startswith("-"):
            i += 1                       # -P/--no-pager/--paginate/--bare/other no-arg globals
        else:
            break
    if i >= len(rest):
        return "", []                    # bare `git` with no subcommand
    return rest[i], rest[i + 1:]


def git_segment_mutates_checkout(seg: str) -> bool:
    """Does this git segment MATERIALLY CHANGE the checkout it targets?

    A different question from `_prod_forbidden_git_reason`, which asks whether an operation is
    forbidden ON PRODUCTION and so answers None for `git checkout main` and
    `git merge --ff-only origin/main` — both sanctioned there, and both of which still rewrite
    a working tree. RC-512 needs the material question: a session that ran
    `git -C <worktree> merge --ff-only origin/main` changed that worktree whether or not the
    operation was permitted, so that worktree must take part in adjudicating the turn.

    Both answers come from the SAME `_PROD_MOVE_SUBCOMMANDS` roster and the same parser above;
    only the policy layered on top differs.
    """
    sub, _args = git_subcommand(seg)
    return bool(sub) and sub in _PROD_MOVE_SUBCOMMANDS


def _prod_forbidden_git_reason(cmd: str) -> str | None:
    """For a git command already known to TARGET the production primary, return WHY it is
    forbidden there, or None if it is an allowed production operation. Parses one git
    invocation: strip `git` + global options, then classify the subcommand and its args.
    ALLOWED on production: reads/fetch; `git merge|pull --ff-only origin/main` (the
    merge-then-fast-forward update, invariant #5); `git checkout|switch main` (return to main);
    `git checkout -- <path>` file-restore (left to the destructive-git rail)."""
    sub, args = git_subcommand(cmd)
    if not sub:
        return None
    if sub not in _PROD_MOVE_SUBCOMMANDS:
        return None                      # status/log/diff/show/add/fetch/worktree/stash/... allowed
    if sub in ("checkout", "switch"):
        if "--" in args:
            return None                  # file-restore, not a branch move
        creates = any(a in ("-b", "-B", "-c", "-C") for a in args)
        refs = [a for a in args if not a.startswith("-")]
        if not creates and refs == ["main"]:
            return None                  # return-to-main recovery is sanctioned
        if creates:
            return f"`git {sub} -b` creates/moves onto a new branch"
        return f"`git {sub} {refs[0] if refs else ''}`".rstrip() + " moves the checkout off main"
    if sub in ("merge", "pull"):
        ff = "--ff-only" in args
        refs = [a for a in args if not a.startswith("-")]
        if ff and refs in ([], ["origin/main"], ["origin", "main"]):
            return None                  # the fast-forward-to-origin/main production update
        return f"`git {sub}` (only `--ff-only origin/main` is allowed on production)"
    if sub == "branch":
        mutating = any(a in ("-m", "-M", "-c", "-C", "-d", "-D", "-f", "--force", "--move",
                             "--copy", "--delete", "--edit-description") for a in args)
        creates = any(not a.startswith("-") for a in args)
        return "`git branch` creates/moves/deletes a branch" if (mutating or creates) else None
    return f"`git {sub}` writes history / moves HEAD in the checkout"


def prod_checkout_git_move_violations(cmd: str, payload_cwd: str = "") -> list[str]:
    """PREVENT (not merely detect) an assigned agent MOVING or committing to the PRODUCTION
    checkout (live-checkout invariant #1/#4). The production checkout is the PRIMARY working
    tree of this repo (its `.git` is a directory; linked dev worktrees have a `.git` FILE).

    EVERY git invocation in a chained command is judged independently against the production
    primary: a harmless leading `git status` (or a `git -C <dev-worktree>`) cannot launder a
    later checkout/switch/branch/commit/merge/reset aimed at the primary. A verb that would move
    HEAD off main, create/re-point a branch, or write history in the primary BLOCKs; dev
    worktrees are unconstrained. RC-350 caught this only at the next launch — this refuses it at
    the moment of the command. Not subject-disableable (RC-450)."""
    primary = _primary_worktree_root(REPO) or REPO
    try:
        primary_norm = normalize_repo(primary)
    except (OSError, ValueError):
        return []
    out: list[str] = []
    for target, seg in iter_git_invocations(cmd or "", payload_cwd or ""):
        if not target or target != primary_norm:
            continue                     # this git invocation targets a dev worktree / elsewhere
        reason = _prod_forbidden_git_reason(seg)
        if reason:
            out.append(
                f"PROD_CHECKOUT_LOCK (live-checkout invariant / RC-350): {reason} in the "
                f"PRODUCTION checkout {primary}. That checkout is production ONLY — always "
                f"main == origin/main. Do this in the separate dev worktree and land via PR; "
                f"production updates by fast-forward to origin/main. See "
                f"governance/AGENT_OPERATING_PROCESS_V1.md.")
    return out


def production_checkout_app_edit_violations(tool_input: dict, repo: Path = REPO) -> list[str]:
    """PREVENT an assigned agent EDITING app code in the PRODUCTION checkout (invariant #4).

    The symmetric companion to cross_checkout_edit_violations: that rail stops a LINKED worktree
    reaching INTO the primary; this stops the session that IS the primary from editing product
    code in place. Fires only when this session runs in the production primary
    (`_primary_worktree_root` is None) and the Edit/Write target resolves INSIDE it AND is a
    production path (server.py, *.py, static/*.html|*.js — governance/docs/reports/tests are not
    app code). A dev-worktree file edited from the primary session resolves OUTSIDE the primary
    and is not blocked. Not subject-disableable (RC-450)."""
    if _primary_worktree_root(repo) is not None:
        return []                        # this session is a linked dev worktree — unconstrained
    try:
        primary = repo.resolve()
    except (OSError, ValueError):
        return []
    out: list[str] = []
    for key in _EDIT_TARGET_KEYS:
        raw = tool_input.get(key)
        if not raw or not isinstance(raw, str):
            continue
        try:
            target = Path(raw)
            if not target.is_absolute():
                target = repo / target
            resolved = target.resolve()
            resolved.relative_to(primary)    # must be inside the production tree
        except (OSError, ValueError):
            continue
        if classify_path(str(resolved), repo=str(primary)).production:
            out.append(
                f"PROD_CHECKOUT_APP_EDIT (live-checkout invariant): {resolved} is app code in the "
                f"PRODUCTION checkout {primary}. Development does not edit the live checkout — make "
                f"the change in the separate dev worktree and land via PR. "
                f"See governance/AGENT_OPERATING_PROCESS_V1.md."
            )
    return out


#: A shell redirect destination — `> file` / `>> file` / `N> file` (the path after the operator);
#: `2>&1`-style fd dups don't match (their "path" would start with `&`). The universal
#: source-write ban (operator_law_guard) covers `> *.py` repo-wide but is .py-only; extracting
#: the redirect destination here lets the caller close the static/*.html|*.js gap in production.
_REDIRECT_DEST_RE = re.compile(r'(?:^|[^0-9&>])[0-9]*>>?\|?\s*("[^"]+"|\'[^\']+\'|[^\s;|&<>]+)')

#: Forms that rewrite TRACKED files without naming them on the command line: a patch decides
#: what it touches, and `git checkout <rev> -- <path>` / `git restore` write from an object.
#: `prod_checkout_git_move_violations` deliberately returns None for the `--` file-restore form
#: (it judges branch moves), so these were reachable by every rail.
_TREE_WRITE_RE = re.compile(
    r"(?i)\b(git\s+apply|git\s+checkout(?=[^|;&]*\s--\s)|git\s+restore|"
    r"git\s+stash\s+(?:pop|apply)|patch\s+-[pi]\d?|patch\s+--\w+)")


def _shell_write_dest_paths(seg: str) -> list[str]:
    """Destination file operand(s) a shell segment WRITES: a `>` / `>>` redirect on ANY command
    (e.g. `printf x > static/index.html`, `echo x > static/app.js`), PLUS the material
    file-mutating verbs cp/mv/install/rsync/ln/tee/sed -i/perl -i/truncate/dd of=. The caller
    filters to app code inside the production primary, so a non-app operand (a sed script, a
    redirect to a .log) is harmlessly ignored. Heredocs and -c payloads stay with their
    universal source-write bans in operator_law_guard."""
    dests: list[str] = [m.group(1).strip("\"'") for m in _REDIRECT_DEST_RE.finditer(seg)]
    toks = [t.strip("\"'") for t in _tokens(seg)]
    i = 0
    while i < len(toks):
        t = toks[i]
        name = Path(t).name.lower().removesuffix(".exe")
        if ("=" in t and not t.startswith("-")) or name in (
                "env", "time", "nice", "sudo", "xargs", "nohup", "stdbuf"):
            i += 1
            continue
        break
    if i >= len(toks):
        return dests
    verb = Path(toks[i]).name.lower().removesuffix(".exe")
    args = toks[i + 1:]
    positionals = [a for a in args if not a.startswith("-")]
    if verb in ("cp", "mv", "install", "rsync", "ln"):
        dests += positionals[-1:]                            # DEST is the last operand; sources are reads
    elif verb in ("tee", "truncate"):
        dests += positionals
    elif verb in ("sed", "gsed", "perl"):
        # in-place: -i / -i.bak / a combined short flag carrying 'i' (perl -pi, sed -ni) / --in-place
        if any((a.startswith("-") and not a.startswith("--") and "i" in a)
               or a == "--in-place" or a.startswith("--in-place=") for a in args):
            dests += positionals                             # in-place edit of every file operand
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
        dests += [t for t in args[idx + 1:] if not t.startswith("-")]
        break
    # PowerShell's write cmdlets are DELIBERATELY not enumerated here. operator_law_guard's
    # _PS_WRITE_BAD already bans Set-Content/Add-Content/Out-File/Copy-Item/Move-Item against a
    # production-suffix destination universally — MEASURED: `Set-Content server.py 'x=1'` blocks
    # today with no mission row and no help from this table. A second PowerShell pattern here
    # would be a second producer of one question (ONE FAUCET). Its residual gap is a destination
    # built from a bare `$variable`, which no static table closes; that is a limit of the ban,
    # not something a duplicate here would fix.
    return dests


def _shell_rewrites_tracked_tree(seg: str) -> str | None:
    """The verb, when a segment rewrites tracked files WITHOUT naming them.

    Deliberately separate from `_shell_write_dest_paths` and deliberately adjacent to it: those
    forms have a destination operand to extract, and these do not. `git apply x.patch` and
    `patch -p1 < x.patch` rewrite whatever the patch says; `git checkout <rev> -- path` and
    `git restore` rewrite from an object. Returning a path list for them would be a fiction, so
    this returns the matched verb and the caller reports a tree write.

    MEASURED on 334c5daf: every form here passed the whole PreToolUse chain, including under
    the strictest existing rail with cwd set to the production primary.
    """
    m = _TREE_WRITE_RE.search(seg)
    return m.group(0) if m else None


def _shell_write_targets(cmd: str, payload_cwd: str = "", base_root: Path | None = None):
    """Every resolved destination a shell command writes, cwd tracked across `cd` in a chain.

    Extracted from `production_checkout_shell_app_write_violations` so the resolve-and-join
    loop exists ONCE (ONE FAUCET). The production-checkout rail keeps its own
    `relative_to(primary)` narrowing; the mission latch applies a different narrowing to the
    same stream. Neither re-derives how a shell command names a destination.
    """
    root = str(base_root) if base_root else str(REPO)
    for cwd, seg in iter_command_segments(cmd or "", payload_cwd or ""):
        base = _msys_to_windows(cwd) if cwd else root
        for dest in _shell_write_dest_paths(seg):
            try:
                p = Path(_msys_to_windows(dest))
                if not p.is_absolute():
                    p = Path(base) / p
                yield p.resolve()
            except (OSError, ValueError):
                continue


def _owner_checkout(dest: Path) -> str:
    """The checkout that owns `dest`, tolerating a destination that does not exist YET.

    `repo_root_of` answers this question and stays the only implementation of it, but it
    returns "" for a nonexistent path — and a write destination is very often a file being
    CREATED. MEASURED: `curl -o static/app.js` and `--in-place static/app.js` resolved to no
    owner and went ungoverned for exactly that reason, while `static/index.html` resolved
    fine. Walking up to the nearest ancestor that does exist asks the same question about the
    same tree.
    """
    cur = dest
    for _ in range(64):
        owner = repo_root_of(str(cur))
        if owner:
            return owner
        if cur.parent == cur:
            break
        cur = cur.parent
    return ""


def mission_shell_write_violations(cmd: str, payload_cwd: str = "") -> list[str]:
    """RC-498: a SHELL mutation of production code needs the same durable mission state an
    Edit/Write does. Otherwise the latch is a door with the window left open.

    MEASURED on 334c5daf in the dev worktree, every one of these returned exit 0 with no row
    anywhere: `sed -i 's/a/b/' server.py`, `cp /tmp/x.py server.py`, `mv /tmp/x.py server.py`,
    `echo x | tee server.py`, `truncate -s 0 server.py`, `git apply /tmp/x.patch`, and a repo
    tool invoked as `... --write server.py`. The existing shell rail only fires when the
    destination lands inside the PRODUCTION primary checkout, so ordinary development mutation
    was entirely ungoverned by it — correctly, since that rail answers a different question.
    """
    from tools.mission_latch import has_active_mission

    # RC-501: BOTH questions — "is this production?" and "is there a mission?" — are resolved
    # from the checkout that OWNS THE DESTINATION, never from this guard file's own repo.
    # MEASURED against the previous version, whose `classify_path(..., repo=REPO)` judged any
    # destination outside the guard's checkout to be a foreign tree: `sed -i server.py`,
    # `cp x server.py`, `mv x server.py` and `tee server.py` ALL passed against a repository
    # with no mission row at all. A guard that only governs the tree it happens to live in does
    # not govern the tree the work happens in, which is the whole point of a linked worktree.
    cwd_root = repo_root_of(_msys_to_windows(payload_cwd)) if payload_cwd else ""
    base = cwd_root or payload_cwd or str(REPO)

    out: list[str] = []
    seen: set[str] = set()
    for resolved in _shell_write_targets(cmd, payload_cwd, base_root=base):
        owner = _owner_checkout(resolved)
        if not owner:
            continue                       # not inside any checkout: no ledger governs it
        facts = classify_path(str(resolved), repo=owner)
        if not (facts.governed and facts.production) or facts.rel in seen:
            continue
        if has_active_mission(repo=owner):
            continue                       # that checkout is executing a mission: allowed
        seen.add(facts.rel)
        out.append(
            f"FIND_FIX_MISSION_LATCH (RC-498/RC-501): this command writes production code "
            f"({facts.rel}) in {owner}, which has no single active mission. Open ONE row for "
            f"the session's mission in that checkout's governance/root_cause_log.md first — "
            f"see the AGENTS.md Find -> Fix law. Editing governance/, tests/, docs/ and "
            f"reports/ is never gated.")

    # git apply / patch / restore name no destination, so they are judged against the checkout
    # the command RUNS IN — the tree they would rewrite.
    if not has_active_mission(repo=cwd_root or None):
        for _seg_cwd, seg in iter_command_segments(cmd or "", payload_cwd or ""):
            verb = _shell_rewrites_tracked_tree(seg)
            if verb and verb not in seen:
                seen.add(verb)
                out.append(
                    f"FIND_FIX_MISSION_LATCH (RC-498/RC-501): `{verb}` rewrites tracked files "
                    f"from a patch or a git object without naming them, and this checkout has "
                    f"no single active mission. Open ONE row for the session's mission first.")
    return out


def production_checkout_shell_app_write_violations(cmd: str, payload_cwd: str = "") -> list[str]:
    """PREVENT a materially-equivalent SHELL edit to app code in the PRODUCTION checkout — the
    Bash companion to production_checkout_app_edit_violations (Edit/Write) and to the universal
    shell source-write bans (redirect/heredoc/-c payload in operator_law_guard). For EACH segment
    of a chained command (cwd tracked, so a leading `cd` cannot mislocate a later write), blocks
    a `>`/`>>` redirect or cp/mv/install/tee/sed -i/perl -i/truncate/dd whose destination resolves
    to a production app file (server.py, *.py, static/*.html|*.js, ...) INSIDE the production
    primary — whichever session runs it. This closes the redirect-to-static gap the universal
    .py-only redirect ban misses. Dev-worktree paths resolve outside and stay free. Not
    subject-disableable (RC-450)."""
    primary = _primary_worktree_root(REPO) or REPO
    try:
        primary_res = primary.resolve()
    except (OSError, ValueError):
        return []
    out: list[str] = []
    # ONE resolve loop, shared with the RC-498 mission latch; only the narrowing below is
    # this rail's own — the destination must land INSIDE the production primary.
    for resolved in _shell_write_targets(cmd, payload_cwd, base_root=primary_res):
        try:
            resolved.relative_to(primary_res)
        except ValueError:
            continue
        if classify_path(str(resolved), repo=str(primary_res)).production:
            out.append(
                    f"PROD_CHECKOUT_APP_EDIT (shell, live-checkout invariant): a shell command "
                    f"writes {resolved} — app code in the PRODUCTION checkout {primary}. "
                    f"Development does not modify the live checkout by ANY means; make the change "
                    f"in the separate dev worktree and land via PR. "
                    f"See governance/AGENT_OPERATING_PROCESS_V1.md.")
    return out


def pretooluse_block(tool: str, tool_input: dict, payload_cwd: str = "") -> list[str]:
    out: list[str] = []
    if tool in _EDIT_TOOLS:
        out.extend(cross_checkout_edit_violations(tool_input))
        # Live-checkout invariant #4: the primary SESSION may not edit app code in the production
        # checkout (the symmetric companion to the linked->primary rail above).
        out.extend(production_checkout_app_edit_violations(tool_input))
    if tool in ("Bash", "PowerShell", "Shell"):
        cmd = tool_input.get("command") or ""
        if re.search(r"\bgit\s+commit\b", cmd, re.I):
            out.extend(OPL.commit_violations())
            # RC-234: piped commits mask hook failures as exit 0 — block BEFORE it runs.
            out.extend(OPL.commit_pipe_violations(cmd))
        # LOCK-2 (RC-231): the tree-destructive git CLASS blocks BEFORE the tree is touched —
        # three 2026-08-03 wipes used soft forms the old --hard-literal ban never matched.
        out.extend(OPL.reset_guard_violations(cmd))
        # Live-checkout invariant #1/#4: PREVENT a git branch-move/commit/reset/merge that
        # TARGETS the production checkout, at the moment of the command (not just at next launch).
        # Every git invocation in the chain is judged on its own — no laundering by a harmless first.
        out.extend(prod_checkout_git_move_violations(cmd, payload_cwd))
        # Live-checkout invariant #4: a materially-equivalent SHELL write to production app code
        # (cp/mv/sed -i/tee/...) is blocked too, not only Edit/Write tool calls.
        out.extend(production_checkout_shell_app_write_violations(cmd, payload_cwd))
        # RC-498 Find -> Fix latch: the same durable-mission requirement the Edit/Write seam
        # applies, at the shell seam — otherwise the latch is a door with the window left open.
        out.extend(mission_shell_write_violations(cmd, payload_cwd))
        # RC-517: a heavy verification wave may not be launched beside another one. The
        # process inventory (psutil) is consulted only when the command itself is heavy, so
        # ordinary Bash calls pay nothing.
        out.extend(OPL.competing_heavy_verification_violations(shell_executed_part(cmd)))
    return out


def stop_block(payload: dict) -> list[str]:
    out: list[str] = []
    transcript = payload.get("transcript_path") or ""
    text = ""
    if transcript:
        try:
            from tools.operator_law_guard import last_assistant_text
            text = last_assistant_text(transcript) or ""
        except Exception:  # institutional-swallow-ok: guard must fail-open on transcript read, never hang a Stop; index/DISK checks below still run
            pass
    if text:
        out.extend(OPL.completion_claim_violations(text))
    mism = OPL.index_worktree_mismatches()
    if mism:
        out.append(
            "AUDITOR WINDOW: index≠WT on enforcement paths — re-prove before ending turn: "
            + "; ".join(mism[:5])
        )
    disk = OPL.live_collect_disk_only()
    if disk:
        out.append(f"LIVE vs DISK: {disk}")
    return out


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    if payload.get("stop_hook_active") is True:
        return 0

    tool = payload.get("tool_name") or ""
    ti = payload.get("tool_input") or {}
    payload_cwd = str(payload.get("cwd") or "")

    if tool in _EDIT_TOOLS or tool in ("Bash", "PowerShell", "Shell"):
        bad = pretooluse_block(tool, ti, payload_cwd)
    elif not tool or tool == "Stop":
        bad = stop_block(payload)
    else:
        return 0

    if not bad:
        return 0
    sys.stderr.write(
        "BLOCKED by operating process lock (RC-217 / AGENT_OPERATING_PROCESS_V1).\n\n"
        + "".join(f"  {b}\n" for b in bad)
        + "\nSee governance/AGENT_OPERATING_PROCESS_V1.md, "
        + "tools/operating_process_lock.py --measure\n"
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
