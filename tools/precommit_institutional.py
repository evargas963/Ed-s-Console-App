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
that as a paydown, and `operating_process_lock.staged_enforced_checks_not_on_head` only detects
checks ADDED (`wt - head`), never removed. That comparison needs neither the whole-tree catalog
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


def local_remote_parity(root: Path | None = None) -> dict[str, dict[str, str]]:
    """Per local hook: its deciding owner (the last tools/ token of the entry, or the
    `python -m <module>` it runs) is executed by a remote workflow, directly or through the
    delta gate's imports. A hook whose owner never runs remotely is a rule a `SKIP=` or
    `--no-verify` locally turns into a remotely admissible violation."""
    base = root or REPO
    remote = _acceptance().remote_invoked_tools(base)
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
