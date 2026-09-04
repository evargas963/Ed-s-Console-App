"""ONE Stop process instead of five (SIMPLICITY REHAB, operator full-go 2026-08-24).

MEASURED before this change: the Stop chain spawned five Python interpreters —
stop_guard 632ms + proof_only_guard 459ms + honesty_guard 526ms + operator_law_guard
741ms + process_lock_guard 457ms = 2,815ms per turn end, of which ~2.3s was pure
interpreter startup. This entrypoint imports the SAME five guards and calls their
unmodified main() functions in-process, feeding each the identical payload the harness
would have piped to it. No predicate is weakened, reordered, or skipped: every guard
still runs on every Stop, every guard's stderr still reaches the agent, and a block
from ANY guard still blocks the turn (exit 2), exactly as the five-command chain
behaved. The guards stay independently runnable — this file is wiring, not authority.

Chain members (each file is the lock; this list is the wiring contract the tests pin):
    tools/stop_guard.py
    tools/honesty_guard.py
    tools/operator_law_guard.py
process_lock_guard is deliberately NOT in the Stop chain: its Stop path measured 3.18s
(the bulk of the whole chain) and the dereg landed (PR #187 / RC-471) —
process_lock_guard remains on every PreToolUse, where its process-integrity rails
(cross-checkout protection, destructive/piped git) actually bind.

proof_only_guard was REMOVED from this chain and deleted (RC-504, operator 2026-09-02).
It decided truth and completion by matching words in prose, and that was experimentally
confirmed to false-block: the sentence "rather than tell you again from memory" — a
DISCLAIMER of memory written immediately before running commands — was flagged as citing
memory as evidence, because a substring cannot tell an assertion from a denial. Its
structural half, the transcript readers, moved to tools/operator_law_guard.py, which
already owns turn and session identity. No replacement was built: there is no vocabulary
list, regex escape or successor guard, because the defect was the approach.
"""
from __future__ import annotations

import importlib
import io
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

#: Order preserved from .claude/settings.json's serial chain (process_lock_guard
#: dereg'd from Stop per the docstring; it stays on PreToolUse).
STOP_CHAIN = (
    "tools.stop_guard",
    "tools.honesty_guard",
    "tools.operator_law_guard",
)


def _git(cwd: Path, *args: str) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                           text=True, timeout=15, check=False)
        return (r.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def repo_worktrees() -> set[Path]:
    """Every checkout of THIS repository — the only paths that may hold authority.

    RC-512 trust boundary. Authority is resolved from paths that appear in a hook payload or
    a session transcript, both of which the agent influences. Confining the answer to real
    worktrees of this repo means the worst that can be selected is a different legitimate
    checkout, never a directory prepared with guards of its own.
    """
    out: set[Path] = set()
    for line in _git(REPO, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            try:
                out.add(Path(line[len("worktree "):].strip()).resolve())
            except OSError:
                continue
    out.add(REPO)
    return out


def _member_files(members: tuple[str, ...]) -> list[str]:
    """Repo-relative paths of the rostered guards plus the executor that runs them."""
    out = ["tools/stop_chain.py", "tools/pretooluse_chain.py"]
    for name in members:
        out.append(name.replace(".", "/") + ".py")
    return sorted(set(out))


def uncommitted_guard_files(root: Path, members: tuple[str, ...]) -> list[str]:
    """Rostered guard files with uncommitted changes in `root` — empty means clean.

    Authority may not be handed to a tree whose guards exist only in its working copy. An
    agent that edits a guard would otherwise be judged by that edit on its very next action,
    and a control the subject can rewrite mid-session is not a control (RC-450: subject-
    controlled state cannot authorize around a mandatory one). A COMMITTED guard change is
    fine — that is ordinary development, and it answers to required CI at merge.
    """
    status = _git(root, "status", "--porcelain", "--", *_member_files(members))
    return sorted(line[3:].strip().strip('"') for line in status.splitlines() if len(line) > 3)


def authority_banner(root: Path, source: str, note: str = "") -> str:
    """Which tree judged this event, how it was chosen, and where that tree stands.

    RC-512. A wrong-tree judgement used to be SILENT: the block named a rule but never the
    tree the rule came from, so a stale checkout enforcing a withdrawn rule read as a mystery
    instead of as staleness. This adds no verdict and can block nothing — it only says who
    spoke, and why they were the one asked.
    """
    head = _git(root, "rev-parse", "--short", "HEAD") or "unknown"
    branch = _git(root, "symbolic-ref", "--short", "HEAD") or "detached"
    tail = f" - {note}" if note else ""
    return f"GOVERNANCE AUTHORITY: {root} @ {branch} {head} [{source}]{tail}"


def _enclosing_worktree(target: Path) -> Path | None:
    """The nearest ancestor of `target` that is a worktree of THIS repository.

    A `.git` probe alone would also accept an unrelated repository — a linked worktree's
    `.git` is a FILE and the primary's is a directory, and both shapes exist everywhere — so
    membership is confirmed against `repo_worktrees()` rather than inferred from layout.
    """
    try:
        p = target if target.is_absolute() else (Path.cwd() / target)
        p = p.resolve()
    except OSError:
        return None
    known = repo_worktrees()
    for cand in (p, *p.parents):
        if cand in known:
            return cand
    return None


def _payload(raw_payload: str) -> dict:
    try:
        data = json.loads(raw_payload)
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        return {}
    return data if isinstance(data, dict) else {}


def payload_work_tree(raw_payload: str) -> Path | None:
    """The worktree this tool call TARGETS, or None when the payload names no path.

    RC-512: the tree being changed is the tree whose rules apply. Editing a file in worktree
    X was judged by the guards and the root_cause_log of whatever tree the session started
    in, which is a different question from the one the guards mean to ask.
    """
    tool_input = _payload(raw_payload).get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    for key in ("file_path", "notebook_path", "path"):
        raw = tool_input.get(key)
        if isinstance(raw, str) and raw.strip():
            return _enclosing_worktree(Path(raw))
    return None


#: File-target tools that MODIFY a tree. Only these establish where work occurred.
#:
#: The first cut accepted any `tool_use` carrying a file path, which let a Read, a Glob or a
#: Grep nominate the tree that judges a turn: inspect a file in a stale checkout as the last
#: action and that checkout became the authority. Looking at a file is not working in it.
MUTATING_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})

#: Bash is a mutation channel too, and pretending otherwise was WRONG.
#:
#: This roster once excluded Bash, on the written claim that the repo already refuses shell
#: writes to governed state. That claim is false in this repo and the operator caught it:
#: `tools/operator_law_guard.py` permits heredoc and `-c` writes to `.md`, `.json`, `.jsonl`,
#: `.txt`, `.csv` and `.log`, and names governance-row edits as a legitimate shell-write case.
#: Governance ledgers ARE `.md`. So a session could materially change a worktree entirely
#: through Bash, that tree would never enter the authority set, and Stop fell back to being
#: adjudicated by the launch checkout — the very defect, reachable through the sanctioned path.
#:
#: WHERE a shell command writes is answered by `tools/process_lock_guard.py`, which already
#: owns that question for the production-checkout and mission rails: `_shell_write_targets`
#: (destinations, with `cd` tracked across a chain), `_shell_rewrites_tracked_tree` (the forms
#: that rewrite tracked files WITHOUT naming them) and `git_segment_mutates_checkout` (git
#: subcommands that change a checkout, `-C <path>` resolved). `bash_mutation_targets` composes
#: those. It parses nothing itself, because a second shell parser answering the same question
#: is exactly the duplication this repo removes on sight.
BASH_TOOLS = frozenset({"Bash", "PowerShell"})


def _transcript_lines(path: Path) -> tuple[list[str], str]:
    """EVERY line of the transcript, or an explicit reason it could not be read.

    Read whole, not tailed. A fixed tail was a silent correctness hole twice over: an earlier
    real mutation older than the window vanished, and with it the tree it established, so a
    long session fell back to bootstrap authority precisely when it had the most history to
    lose. And the union across a session (see `session_work_trees`) cannot be built from a
    window at all.

    The cost is bounded by only PARSING lines that could carry a tool call — see the
    `"tool_use"` pre-filter in the caller, which can produce no false negatives because a real
    tool_use record necessarily contains that substring.
    """
    try:
        with path.open("rb") as fh:
            return fh.read().decode("utf-8", errors="replace").splitlines(), ""
    except OSError as exc:
        return [], (
            f"the session transcript at {path} could not be read ({type(exc).__name__}: "
            f"{exc}), so where this session did its work cannot be established")


def bash_mutation_targets(command: str, payload_cwd: str = "") -> tuple[list[str], list[str]]:
    """`(paths a shell command materially writes, reasons a mutation could not be located)`.

    Composition only — every judgement below belongs to `tools/process_lock_guard.py`, which
    already owns "where does this shell command write" for the production-checkout and mission
    rails. Adding a second parser here would put two answers to one question in the tree.

    Three channels, because the existing owner models them as three:
      1. WRITE DESTINATIONS — redirects and the file-mutating verbs, `cd` tracked across a
         chain. This is where the sanctioned `.md`/`.json`/`.jsonl` data writes land, ledgers
         included.
      2. GIT OPERATIONS that change a checkout, with `-C <path>` resolved to its worktree, so
         `git -C <other-worktree> commit` puts THAT tree in the set rather than this one.
      3. TRACKED-TREE REWRITES that name no destination at all (`git apply`, `patch -p1`,
         `git restore`, `git stash pop`). Their target is the working directory in effect.

    A harmless read yields nothing from any of the three, so inspection still establishes no
    authority. Channels 2 and 3 report UNRESOLVED when a mutation is recognised but its tree
    cannot be located: better an explicit refusal than a quiet fallback to whichever checkout
    happens to be running the hook.
    """
    try:
        from tools.operator_law_guard import iter_command_segments, iter_git_invocations
        from tools.process_lock_guard import (
            _shell_rewrites_tracked_tree,
            _shell_write_targets,
            git_segment_mutates_checkout,
        )
    except ImportError as exc:
        # The owner of shell resolution is unavailable, so a shell command's target cannot be
        # established. Reporting "no mutations" here would be the silent fallback this whole
        # resolver exists to remove, so it is reported as unresolved instead.
        return [], [f"shell resolution is unavailable ({type(exc).__name__}: {exc}), so a "
                    f"shell command's target cannot be established"]

    paths: list[str] = []
    unresolved: list[str] = []
    cmd = command or ""

    for dest in _shell_write_targets(cmd, payload_cwd, REPO):
        paths.append(str(dest))

    for target, seg in iter_git_invocations(cmd, payload_cwd):
        if not git_segment_mutates_checkout(seg):
            continue
        if target:
            paths.append(str(target))
        else:
            unresolved.append(
                f"a git operation that materially changes a checkout could not be located: "
                f"{seg.strip()[:120]!r}")

    for cwd, seg in iter_command_segments(cmd, payload_cwd):
        verb = _shell_rewrites_tracked_tree(seg)
        if not verb:
            continue
        base = cwd or payload_cwd
        if base:
            paths.append(str(base))
        else:
            unresolved.append(
                f"`{verb}` rewrites tracked files from a working directory this resolver "
                f"cannot determine: {seg.strip()[:120]!r}")
    return paths, unresolved


def _mutation_targets_in(node, payload_cwd: str = "") -> tuple[list[str], list[str]]:
    """`(paths this record MODIFIED, reasons a mutation could not be located)`.

    Never paths the record merely looked at. Three filters, all load-bearing:

      * a file-target record must be a `tool_use` whose `name` is in `MUTATING_TOOLS`. Without
        the name test a Read in a stale checkout nominates that checkout as the authority,
        which is a one-line way to choose your own judge.
      * a shell record goes to `bash_mutation_targets`, because Bash writes governed `.md`
        state by sanctioned means and pretending otherwise left an untracked channel.
      * it is walked STRUCTURALLY, so assistant prose quoting a path is not a mutation of it.
    """
    found: list[str] = []
    unresolved: list[str] = []
    if isinstance(node, dict):
        tool_input = node.get("input")
        if node.get("type") == "tool_use" and isinstance(tool_input, dict):
            if node.get("name") in MUTATING_TOOLS:
                for key in ("file_path", "notebook_path", "path"):
                    val = tool_input.get(key)
                    if isinstance(val, str) and val.strip():
                        found.append(val)
            elif node.get("name") in BASH_TOOLS:
                command = tool_input.get("command")
                if isinstance(command, str) and command.strip():
                    paths, reasons = bash_mutation_targets(command, payload_cwd)
                    found.extend(paths)
                    unresolved.extend(reasons)
        for value in node.values():
            sub_found, sub_unresolved = _mutation_targets_in(value, payload_cwd)
            found.extend(sub_found)
            unresolved.extend(sub_unresolved)
    elif isinstance(node, list):
        for item in node:
            sub_found, sub_unresolved = _mutation_targets_in(item, payload_cwd)
            found.extend(sub_found)
            unresolved.extend(sub_unresolved)
    return found, unresolved


def session_work_trees(raw_payload: str) -> tuple[tuple[Path, ...], str]:
    """EVERY worktree this session materially modified, or an explicit reason it is unknown.

    Returns `(trees, failure)`. A non-empty `failure` means authority could not be
    established and the caller must refuse the event — never quietly fall back.

    ALL of them, not the last one. Taking the most recent mutation let a session that worked
    in A finish with one harmless write in stale worktree B and hand B the verdict. Work in A
    does not stop having happened because something later happened elsewhere, so every
    materially touched tree is returned and the caller adjudicates all of them.

    The whole transcript is read, because a union cannot be built from a window and because a
    mutation older than any window would otherwise disappear along with the tree it
    established. Lines are pre-filtered on the `"tool_use"` substring purely to avoid parsing
    prose; that can miss nothing, since a real tool_use record contains it by construction.
    """
    payload = _payload(raw_payload)
    raw = payload.get("transcript_path")
    if not isinstance(raw, str) or not raw.strip():
        return (), ""                      # no evidence channel at all — caller says so
    lines, failure = _transcript_lines(Path(raw))
    if failure:
        return (), failure

    session_cwd = payload.get("cwd")
    session_cwd = session_cwd if isinstance(session_cwd, str) else ""
    ordered: list[Path] = []
    unresolved: list[str] = []
    for line in lines:
        if "tool_use" not in line:
            continue
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        candidates, reasons = _mutation_targets_in(record, session_cwd)
        unresolved.extend(reasons)
        for candidate in candidates:
            tree = _enclosing_worktree(Path(candidate))
            if tree is not None and tree not in ordered:
                ordered.append(tree)
    if unresolved:
        # A mutation the session definitely performed, in a tree that cannot be named. Falling
        # back to whichever checkout runs the hook is the defect; refuse instead.
        return (), "; ".join(sorted(set(unresolved))[:5])
    return tuple(ordered), ""


def canonical_authority(raw_payload: str) -> tuple[tuple[Path, ...], str, str]:
    """Who governs this event: `(trees, source, failure)`.

    ONE resolver for both shapes, so there is a single answer to "who judges this" instead of
    a rule for edits and a shrug for everything else:

        payload names a path -> the worktree containing it              work target
        payload names none   -> EVERY worktree this session materially
                                modified, from its own transcript       session record
        no mutations at all  -> none; this tree judges, and says so     bootstrap

    Plural on purpose. A single answer for a session that worked in two trees would mean
    choosing one, and any rule for choosing is a rule an agent can satisfy on purpose.
    """
    tree = payload_work_tree(raw_payload)
    if tree is not None:
        return (tree,), "work target", ""
    trees, failure = session_work_trees(raw_payload)
    if failure:
        return (), "unresolved", failure
    if trees:
        return trees, "session record", ""
    return (), "bootstrap", ""


# RC-512 — GOVERNANCE AUTHORITY, and why the resolvers above exist.
#
# THE DEFECT. `.claude/settings.json` registers the hook as a command RELATIVE to the session
# project directory, and REPO above is derived from this file's own location. So the guards
# that judged an event, and every ledger they read, came from whichever checkout the session
# happened to be launched in — in practice the production APP RUNTIME tree, because that is
# where the desk lives. Being launched somewhere is not a reason to be governed by it.
#
# OBSERVED 2026-09-03: a chain sourced from a production checkout 9 commits behind origin/main
# ran `tools/proof_only_guard.py` — a guard main had already DELETED for false-blocking a
# denial (RC-504) — and it false-blocked a turn whose work was in a different worktree
# entirely. Stale code enforcing a withdrawn rule, and the block never said which tree it came
# from, so it read as a mystery rather than as staleness.
#
# THE RULE, resolved from evidence in BOTH shapes (`canonical_authority`):
#     payload names a path -> the worktree containing it                    work target
#     payload names none   -> EVERY worktree this session MATERIALLY MODIFIED, from its own
#                             transcript, all of them adjudicated           session record
#     no mutations at all  -> none; this tree judges and says so            bootstrap
#     transcript unreadable-> REFUSE, explicitly                            unresolved
#
# The middle line is what makes Stop and every other no-file event answerable. The first cut
# returned None there and the bootstrap judged by default, which is the defect itself.
#
# THREE WAYS THE MIDDLE LINE WAS ITSELF A BYPASS, and what each cost:
#   * it accepted ANY tool_use carrying a path, so a READ in a stale checkout nominated that
#     checkout. Only MUTATING_TOOLS establish work now: looking at a file is not working in it.
#   * it took the MOST RECENT target, so one harmless final write in another worktree replaced
#     the tree where the real work happened. Every materially touched tree is adjudicated now
#     and the worst real verdict wins — earlier work does not stop having happened.
#   * it read a fixed 2 MB tail, so a real mutation older than the window vanished and the
#     session fell back to bootstrap authority silently. The transcript is read whole.
#
# WHAT IT DOES NOT DO. It never decides to skip guards: every path either delegates to real
# worktrees that run the IDENTICAL roster, or runs that roster here. Authority is confined to
# `repo_worktrees()`, so a prepared directory can never be selected. A tree with UNCOMMITTED
# guard files is refused, so an agent cannot edit a guard and be judged by the edit. A delegate
# that crashes or times out BLOCKS. And authority that cannot be established REFUSES the event
# rather than picking a convenient tree.


#: Set on a delegated run so authority hops exactly ONCE and can never loop.
DELEGATED_ENV = "ED_GOVERNANCE_AUTHORITY_DELEGATED"


def _delegate(root: Path, raw_payload: str, members: tuple[str, ...]) -> int:
    """Run the IDENTICAL roster under `root`'s governance and return its verdict.

    The roster travels as argv, so the member list cannot be shortened on the way across and
    `.claude/settings.json` stays the reviewable authority over which guards run. Fail-closed:
    a delegate that crashes, times out, or cannot be spawned returns non-zero, because an
    unmeasurable guard run is not a passing one (RC-57).
    """
    import os

    entry = root / "tools" / "stop_chain.py"
    argv = [f"tools/{name.split('.')[-1]}.py" for name in members]
    env = dict(os.environ)
    env[DELEGATED_ENV] = "1"
    try:
        proc = subprocess.run(
            [sys.executable, str(entry), *argv], cwd=str(root), env=env,
            input=raw_payload, text=True, capture_output=True, timeout=180,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        sys.stderr.write(
            f"GOVERNANCE AUTHORITY: delegation to {root} failed "
            f"({type(exc).__name__}: {exc}); blocking, because a guard run that did not "
            f"happen is not a guard run that passed.\n")
        return 2
    if proc.stdout:
        sys.stdout.write(proc.stdout)
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    return proc.returncode


def _ineligible_reason(root: Path, members: tuple[str, ...]) -> str:
    """Why `root` may not judge for itself — empty when it may."""
    if not (root / "tools" / "stop_chain.py").is_file():
        return f"{root} carries no chain to delegate to"
    dirty = uncommitted_guard_files(root, members)
    if dirty:
        return (f"{root} has UNCOMMITTED guard files ({', '.join(dirty)}); a tree cannot be "
                f"handed authority over its own unreviewed guard edits")
    return ""


def resolve_authority(raw_payload: str, members: tuple[str, ...]) -> tuple[
        tuple[Path, ...], bool, str, str, str]:
    """The whole plan: `(delegate_to, run_here, source, notes, failure)`.

    Separated from the acting so the decision is testable on its own, and so the reason a
    delegation did NOT happen is a value rather than a silence.

    `run_here` is True whenever this tree must judge as well — because it is itself one of the
    materially touched trees, because nothing resolved, or because a resolved tree was refused
    authority. A refused tree is never simply dropped: something always judges for it.
    """
    import os

    if os.environ.get(DELEGATED_ENV) == "1":
        return (), True, "delegated run", "already delegated; this IS the authority", ""

    trees, source, failure = canonical_authority(raw_payload)
    if failure:
        # run_here stays TRUE: refusing to establish authority must not become a way to skip
        # the roster. The members still run and still say what they found; the refusal is an
        # ADDITIONAL block on top of their verdict, never a substitute for asking them.
        return (), True, source, "", failure
    if not trees:
        return (), True, source, "", ""

    delegate_to: list[Path] = []
    notes: list[str] = []
    run_here = False
    for root in trees:
        if root == REPO:
            run_here = True
            continue
        reason = _ineligible_reason(root, members)
        if reason:
            notes.append(reason)
            run_here = True          # judged here INSTEAD, never skipped
            continue
        delegate_to.append(root)
    return tuple(delegate_to), run_here, source, "; ".join(notes), ""


def run_chain(raw_payload: str, members: tuple[str, ...] = STOP_CHAIN) -> int:
    """Run every member on the same payload; the worst exit code wins.

    A guard that crashes is a BLOCK, not a pass (unmeasurable is never compliant —
    RC-57): its traceback goes to stderr and the chain reports exit 2.

    RC-512: before running anything, ask WHO should be running it. Every materially touched
    worktree of this repository runs the identical roster and the WORST real verdict wins —
    adjudicated, not chosen, because any rule for choosing one tree is a rule an agent can
    satisfy on purpose. When this tree is among them, or when a resolved tree was refused
    authority, the roster also runs here and every BLOCK says so. No path skips the roster,
    no verdict is softened on the way back, and authority that cannot be established REFUSES
    the event instead of picking a convenient tree.
    """
    delegate_to, run_here, source, notes, failure = resolve_authority(raw_payload, members)
    worst = 0
    if failure:
        sys.stderr.write(
            f"GOVERNANCE AUTHORITY: REFUSED — {failure}. Blocking rather than falling back to "
            f"{REPO}, because quietly judging in whichever tree happens to be running the hook "
            f"is the defect this resolves (RC-512). The roster below still runs: a refusal to "
            f"establish authority adds a block, it never removes one.\n")
        worst = 2
    for root in delegate_to:
        worst = max(worst, _delegate(root, raw_payload, members))
    if not run_here:
        return 2 if worst else 0
    for name in members:
        try:
            mod = importlib.import_module(name)
            sys.stdin = io.StringIO(raw_payload)
            rc = int(mod.main() or 0)
        except SystemExit as exc:          # a guard that sys.exit()s inside main()
            rc = int(exc.code or 0)
        except Exception as exc:  # noqa: BLE001 — a broken guard must scream, not wave through
            sys.stderr.write(f"STOP CHAIN: {name} crashed: {type(exc).__name__}: {exc}\n")
            rc = 2
        worst = max(worst, rc)
    if worst:
        sys.stderr.write(authority_banner(REPO, source, notes) + "\n")
    return 2 if worst else 0


def _argv_members(argv: list[str]) -> tuple[str, ...]:
    """Roster from the command line: 'tools/stop_guard.py' -> 'tools.stop_guard'.

    The hook files pass the roster EXPLICITLY, so the wiring stays reviewable in
    .claude/settings.json / .cursor/hooks.json and the existing name-pin tests keep
    binding the real thing. No argv -> the default STOP_CHAIN."""
    out = []
    for a in argv:
        a = a.replace("\\", "/").removeprefix("tools/").removesuffix(".py")
        if a:
            out.append(f"tools.{a}")
    return tuple(out)


def main() -> int:
    members = _argv_members(sys.argv[1:]) or STOP_CHAIN
    return run_chain(sys.stdin.read(), members)


if __name__ == "__main__":
    sys.exit(main())
