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
import ast
import json
import os
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
_BANNER_FAIL_N = re.compile(r"GATE: FAIL \((\d+) enforced")


def _run(args: list[str], cwd: Path | None = None, timeout: int = 3600) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, cwd=str(cwd or REPO), capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False, timeout=timeout,
    )


def parse_counts(stdout: str) -> dict[str, int]:
    return {m.group(1): int(m.group(2)) for m in _FAIL_RE.finditer(stdout)}


def interpret_gate_output(returncode: int, stdout: str, stderr: str = "",
                          ref: str = "ref") -> dict[str, int]:
    """Fail-closed: a completed gate, or raise. Never treat silence as zero.

    Residual H1 (Cursor 2026-08-16): banner present + rc in {0,1} + no parseable
    FAIL [name] lines still rendered as {} and compared as PAID DOWN. A FAIL
    banner with an empty parse is the same hole wearing a header.
    """
    out = stdout or ""
    if returncode not in (0, 1) or _BANNER not in out:
        raise RuntimeError(
            f"gate did not complete for {ref} (rc={returncode}, banner "
            f"{'present' if _BANNER in out else 'MISSING'}). Refusing to "
            f"report a count: silence is not cleanliness.\n"
            f"--- tail ---\n{(out or stderr)[-600:]}")
    counts = parse_counts(out)
    parsed = sum(counts.values())
    m = _BANNER_FAIL_N.search(out)
    banner_tail = out.split(_BANNER, 1)[-1] if _BANNER in out else ""
    if returncode == 1:
        if not m or int(m.group(1)) <= 0 or parsed == 0:
            raise RuntimeError(
                f"gate exited 1 for {ref} but produced no parseable "
                f"FAIL [name] lines (parsed={parsed}, banner_n="
                f"{m.group(1) if m else 'MISSING'}). Silence-as-clean "
                f"is refused.")
        n = int(m.group(1))
        if parsed != n:
            raise RuntimeError(
                f"gate banner says {n} enforced for {ref} but parsed {parsed}.")
    elif m and int(m.group(1)) > 0:
        raise RuntimeError(
            f"gate exited 0 for {ref} but banner says FAIL ({m.group(1)}).")
    elif parsed > 0:
        raise RuntimeError(
            f"gate exited 0 for {ref} but parsed {parsed} FAIL [name] line(s).")
    elif "FAIL" in banner_tail and parsed == 0:
        raise RuntimeError(
            f"gate banner contains FAIL for {ref} but no parseable "
            f"FAIL [name] lines. Silence-as-clean is refused.")
    return counts


def commit_from_index() -> str:
    """Ephemeral commit of the STAGED index (RC-389 / H2). Does not move HEAD."""
    tree = _run(["git", "write-tree"])
    if tree.returncode != 0 or not tree.stdout.strip():
        raise RuntimeError(f"cannot write-tree the index: {tree.stderr[-300:]}")
    head = _run(["git", "rev-parse", "HEAD"])
    if head.returncode != 0 or not head.stdout.strip():
        raise RuntimeError(f"cannot resolve HEAD: {head.stderr[-300:]}")
    env = os.environ.copy()
    env.setdefault("GIT_AUTHOR_NAME", "delta-gate")
    env.setdefault("GIT_AUTHOR_EMAIL", "delta-gate@local")
    env.setdefault("GIT_COMMITTER_NAME", "delta-gate")
    env.setdefault("GIT_COMMITTER_EMAIL", "delta-gate@local")
    cmt = subprocess.run(
        ["git", "commit-tree", tree.stdout.strip(), "-p", head.stdout.strip(),
         "-m", "delta-gate-staged"],
        cwd=str(REPO), capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=env, check=False,
    )
    if cmt.returncode != 0 or not cmt.stdout.strip():
        raise RuntimeError(f"cannot commit-tree the index: {cmt.stderr[-300:]}")
    return cmt.stdout.strip()


def parse_enforced_names(source: str) -> set[str]:
    """ENFORCED check ids from a checker source. Empty on parse failure (fail-closed)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "CHECKS" for t in node.targets):
            continue
        if not isinstance(node.value, ast.List):
            return set()
        names: set[str] = set()
        for elt in node.value.elts:
            if not (isinstance(elt, ast.Tuple) and len(elt.elts) >= 3):
                continue
            name_node, en_node = elt.elts[0], elt.elts[2]
            if (
                isinstance(name_node, ast.Constant)
                and isinstance(name_node.value, str)
                and isinstance(en_node, ast.Constant)
                and en_node.value is True
            ):
                names.add(name_node.value)
        return names
    return set()


def wiring_violations(root: Path) -> list[str]:
    """RC-389: the commit path must grade a delta, and --no-verify must not be a default.

    File reads only — this is applied to a detached worktree of HEAD/staged, so it
    must not import that tree's modules into the running process.
    """
    out: list[str] = []
    pre_path = root / "tools" / "precommit_institutional.py"
    if not pre_path.is_file():
        out.append("tools/precommit_institutional.py is missing")
        return out
    pre = pre_path.read_text(encoding="utf-8")
    if "check_delta_adds_no_debt.py" not in pre:
        out.append(
            "precommit_institutional.py does not invoke check_delta_adds_no_debt.py "
            "— the blocking path is back to absolute-zero and will be bypassed"
        )
    if "--staged" not in pre:
        out.append(
            "precommit_institutional.py does not pass --staged "
            "(H2: would grade last HEAD, not the index being committed)"
        )
    if "origin/main" not in pre:
        out.append("precommit_institutional.py does not pin --base origin/main")
    if "return 2" not in pre:
        out.append(
            "precommit_institutional.py does not fail-closed (exit 2) when "
            "origin/main cannot be resolved"
        )
    wf = root / ".github" / "workflows" / "delta-debt.yml"
    if not wf.is_file():
        out.append(
            ".github/workflows/delta-debt.yml is missing — local --no-verify "
            "cannot skip CI, so deleting the workflow deletes the unskippable half"
        )
    else:
        wf_text = wf.read_text(encoding="utf-8")
        if "check_delta_adds_no_debt.py" not in wf_text:
            out.append(
                "delta-debt.yml does not invoke check_delta_adds_no_debt.py"
            )
        if "git show" not in wf_text and "BASE" not in wf_text:
            out.append(
                "delta-debt.yml does not run the BASE comparator "
                "(a PR must not grade itself)"
            )
    grants_path = root / "governance" / "operator_grants.json"
    if not grants_path.is_file():
        out.append("governance/operator_grants.json is missing")
    else:
        try:
            doc = json.loads(grants_path.read_text(encoding="utf-8"))
        except ValueError:
            out.append("governance/operator_grants.json is unparseable")
        else:
            grant = (doc.get("grants") or {}).get("claude_no_verify_checkpoints") or {}
            if grant.get("granted") is True:
                out.append(
                    "claude_no_verify_checkpoints.granted is true — --no-verify "
                    "hides new enforced violations inside standing red (RC-389)"
                )
    delta_path = root / "tools" / "check_delta_adds_no_debt.py"
    if not delta_path.is_file():
        out.append("tools/check_delta_adds_no_debt.py is missing")
    else:
        src = delta_path.read_text(encoding="utf-8")
        if "interpret_gate_output" not in src:
            out.append("delta tool has no interpret_gate_output (H1 fail-open)")
        if "no parseable" not in src:
            out.append(
                "delta tool does not refuse a FAIL banner with no parseable "
                "FAIL [name] lines (residual H1)"
            )
    return out


def inspect_ref(ref: str, *, collect_wiring: bool = False
                ) -> tuple[dict[str, int], str, set[str], list[str]]:
    """counts, short-sha, ENFORCED names, wiring violations — clean detached worktree."""
    sha = _run(["git", "rev-parse", "--short", ref]).stdout.strip()
    with tempfile.TemporaryDirectory(prefix="deltagate-") as tmp:
        wt = Path(tmp) / "wt"
        add = _run(["git", "worktree", "add", "--detach", str(wt), ref])
        if add.returncode != 0:
            raise RuntimeError(f"cannot materialise {ref}: {add.stderr[-300:]}")
        try:
            checker = wt / "tools" / "check_institutional_correctness.py"
            names = parse_enforced_names(
                checker.read_text(encoding="utf-8")) if checker.is_file() else set()
            wiring = wiring_violations(wt) if collect_wiring else []
            proc = _run([sys.executable, "tools/check_institutional_correctness.py",
                         "--enforced-only"], cwd=wt)
            counts = interpret_gate_output(
                proc.returncode, proc.stdout, proc.stderr, ref)
            return counts, sha, names, wiring
        finally:
            _run(["git", "worktree", "remove", "--force", str(wt)])


def enforced_counts(ref: str) -> tuple[dict[str, int], str]:
    """{check_name: violation_count} for `ref`, measured in a CLEAN detached worktree."""
    counts, sha, _names, _wiring = inspect_ref(ref)
    return counts, sha


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
    ap.add_argument(
        "--staged", action="store_true",
        help="RC-389/H2: measure the staged index, not HEAD (pre-commit path)")
    args = ap.parse_args(argv)

    base_counts, base_sha, base_names, _ = inspect_ref(args.base)
    head_ref = commit_from_index() if args.staged else "HEAD"
    head_counts, head_sha, head_names, wiring = inspect_ref(
        head_ref, collect_wiring=True)
    removed = sorted(base_names - head_names)
    if wiring:
        head_counts = dict(head_counts)
        head_counts["no_verify_cannot_hide_delta"] = (
            head_counts.get("no_verify_cannot_hide_delta", 0) + len(wiring))
    if removed:
        head_counts = dict(head_counts)
        head_counts["enforced_gate_shrink"] = (
            head_counts.get("enforced_gate_shrink", 0) + len(removed))
    added, improved = compare(base_counts, head_counts)

    print(f"base {args.base} ({base_sha}): {sum(base_counts.values())} enforced "
          f"across {len(base_counts)} check(s)")
    print(f"HEAD ({head_sha}): {sum(head_counts.values())} enforced "
          f"across {len(head_counts)} check(s)")
    if improved:
        print("\nPAID DOWN by this delta:")
        print("\n".join(improved))
    if wiring:
        print("\nWIRING (HEAD/staged — RC-389, not inherited backlog):")
        print("\n".join(f"  {w}" for w in wiring))
    if removed:
        print("\nGATE SHRINK (H3 — dropping an ENFORCED check is not an improvement):")
        print("\n".join(f"  {n}" for n in removed))
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
