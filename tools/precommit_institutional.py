#!/usr/bin/env python3
"""Pre-commit institutional gate entry — and the ONE owner of the local commit seam's roster.

RC-406 (engineering-cycle latency): the whole-tree ADDED-VIOLATION delta — two clean detached
worktrees (base origin/main + candidate index), the enforced catalog run in EACH — measured
~250s on the commit path and was the dominant commit-cycle cost. It is REDUNDANT there:
`.github/workflows/hardening.yml` runs the SAME owner (`check_delta_adds_no_debt.py --base
origin/main`) on every PR — the authority before merge — so the whole-tree added-violation
scan is RELOCATED to CI, NOT skipped.

What STAYS on the commit path, fast and fail-closed: the single most valuable thing to detect
LOCALLY is an enforced check being DELETED or DOWNGRADED (RC-391) — violation counts alone read
that as a paydown. That comparison needs neither the whole-tree catalog
nor a worktree: it is the enforced ROSTER of `check_institutional_correctness.py`, read from the
base (origin/main) and the candidate (staged index) with `git show` + a static AST parse
(milliseconds). If the candidate drops any check the base enforced, this hook BLOCKS. Everything
else (added-violation counts across the tree) is proven in CI. Fail-closed: an unresolvable base,
an unreadable checker on either side, or an unparseable base roster refuses the commit.

UNIVERSAL_QUANTITATIVE_CLOSURE_V1 (2026-09-10): `_enforced_roster` is the ONE static roster
reader (the delta gate and the acceptance executor call it, so no side ever EXECUTES a
candidate checker to learn its roster); a deliberate retirement is declared by a base-side
`AUTHORIZE retire:<check>` row of the OPEN_ITEMS.md Requirements contract (the same two-step
rule every other grant follows — the former governance/retired_checks.md manifest is git
history); `local_hooks` / `local_remote_parity` enumerate this seam's own hooks and prove each
owner runs remotely (REQ-GOV-LOCAL-REMOTE-PARITY).

This file is also the owner of THE ENFORCEMENT-PATH POPULATION (`trust_anchor_paths`): every
file whose content decides what the commit seam, the hook seam and the remote workflows DO,
derived from the wirings themselves (the hook owner `tools.stop_chain` enumerates its
executables, this seam its hook entries, GitHub its workflow directory) plus every tools/
module those transitively import or run. The acceptance executor (governance/acceptance.py)
holds no population of its own; it calls this owner in the judged tree.
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CHECKER_REL = "tools/check_institutional_correctness.py"
_TOOL_TOKEN_RE = re.compile(r"tools[/\\]([A-Za-z0-9_]+)\.py")
#: Callees that run or load the path they are handed (the only string context that is behaviour).
_EXECUTING_CALLEES = frozenset({"run", "Popen", "call", "check_call", "check_output", "spec_from_file_location",
                                "import_module", "run_path", "exec_module", "_run", "_pipe", "_load_module",
                                "load_tree_module", "runWithFileSink", "spawnSync"})


def _acceptance():
    """The executor beside THIS file (the tree this seam belongs to), loaded by path so the
    seam works whether it runs as a hook, as an import, or as a tree module a judge loads."""
    import importlib.util
    name = f"_acceptance_{abs(hash(str(REPO)))}"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO / "governance" / "acceptance.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _git_show(spec: str, repo: Path | None = None) -> str | None:
    p = subprocess.run(
        ["git", "show", spec], cwd=str(repo or REPO),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return p.stdout if p.returncode == 0 else None


def _enforced_roster(source: str) -> set[str]:
    """Enforced check names from `CHECKS = [(name, fn, enforced), ...]` — static, no import."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "CHECKS" for t in node.targets
        ):
            if not isinstance(node.value, ast.List):
                continue
            names: set[str] = set()
            for elt in node.value.elts:
                if isinstance(elt, ast.Tuple) and len(elt.elts) >= 3:
                    nm, en = elt.elts[0], elt.elts[2]
                    if (
                        isinstance(nm, ast.Constant) and isinstance(nm.value, str)
                        and isinstance(en, ast.Constant) and en.value is True
                    ):
                        names.add(nm.value)
            return names
    return set()


def enforced_roster(root: Path) -> list[str]:
    """The tree's own enforced roster — a population authority for the acceptance contract."""
    names = _enforced_roster((root / CHECKER_REL).read_text(encoding="utf-8", errors="replace"))
    if not names:
        raise LookupError("CHECKS carries no enforced entry - an empty roster is a broken read")
    return sorted(names)


def _base_retirements(git_show, base: str) -> set[str]:
    """Check names the BASE ref's OPEN_ITEMS.md contract declares retired (`retire:` rows).
    A missing or unreadable base contract declares nothing — fail-closed toward blocking."""
    text = git_show(f"{base}:OPEN_ITEMS.md")
    if text is None:
        return set()
    A = _acceptance()
    try:
        return A.retirements(A.parse_contract(text))
    except A.ContractError:
        return set()


def local_hooks(root: Path | None = None) -> dict[str, str]:
    """{hook id: entry} of .pre-commit-config.yaml — the local commit seam's own roster."""
    text = ((root or REPO) / ".pre-commit-config.yaml").read_text(encoding="utf-8", errors="replace")
    out: dict[str, str] = {}
    cur = None
    for line in text.splitlines():
        m = re.match(r"^\s*-\s*id:\s*([A-Za-z0-9_\-]+)\s*$", line)
        if m:
            cur = m.group(1)
            out.setdefault(cur, "")
            continue
        m = re.match(r"^\s*entry:\s*(.+?)\s*$", line)
        if m and cur:
            out[cur] = m.group(1)
    if not out:
        raise LookupError("no hook ids in .pre-commit-config.yaml")
    return out


def _callee_name(call: ast.Call) -> str:
    f = call.func
    return f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")


def _tools_imports(root: Path, rel: str, seen: set[str]) -> None:
    """Transitive tools/* modules `rel` imports or runs (a tools/ path handed to a call that
    EXECUTES or LOADS it is behaviour; a path in a docstring or an allowlist is a mention)."""
    p = root / rel
    if rel in seen or not p.is_file():
        return
    seen.add(rel)
    try:
        tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _callee_name(node) in _EXECUTING_CALLEES:
            for arg in list(node.args) + [k.value for k in node.keywords]:
                for c in ast.walk(arg):
                    if isinstance(c, ast.Constant) and isinstance(c.value, str):
                        names.update(_TOOL_TOKEN_RE.findall(c.value))
        elif isinstance(node, ast.ImportFrom) and node.module:
            mod = node.module
            if mod.startswith("tools."):
                names.add(mod.split(".", 1)[1].split(".")[0])
            elif node.level == 0 and rel.startswith("tools/") and (root / "tools" / f"{mod}.py").is_file():
                names.add(mod)
            if mod == "tools":
                names.update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("tools."):
                    names.add(a.name.split(".", 1)[1].split(".")[0])
    for n in sorted(names):
        _tools_imports(root, f"tools/{n}.py", seen)


def workflow_files(root: Path) -> list[str]:
    """Every workflow GitHub can run: the directory IS the population by GitHub's definition."""
    d = root / ".github" / "workflows"
    if not d.is_dir():
        raise LookupError(".github/workflows missing")
    return sorted(f".github/workflows/{p.name}" for p in d.iterdir() if p.suffix in (".yml", ".yaml"))


def remote_invoked_tools(root: Path) -> set[str]:
    """Tool basenames (and `python -m` modules) the workflows execute, transitively through
    imports and subprocess strings - what a remote lane actually runs."""
    direct: set[str] = set()
    for wf in workflow_files(root):
        text = (root / wf).read_text(encoding="utf-8", errors="replace")
        direct.update(_TOOL_TOKEN_RE.findall(text))
        direct.update(m.group(1) for m in re.finditer(r"python\s+-m\s+([A-Za-z0-9_\.]+)", text))
    seen: set[str] = set()
    for tok in sorted(direct):
        _tools_imports(root, f"tools/{tok}.py", seen)
    return direct | {s.removeprefix("tools/").removesuffix(".py") for s in seen}


def trust_anchor_paths(root: Path) -> list[str]:
    """The files whose content decides what the enforcement path DOES, derived from the
    wiring itself: the hook wirings and every executable they run (tools.stop_chain owns that
    enumeration), the pre-commit config and the tools its entries run (this seam), every
    workflow and the tools they run, the institutional gate, the delta gate, the acceptance
    executor, every tools/ module any of those import, and every owner a Requirements SCOPE
    names. A candidate change to any of them is judged by the BASE copy and lands only with a
    base-side `AUTHORIZE anchor:` row. Raises LookupError when the tree cannot enumerate its
    own seam — the judge reports NOT_PROVEN, never a smaller population."""
    A = _acceptance()
    sc = A.load_tree_module(root, "tools.stop_chain")
    for fn in ("wired_executables", "HOOK_WIRINGS"):
        if not hasattr(sc, fn):
            raise LookupError(f"tools.stop_chain in {root} has no {fn} (predates this contract)")
    anchors: set[str] = set()
    anchors.update("/".join(parts) for _name, parts in sc.HOOK_WIRINGS)
    anchors.update(sc.wired_executables(root))
    anchors.add(".pre-commit-config.yaml")
    for entry in local_hooks(root).values():
        anchors.update(f"tools/{tok}.py" for tok in _TOOL_TOKEN_RE.findall(entry))
    anchors.update(workflow_files(root))
    for wf in workflow_files(root):
        anchors.update(f"tools/{tok}.py" for tok in _TOOL_TOKEN_RE.findall((root / wf).read_text(encoding="utf-8", errors="replace")))
    anchors.update({CHECKER_REL, "tools/check_delta_adds_no_debt.py", "governance/acceptance.py"})
    for r in A.requirements(A.load_contract(root)):
        if ":" in r.scope and not r.scope.startswith(("delta:", "evidence:", "narrowing:")):
            anchors.add(Path(*r.scope.split(":", 1)[0].split(".")).with_suffix(".py").as_posix())
    seen: set[str] = set()
    for a in sorted(anchors):
        if a.startswith("tools/") and a.endswith(".py"):
            _tools_imports(root, a, seen)
    anchors.update(seen)
    return sorted(a for a in anchors if (root / a).is_file())


def local_remote_parity(root: Path | None = None) -> dict[str, dict[str, str]]:
    """Per local hook: its deciding owner (the last tools/ token of the entry, or the
    `python -m <module>` it runs) is executed by a remote workflow, directly or through the
    delta gate's imports. A hook whose owner never runs remotely is a rule a `SKIP=` or
    `--no-verify` locally turns into a remotely admissible violation."""
    base = root or REPO
    remote = remote_invoked_tools(base)
    out: dict[str, dict[str, str]] = {}
    for hook, entry in local_hooks(base).items():
        toks = _TOOL_TOKEN_RE.findall(entry)
        m = re.search(r"python\s+-m\s+([A-Za-z0-9_\.]+)", entry)
        owner = toks[-1] if toks else (m.group(1) if m else (entry.split() or ["?"])[0])
        out[hook] = ({"status": "PROVEN", "detail": f"owner {owner} runs remotely"} if owner in remote
                     else {"status": "MISSING", "detail": f"owner {owner} is executed by no workflow"})
    return out


def _base_ref() -> str:
    """The trunk the roster is compared against. Unresolvable base => refuse the commit."""
    for ref in ("origin/main", "main"):
        p = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
            cwd=str(REPO), capture_output=True, text=True,
        )
        if p.returncode == 0 and p.stdout.strip():
            return ref
    raise SystemExit(
        "institutional gate: cannot resolve a base trunk (tried origin/main, main); the "
        "enforced-check roster cannot be compared, so this commit is refused rather than "
        "waved through unverified.")


def main() -> int:
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    base = _base_ref()
    base_src = _git_show(f"{base}:{CHECKER_REL}")
    cand_src = _git_show(f":{CHECKER_REL}")  # staged index (== HEAD when the checker is unstaged)
    if base_src is None or cand_src is None:
        print(
            f"institutional gate BLOCKED: cannot read {CHECKER_REL} on "
            f"{'base ' if base_src is None else ''}{'candidate' if cand_src is None else ''} "
            "— refusing rather than passing an unverifiable roster.", file=sys.stderr)
        return 1
    base_roster = _enforced_roster(base_src)
    cand_roster = _enforced_roster(cand_src)
    if not base_roster:
        print(
            f"institutional gate BLOCKED: could not parse the enforced roster from base "
            f"{CHECKER_REL} — an empty roster reads in the flattering direction, so refuse "
            "(RC-390 class).", file=sys.stderr)
        return 1
    removed = sorted(base_roster - cand_roster)
    if removed:
        declared = _base_retirements(_git_show, base)
        retired = [n for n in removed if n in declared]
        removed = [n for n in removed if n not in declared]
        if retired:
            print(
                f"institutional gate: {len(retired)} enforced check(s) RETIRED by BASE-side "
                f"AUTHORIZE retire: rows in OPEN_ITEMS.md (two-step contract): {', '.join(retired)}")
    if removed:
        print(
            "institutional gate BLOCKED: the staged change DELETES or DOWNGRADES enforced "
            f"check(s) the base carried WITHOUT a base-side `AUTHORIZE retire:` row in "
            f"OPEN_ITEMS.md: {', '.join(removed)}. Removing enforcement silently is the single "
            "most valuable regression to catch (RC-391); it is refused at commit. The whole-tree "
            "added-violation delta is proven separately in CI.", file=sys.stderr)
        return 1
    print(
        f"institutional correctness: enforced-check roster intact ({len(cand_roster)} enforced); "
        "whole-tree added-violation delta enforced in CI (.github/workflows/hardening.yml, same "
        "check_delta_adds_no_debt.py owner). (RC-406)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
