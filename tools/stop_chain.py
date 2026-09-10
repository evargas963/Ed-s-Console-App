"""ONE hook executor for both entrypoints (tools/stop_chain.py, tools/pretooluse_chain.py).

Runs every rostered guard in-process on the same payload; the worst exit code wins; a guard
that crashes is a BLOCK (unmeasurable is never compliant, RC-57). The guards stay
independently runnable — this file is wiring plus one question: WHICH TREE judges the event.

GOVERNANCE AUTHORITY — resolved from the event's own payload, and from nothing else.

  RC-512: `.claude/settings.json` registers the hook relative to the session project
  directory, so the guards that judged an event came from whichever checkout the session was
  LAUNCHED in (the production desk, possibly commits behind), not the tree the event touches.
  The rule: the tree a mutation TARGETS is the tree whose registered guards judge it.

      file-target payload  -> the worktree containing the path                (work target)
      shell payload        -> every worktree the command materially writes,
                              read through process_lock_guard's own parsers     (shell target)
      no target (Stop, a read-only shell command) -> this tree judges           (this tree)
      a mutation whose tree cannot be located     -> the event is REFUSED       (unresolved)

  Authority is confined to `repo_worktrees()`, so a prepared directory with obliging guards
  is never selected; a delegate runs the roster ITS OWN wiring registers (RC-522/RC-531);
  a delegate that cannot run BLOCKS.

  INVARIANT (2026-09-10): a blocked or unexecuted action has ZERO authority-state effect.
  Authority is a pure function of the payload in hand. Nothing is remembered across events:
  no transcript is read, no session record is kept, no crashed-delegate recovery door
  exists, no tree is refused for uncommitted guard edits and judged elsewhere instead. The
  previous resolver read the session transcript to find "every worktree this session
  modified"; a tool_use record there cannot tell an executed mutation from one the hook
  refused, so a single BLOCKED command poisoned every later event of the session. A
  broken guard module in a target tree is repaired by the operator or from git, never through
  a hooked mutation judged by another tree.
"""
from __future__ import annotations

import importlib
import io
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

#: Default Stop roster when no argv is given; the hook files pass the roster explicitly.
STOP_CHAIN = ("tools.stop_guard",)

#: RC-520: THE roster of tools that carry a shell `command`; both shell guards import it.
BASH_TOOLS = frozenset({"Bash", "PowerShell", "Shell", "Monitor"})

#: File-target tools that MODIFY a tree (a Read/Grep/Glob payload names no work target).
MUTATING_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})

#: Set on a delegated run so authority hops exactly ONCE and can never loop.
DELEGATED_ENV = "ED_GOVERNANCE_AUTHORITY_DELEGATED"

#: The live in-session hook hosts and their wiring files; `hook_wiring_divergence` proves
#: they register the same chain entries, so no host is a population of its own.
HOOK_WIRINGS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("claude", (".claude", "settings.json")),
    ("cursor", (".cursor", "hooks.json")),
)


def _git(cwd: Path, *args: str) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                           text=True, timeout=15, check=False)
        return (r.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _payload(raw_payload: str) -> dict:
    try:
        data = json.loads(raw_payload)
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        return {}
    return data if isinstance(data, dict) else {}


# ── which trees may hold authority ─────────────────────────────────────────────────────
def repo_worktrees() -> set[Path]:
    """Every checkout of THIS repository — the only paths that may hold authority."""
    out: set[Path] = set()
    for line in _git(REPO, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            try:
                out.add(Path(line[len("worktree "):].strip()).resolve())
            except OSError:
                continue
    out.add(REPO)
    return out


def _enclosing_worktree(target: Path) -> Path | None:
    """The nearest ancestor of `target` that is a worktree of THIS repository, confirmed
    against `repo_worktrees()` rather than inferred from a `.git` probe."""
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


def payload_work_tree(raw_payload: str) -> Path | None:
    """The worktree a file-target tool call TARGETS, or None when the payload names no path."""
    tool_input = _payload(raw_payload).get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    for key in ("file_path", "notebook_path", "path"):
        raw = tool_input.get(key)
        if isinstance(raw, str) and raw.strip():
            return _enclosing_worktree(Path(raw))
    return None


def bash_mutation_targets(command: str, payload_cwd: str = "") -> tuple[list[str], list[str]]:
    """`(paths a shell command materially writes, reasons a mutation could not be located)`.

    Composition only — every judgement belongs to `tools/process_lock_guard.py`, which owns
    "where does this shell command write": write destinations (`cd` tracked across a chain),
    git operations that change a checkout (`-C <path>` resolved), and tracked-tree rewrites
    that name no destination (`git apply`, `patch`, `git restore`). A harmless read yields
    nothing. A mutation whose tree cannot be located is reported UNRESOLVED.
    """
    try:
        from tools.shell_parse import iter_command_segments, iter_git_invocations
        from tools.process_lock_guard import (
            _shell_rewrites_tracked_tree,
            _shell_write_targets,
            git_segment_mutates_checkout,
        )
    except ImportError as exc:
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


def canonical_authority(raw_payload: str) -> tuple[tuple[Path, ...], str, str]:
    """Who governs this event: `(trees, source, failure)` — from the payload alone."""
    data = _payload(raw_payload)
    tree = payload_work_tree(raw_payload)
    if tree is not None:
        return (tree,), "work target", ""
    tool_input = data.get("tool_input")
    if data.get("tool_name") in BASH_TOOLS and isinstance(tool_input, dict):
        command = tool_input.get("command")
        if isinstance(command, str) and command.strip():
            cwd = data.get("cwd")
            paths, unresolved = bash_mutation_targets(command, cwd if isinstance(cwd, str) else "")
            if unresolved:
                return (), "unresolved", "; ".join(sorted(set(unresolved))[:5])
            trees: list[Path] = []
            for p in paths:
                t = _enclosing_worktree(Path(p))
                if t is not None and t not in trees:
                    trees.append(t)
            if trees:
                return tuple(trees), "shell target", ""
    return (), "this tree", ""


def authority_banner(root: Path, source: str, note: str = "") -> str:
    """Which tree judged this event and how it was chosen — a block never reads as a mystery."""
    head = _git(root, "rev-parse", "--short", "HEAD") or "unknown"
    branch = _git(root, "symbolic-ref", "--short", "HEAD") or "detached"
    tail = f" - {note}" if note else ""
    return f"GOVERNANCE AUTHORITY: {root} @ {branch} {head} [{source}]{tail}"


# ── the hook seam's own enumeration ────────────────────────────────────────────────────
def _wiring_entries(root: Path, parts: tuple[str, ...]) -> list[str] | None:
    """Chain entries (`tools/*_chain.py` tokens) in one wiring file, in wiring order; None when
    the file is unreadable. Claude nests commands under `hooks`; Cursor puts `command` on the
    entry — one reader for both shapes."""
    try:
        data = json.loads(root.joinpath(*parts).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    hooks = (data.get("hooks") or {}) if isinstance(data, dict) else {}
    out: list[str] = []
    for entries in (hooks.values() if isinstance(hooks, dict) else ()):
        for entry in entries if isinstance(entries, list) else ():
            if not isinstance(entry, dict):
                continue
            nested = [h.get("command") for h in (entry.get("hooks") or []) if isinstance(h, dict)]
            for command in nested or [entry.get("command")]:
                for tok in str(command or "").split():
                    tok = tok.replace("\\", "/")
                    if tok.startswith("tools/") and tok.endswith("_chain.py") and tok not in out:
                        out.append(tok)
    return out


def registered_entrypoints(root: Path, host: str | None = None) -> tuple[str, ...]:
    """Every chain ENTRY the tree's own hook wiring registers — the union of every live host
    wiring, or one host's when `host` names it. The canonical enumeration of the hook seam
    (Close contract, AGENTS.md): recurrence controls drive every entry returned here and no
    hand-maintained list exists. Fail-closed: an unreadable wiring contributes nothing."""
    out: list[str] = []
    for name, parts in HOOK_WIRINGS:
        if host is not None and name != host:
            continue
        for tok in _wiring_entries(root, parts) or []:
            if tok not in out:
                out.append(tok)
    return tuple(out)


def wired_executables(root: Path) -> list[str]:
    """Every executable the hook seam runs on an event, repo-relative: the chain entries both
    hosts wire plus every member of the `*_CHAIN` rosters those executors declare — read
    statically from the tree at `root`. The population of REQ-GOV-HOOKS-FAIL-CLOSED."""
    import ast as _ast
    mods: list[str] = []
    for entry in registered_entrypoints(root):
        rel = entry.replace("\\", "/")
        if rel not in mods:
            mods.append(rel)
        p = root / rel
        if not p.is_file():
            continue
        try:
            tree = _ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, _ast.Assign) and any(
                    isinstance(t, _ast.Name) and t.id.endswith("_CHAIN") for t in node.targets):
                for c in _ast.walk(node.value):
                    if isinstance(c, _ast.Constant) and isinstance(c.value, str) and c.value.startswith("tools."):
                        member = "tools/" + c.value.split(".", 1)[1] + ".py"
                        if member not in mods:
                            mods.append(member)
    return sorted(m for m in mods if (root / m).is_file())


def fail_closed_status(root: Path) -> dict[str, dict[str, str]]:
    """Run every wired executable on an UNREADABLE payload: `{path: {status, detail}}`.
    A guard that exits 0 on input it cannot read waves the event through (RC-541)."""
    out: dict[str, dict[str, str]] = {}
    for rel in wired_executables(root):
        try:
            r = subprocess.run([sys.executable, str(root / rel)], cwd=str(root), input="{not json",
                               capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=120)
            rc = r.returncode
        except (OSError, subprocess.SubprocessError) as e:
            out[rel] = {"status": "INVALID", "detail": f"could not execute: {e}"}
            continue
        out[rel] = ({"status": "PROVEN", "detail": f"exit {rc} on an unreadable payload"} if rc != 0
                    else {"status": "FAIL", "detail": "exit 0 on an unreadable payload - fails OPEN"})
    return out


def hook_wiring_divergence(root: Path) -> dict[str, tuple[str, ...]]:
    """Entries one live host wires and the other does not — `{host: entries_only_there}`."""
    seen = {name: tuple(_wiring_entries(root, parts) or ()) for name, parts in HOOK_WIRINGS}
    return {name: tuple(e for e in entries
                        if any(e not in other for oname, other in seen.items() if oname != name))
            for name, entries in seen.items()}


# ── the roster a tree is judged under: its OWN wiring (RC-522 / RC-531) ────────────────
_PRETOOLUSE_TOOLS = MUTATING_TOOLS | BASH_TOOLS


def _payload_event(raw_payload: str) -> tuple[str, str]:
    """`(event, tool_name)` — the event a payload belongs to, as the host would route it."""
    data = _payload(raw_payload)
    tool = data.get("tool_name")
    tool = tool if isinstance(tool, str) else ""
    event = data.get("hook_event_name")
    if isinstance(event, str) and event:
        return event, tool
    return ("PreToolUse" if tool in _PRETOOLUSE_TOOLS else "Stop"), tool


def tree_roster(root: Path, raw_payload: str) -> tuple[tuple[str, ...], str]:
    """`(members, failure)`: the roster `root`'s OWN `.claude/settings.json` registers for this
    event. Read from the tree, never trusted from argv (RC-522: the launch tree's wiring named
    a guard the delegate had retired; RC-531: an old launcher forwarded its argv). Fail-closed:
    no wiring, an unparseable one, no entry for this event, or an empty roster is a failure."""
    wiring = root / ".claude" / "settings.json"
    try:
        data = json.loads(wiring.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return (), f"{root} carries no readable hook wiring at .claude/settings.json"
    event, tool = _payload_event(raw_payload)
    hooks = (data.get("hooks") or {}) if isinstance(data, dict) else {}
    entries = hooks.get(event) if isinstance(hooks, dict) else None
    if not isinstance(entries, list) or not entries:
        return (), f"{root} registers no {event} hook in its wiring"
    chosen = None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        matcher = entry.get("matcher")
        if event == "PreToolUse":
            if not isinstance(matcher, str) or not tool:
                continue
            try:
                if not re.fullmatch(matcher, tool):
                    continue
            except re.error:
                continue
        chosen = entry
        break
    if chosen is None:
        return (), f"{root} registers no {event} hook for tool {tool!r} in its wiring"
    commands = [h.get("command") for h in (chosen.get("hooks") or []) if isinstance(h, dict)]
    command = next((c for c in commands if isinstance(c, str) and c.strip()), "")
    argv = [t for t in command.split() if t.replace("\\", "/").startswith("tools/")
            and "chain" not in t]
    members = _argv_members(argv)
    if not members:
        return (), f"{root} registers an empty {event} roster in its wiring"
    return members, ""


def _delegate(root: Path, raw_payload: str) -> int:
    """Run `root`'s OWN roster under `root`'s governance; return its verdict. Fail-closed: a
    tree with no canonical wiring, or a delegate that crashes, times out or cannot be spawned,
    is a BLOCK — a guard run that did not happen is not one that passed."""
    import os

    members, failure = tree_roster(root, raw_payload)
    if failure:
        sys.stderr.write(f"GOVERNANCE AUTHORITY: {root} cannot judge this event — {failure}. "
                         f"A mutation there is refused, never judged by another tree.\n")
        return 2
    entry = root / "tools" / "stop_chain.py"
    if not entry.is_file():
        sys.stderr.write(f"GOVERNANCE AUTHORITY: {root} carries no chain to delegate to; refused.\n")
        return 2
    argv = [f"tools/{name.split('.')[-1]}.py" for name in members]
    env = dict(os.environ)
    env[DELEGATED_ENV] = "1"
    try:
        proc = subprocess.run(
            [sys.executable, str(entry), *argv], cwd=str(root), env=env,
            input=raw_payload, text=True, capture_output=True, timeout=180,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        sys.stderr.write(f"GOVERNANCE AUTHORITY: delegation to {root} failed "
                         f"({type(exc).__name__}: {exc}); blocking.\n")
        return 2
    if proc.stdout:
        sys.stdout.write(proc.stdout)
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    return proc.returncode


def resolve_authority(raw_payload: str, members: tuple[str, ...]) -> tuple[
        tuple[Path, ...], bool, str, str, str]:
    """The whole plan: `(delegate_to, run_here, source, notes, failure)`.

    `run_here` is True when this tree is itself a target or nothing resolved. Every other
    target worktree is delegated to and judged under its own wiring; a refused delegation is a
    block, never a reason to judge here instead. `members` (this tree's argv roster) governs
    only the run-here half."""
    import os

    if os.environ.get(DELEGATED_ENV) == "1":
        return (), True, "delegated run", "already delegated; this IS the authority", ""
    trees, source, failure = canonical_authority(raw_payload)
    if failure:
        # run_here stays TRUE: refusing to locate a mutation's tree must not become a way to
        # skip the roster; the refusal is an ADDITIONAL block on top of the members' verdict.
        return (), True, source, "", failure
    if not trees:
        return (), True, source, "", ""
    delegate_to = tuple(root for root in trees if root != REPO)
    return delegate_to, REPO in trees, source, "", ""


def run_chain(raw_payload: str, members: tuple[str, ...] = STOP_CHAIN) -> int:
    """Run every member on the same payload in the tree(s) the payload targets; worst exit wins.

    RC-541: an unreadable payload is refused before any roster sees it. RC-531: a DELEGATED
    run is judged under THIS tree's own wiring whatever the launcher passed on argv, decided
    here in the one executor both entrypoints share."""
    import os

    try:
        parsed = json.loads(raw_payload)
    except (json.JSONDecodeError, ValueError, TypeError):
        parsed = None
    if not isinstance(parsed, dict):
        sys.stderr.write("STOP CHAIN: the hook payload is not a readable JSON object; the event "
                         "cannot be judged and is refused. Unreadable is not clean.\n")
        return 2

    if os.environ.get(DELEGATED_ENV) == "1":
        own, roster_failure = tree_roster(REPO, raw_payload)
        if roster_failure:
            sys.stderr.write(
                f"GOVERNANCE AUTHORITY: delegated run in {REPO} REFUSED — {roster_failure}; the "
                f"launch tree's argv roster is not a substitute for this tree's wiring (RC-531).\n")
            return 2
        members = own
    delegate_to, run_here, source, notes, failure = resolve_authority(raw_payload, members)
    worst = 0
    if failure:
        sys.stderr.write(
            f"GOVERNANCE AUTHORITY: REFUSED — {failure}. This event is blocked; nothing is "
            f"remembered about it, and the next event is judged on its own payload.\n")
        worst = 2
    for root in delegate_to:
        worst = max(worst, _delegate(root, raw_payload))
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
    """Roster from the command line: 'tools/stop_guard.py' -> 'tools.stop_guard'."""
    out = []
    for a in argv:
        a = a.replace("\\", "/").removeprefix("tools/").removesuffix(".py")
        if a:
            out.append(f"tools.{a}")
    return tuple(out)


def main() -> int:
    members = _argv_members(sys.argv[1:]) or STOP_CHAIN
    return run_chain(sys.stdin.read(), members)   # a delegated run re-reads its own roster inside


if __name__ == "__main__":
    sys.exit(main())
