#!/usr/bin/env python3
"""Pre-commit institutional gate entry.

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
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CHECKER_REL = "tools/check_institutional_correctness.py"


def _neutralize_fabricated_identity() -> None:
    """RC-240: the institutional gate entry must never carry a FABRICATED actor into its own
    process. This wrapper once assigned ``ED_AGENT_ROLE = "cursor"`` unconditionally, so the
    identity-sensitive backstop judged the sole writer's OWN commit under an invented agent
    and blocked it ("mission writer='claude' but agent='cursor'"). A verdict that depends on
    who is acting must be given the real identity or NONE — never a guess. Whatever this gate
    runs now (roster read) or later, it first clears an unusable inherited role so nothing
    downstream in THIS process abstains-or-judges under a wrong actor. RC-406 relocated the
    catalog but this seam guarantee is independent of what runs behind it.
    """
    os.environ.pop("ED_AGENT_ROLE", None)


def _git_show(spec: str) -> str | None:
    p = subprocess.run(
        ["git", "show", spec], cwd=str(REPO),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return p.stdout if p.returncode == 0 else None


def _enforced_roster(source: str) -> set[str]:
    """Enforced check names from `CHECKS = [(name, fn, enforced), ...]` — static, no import.

    Mirrors operating_process_lock._parse_enforced_checks so the two locks read the roster
    the same way; kept local to avoid a heavy import on the commit hot-path.
    """
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
    _neutralize_fabricated_identity()
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
        print(
            "institutional gate BLOCKED: the staged change DELETES or DOWNGRADES enforced "
            f"check(s) the base carried: {', '.join(removed)}. Removing enforcement is the "
            "single most valuable regression to catch (RC-391); it is refused at commit. The "
            "whole-tree added-violation delta is proven separately in CI.", file=sys.stderr)
        return 1
    print(
        f"institutional correctness: enforced-check roster intact ({len(cand_roster)} enforced); "
        "whole-tree added-violation delta enforced in CI (.github/workflows/hardening.yml, same "
        "check_delta_adds_no_debt.py owner). (RC-406)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
