"""Did MY change add debt? Compare the enforced gate between a base and this HEAD.

WHY THIS EXISTS (RC-387) — the measured failure pattern of 2026-08-15/16, one session:

  * RC-384: I refused a glob at PATH scope, then built exactly that failure at FILE scope.
    My own test could not see it. Cursor found it.
  * Four ledger closes shipped without the RC-106 clauses the contract requires. The stop
    guard found them, on two separate passes.
  * My verifier's regex matched `.js` inside `.json`, so rows were held open for a parser
    error. The operator's question found it.
  * I verified that citations RESOLVE and called that verification; running the cited
    proofs showed one failing across 736. The operator's question found that too.

Every one is the same shape: I write the check for the failure mode I am thinking about,
ship it, and a DIFFERENT mode is discovered by someone else. Tests an author writes can
only encode the modes that author already imagined.

The repo, however, already owns ~75 checks encoding modes I did NOT imagine — written by
past incidents, precisely because somebody missed them before. Nothing was pointing that
surface at my delta before I declared the work done, so review was acting as the discovery
mechanism instead of the confirmation mechanism, and every miss cost an operator round trip.

So this is not a new rule. It is the existing gate, aimed at my own change, asking one
question: does HEAD carry any enforced violation the base did not?

Two design choices that decide whether it is useful:
  * CLEAN detached worktrees on both sides. A dirty tree carries scratch files and
    half-finished edits that are not part of the change — that is exactly how a filtered
    local count got quoted where the gate reads the full one.
  * Pre-existing violations are reported SEPARATELY, never summed into a verdict. On a
    repo carrying ~100 standing violations, a whole-number comparison would drown a fresh
    regression in backlog noise and the tool would be ignored inside a week.

Usage:
    python tools/check_delta_adds_no_debt.py                 # origin/main -> HEAD
    python tools/check_delta_adds_no_debt.py --base <ref>
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: `FAIL [name] (ENFORCED) — N violation(s):`  — the em dash varies by console encoding,
#: so match on the bracketed name and the trailing count rather than the separator.
_FAIL_RE = re.compile(r"FAIL \[([a-z_0-9]+)\].*?(\d+) violation")

#: The gate prints this on every completed run, PASS or FAIL. Its ABSENCE means the run
#: died, not that the tree is clean — see the fail-closed guard in enforced_counts.
_BANNER = "INSTITUTIONAL CORRECTNESS GATE:"


def _run(args: list[str], cwd: Path | None = None, timeout: int = 3600) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, cwd=str(cwd or REPO), capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False, timeout=timeout,
    )


def parse_counts(stdout: str) -> dict[str, int]:
    return {m.group(1): int(m.group(2)) for m in _FAIL_RE.finditer(stdout)}


def enforced_counts(ref: str) -> tuple[dict[str, int], str]:
    """{check_name: violation_count} for `ref`, measured in a CLEAN detached worktree."""
    sha = _run(["git", "rev-parse", "--short", ref]).stdout.strip()
    with tempfile.TemporaryDirectory(prefix="deltagate-") as tmp:
        wt = Path(tmp) / "wt"
        add = _run(["git", "worktree", "add", "--detach", str(wt), ref])
        if add.returncode != 0:
            raise RuntimeError(f"cannot materialise {ref}: {add.stderr[-300:]}")
        try:
            proc = _run([sys.executable, "tools/check_institutional_correctness.py",
                         "--enforced-only"], cwd=wt)
            # FAIL CLOSED (Cursor hole audit H1). As first shipped this returned
            # parse_counts(stdout) unconditionally, and parse_counts("") is {} — so a
            # crashed gate, an import error, or a changed output format rendered the side
            # as ZERO violations, printed PASS, and invented a "PAID DOWN" line. A lock
            # that cannot distinguish CLEAN from SILENT is the RC-90 class. The gate's own
            # summary banner is the proof it actually ran to completion.
            if proc.returncode not in (0, 1) or _BANNER not in proc.stdout:
                raise RuntimeError(
                    f"gate did not complete for {ref} (rc={proc.returncode}, banner "
                    f"{'present' if _BANNER in proc.stdout else 'MISSING'}). Refusing to "
                    f"report a count: silence is not cleanliness.\n"
                    f"--- tail ---\n{(proc.stdout or proc.stderr)[-600:]}")
            return parse_counts(proc.stdout), sha
        finally:
            _run(["git", "worktree", "remove", "--force", str(wt)])


def compare(base_counts: dict[str, int], head_counts: dict[str, int]) -> tuple[list[str], list[str]]:
    """(added, improved) as human lines. Added is the only thing that fails the gate."""
    added, improved = [], []
    for name in sorted(set(base_counts) | set(head_counts)):
        b, h = base_counts.get(name, 0), head_counts.get(name, 0)
        if h > b:
            added.append(f"  {name}: {b} -> {h}  (+{h - b})")
        elif h < b:
            improved.append(f"  {name}: {b} -> {h}  (-{b - h})")
    return added, improved


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Fail if HEAD adds an enforced violation the base did not carry")
    ap.add_argument("--base", default="origin/main")
    args = ap.parse_args(argv)

    base_counts, base_sha = enforced_counts(args.base)
    head_counts, head_sha = enforced_counts("HEAD")
    added, improved = compare(base_counts, head_counts)

    print(f"base {args.base} ({base_sha}): {sum(base_counts.values())} enforced "
          f"across {len(base_counts)} check(s)")
    print(f"HEAD ({head_sha}): {sum(head_counts.values())} enforced "
          f"across {len(head_counts)} check(s)")
    if improved:
        print("\nPAID DOWN by this delta:")
        print("\n".join(improved))
    if not added:
        print("\n[PASS] this delta adds no enforced violation the base did not already carry.")
        return 0
    print("\n[FAIL] this delta ADDS enforced violations — not done, whatever the "
          "hand-written tests say:")
    print("\n".join(added))
    print("\nThese checks are already owned by the repo and encode failure modes this "
          "change's own tests did not imagine. Fix them, then re-run.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
