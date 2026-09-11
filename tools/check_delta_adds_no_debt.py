"""Did MY change add debt? Compare the enforced gate between a base and a candidate, in CI.

WHY THIS EXISTS (RC-387): the repo owns ~35 enforced checks encoding failure modes nobody
imagined in advance, and the trunk carries standing violations, so an absolute-zero gate is
unreachable and a whole-number comparison drowns a fresh regression in backlog. This measures
the DELTA: does the candidate carry any enforced violation the base did not? Clean detached
worktrees on both sides (a dirty tree carries scratch that is not the change); pre-existing
violations reported separately, never summed into a verdict.

Run by .github/workflows/hardening.yml (required check) as
    python tools/check_delta_adds_no_debt.py --base origin/main
and by hand. (The `--index` mode that measured the staged index for a pre-commit hook was
deleted 2026-09-11: its only caller, tools/precommit_institutional.py, left with RC-546.)

WHAT THIS IS, AND IS NOT (attack matrix on 1a2eaafe, 2026-09-11, RC-539): REGRESSION DETECTION
for a candidate that does not touch its judge. It runs the CANDIDATE's checker, in the
CANDIDATE's tree, from the CANDIDATE's workflow file, under the credential that also
administers the repository. A candidate that weakens a predicate (name kept), rubber-stamps
this script, retires the check that sees its violation, deletes the negative controls,
neutralises a module the checker imports without touching the checker, or replaces the
workflow step with `true` obtains the required `hardening` status — every one was executed
and passed (`tests/test_delta_adds_no_debt_v1.py` names the class; the scratch PRs #240 and
#241 carried the GitHub-side proofs). The VALIDATOR CHANGED line is disclosure for a reviewer,
not prevention. Non-bypass is an IDENTITY boundary the repository cannot hold: a reviewer
the coding agent is not, and a token that cannot administer the repository or push workflow
files (GOV-REMOTE-ENFORCEMENT in OPEN_ITEMS.md).

What it decides, entirely:
  1. no enforced check reports MORE violations on the candidate than on the base;
  2. no enforced check the base declared is missing from the candidate's roster unless the
     candidate DECLARES the retirement in `RETIRED_CHECKS` of the checker itself (RC-391:
     deleting the failing check is not paying the debt; the declaration makes the removal
     visible in the same diff a reviewer reads — "folded into <survivor>" in the reason moves
     the retired check's standing debt to the survivor instead of counting it as new);
  3. every `governance/root_cause_log.md` row the delta CLOSES cites an interpreter-led
     command that EXITS 0 when executed in the candidate tree (RC-540: closure was a regex;
     RC-545: the rule must run on the delta that introduces it, so it runs here, in ordinary
     CI, on candidate code).
When the candidate changed the checker itself, the counts are measured by the candidate's
own predicates on both trees; that is printed loudly so review reads the predicate diff.

DELETED 2026-09-10 (RC-546): the `--trusted` lane, the trust-anchor overlay, the acceptance
contract and its monotonicity rule. The overlay ran the base checker on a candidate tree whose
root modules (db_authority, …) the checker imports and the anchor walk never followed —
candidate code under a "trusted" label — and the contract froze SCOPE/PARENT ownership. The
repository cannot defend the predicate against its own credential (RC-539); review of the
checker diff and required checks are the boundary that actually exists.
"""
from __future__ import annotations

import argparse
import ast
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: `FAIL [name] (ENFORCED) — N violation(s):`  — the em dash varies by console encoding.
_FAIL_RE = re.compile(r"FAIL \[([a-z_0-9]+)\].*?(\d+) violation")
#: The gate prints this on every completed run; its ABSENCE means the run died.
_BANNER = "INSTITUTIONAL CORRECTNESS GATE:"
#: The gate's OWN total, which the per-check parse must reconcile with (RC-390).
_TOTAL_RE = re.compile(r"GATE: FAIL \((\d+) enforced violation")

#: A count comparison alone cannot tell "the same violation persisted" from "a different
#: violation appeared" under the same check while the count happens not to change — fix one,
#: introduce another, and 1 -> 1 reads as clean. `Violation.__str__` already prints
#: `  {path}:{line}  {msg}` for every violation the checker's own _MAX_PRINT cap allows, so the
#: identity for that is already ON STDOUT; nothing needs to change in the checker itself.
#: A PASS/FAIL header line for a check, and one violation line under it.
_CHECK_HEADER_RE = re.compile(r"^(?:FAIL|PASS) \[([a-z_0-9]+)\]")
_VIOLATION_LINE_RE = re.compile(r"^  (.+):(\d+)  (.+)$")
#: The checker's own truncation note ("  … and N more") — printed instead of the remaining
#: violation lines once a check exceeds its _MAX_PRINT cap.
_TRUNCATED_RE = re.compile(r"^  … and \d+ more$")

CHECKER_REL = "tools/check_institutional_correctness.py"
_LEDGER_REL = "governance/root_cause_log.md"

#: Variables that BIND git to a specific repository, index or object store. A pre-commit hook
#: exports several and children inherit them; RC-391 measured `git diff --cached` inside a
#: fresh measurement worktree reading the CALLER'S index. The worktrees are the isolation.
_GIT_BINDING_VARS = (
    "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_NAMESPACE",
    "GIT_PREFIX", "GIT_CEILING_DIRECTORIES", "GIT_INDEX_VERSION",
)


def _clean_env() -> dict[str, str]:
    """The ambient environment with every repository binding removed."""
    return {k: v for k, v in os.environ.items() if k not in _GIT_BINDING_VARS}


def _run(args: list[str], cwd: Path | None = None, timeout: int = 3600,
         env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, cwd=str(cwd or REPO), capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False, timeout=timeout,
        env=env if env is not None else _clean_env(),
    )


def parse_counts(stdout: str) -> dict[str, int]:
    return {m.group(1): int(m.group(2)) for m in _FAIL_RE.finditer(stdout)}


def parse_violation_identities(stdout: str) -> dict[str, tuple[frozenset[tuple[str, str]], bool]]:
    """{check: (identities, truncated)} from the SAME stdout parse_counts reads. An identity is
    (path, msg) — the LINE NUMBER is deliberately excluded: an unrelated edit elsewhere in the
    file that shifts a violation down a few lines is not a new violation, and comparing on line
    would fail ordinary development that never touched the violating code. `truncated` is True
    when the checker's own _MAX_PRINT cap hid some of this check's violations — the identity set
    is then incomplete, and the caller must not read a missing identity as proof of absence."""
    out: dict[str, tuple[set[tuple[str, str]], bool]] = {}
    current: str | None = None
    for line in stdout.splitlines():
        header = _CHECK_HEADER_RE.match(line)
        if header:
            current = header.group(1)
            out.setdefault(current, (set(), False))
            continue
        if current is None:
            continue
        if _TRUNCATED_RE.match(line):
            ids, _ = out[current]
            out[current] = (ids, True)
            continue
        v = _VIOLATION_LINE_RE.match(line)
        if v:
            ids, truncated = out[current]
            ids.add((v.group(1), v.group(3)))
            out[current] = (ids, truncated)
    return {name: (frozenset(ids), truncated) for name, (ids, truncated) in out.items()}


def identity_regressions(
        base: dict[str, tuple[frozenset[tuple[str, str]], bool]],
        head: dict[str, tuple[frozenset[tuple[str, str]], bool]]) -> list[str]:
    """Checks where HEAD reports a violation identity BASE's set for that check does not
    contain — a SUBSTITUTION the count comparison alone misses (fix violation A, introduce
    different violation B under the same check: count stays 1 -> 1). Skipped when either side's
    set for that check was truncated by the checker's own _MAX_PRINT cap: an incomplete set
    cannot prove a new identity is genuinely new, and the unconditional count comparison in
    `compare()` already refuses a truncated check's total from growing regardless."""
    out: list[str] = []
    for name in sorted(set(base) & set(head)):
        base_ids, base_truncated = base[name]
        head_ids, head_truncated = head[name]
        if base_truncated or head_truncated:
            continue
        new = head_ids - base_ids
        if new:
            examples = "; ".join(f"{p}:{m}" for p, m in sorted(new)[:3])
            more = f" (+{len(new) - 3} more)" if len(new) > 3 else ""
            out.append(f"  {name}: {len(new)} violation(s) not present on base{more} — {examples}")
    return out


# ── the checker's declarations, read STATICALLY (the candidate is data here) ────────────
def _checker_literals(source: str) -> tuple[set[str], dict[str, str]]:
    """(enforced check names from `CHECKS = [(name, fn, enforced), ...]`,
        {retired check: reason} from `RETIRED_CHECKS = {...}`), by AST — no import."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set(), {}
    enforced: set[str] = set()
    retired: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.AnnAssign):                 # `RETIRED_CHECKS: dict[str, str] = {...}`
            targets = {node.target.id} if isinstance(node.target, ast.Name) else set()
        elif isinstance(node, ast.Assign):
            targets = {t.id for t in node.targets if isinstance(t, ast.Name)}
        else:
            continue
        if node.value is None:
            continue
        if "CHECKS" in targets and isinstance(node.value, ast.List):
            for elt in node.value.elts:
                if isinstance(elt, ast.Tuple) and len(elt.elts) >= 3:
                    nm, en = elt.elts[0], elt.elts[2]
                    if isinstance(nm, ast.Constant) and isinstance(nm.value, str) \
                            and isinstance(en, ast.Constant) and en.value is True:
                        enforced.add(nm.value)
        elif "RETIRED_CHECKS" in targets and isinstance(node.value, ast.Dict):
            for k, v in zip(node.value.keys, node.value.values):
                if isinstance(k, ast.Constant) and isinstance(v, ast.Constant):
                    retired[str(k.value)] = str(v.value)
    return enforced, retired


def enforced_roster(wt: Path) -> set[str]:
    """The enforced names declared by CHECKS in the tree at `wt`. An absent checker or an
    empty roster is a broken read (it would let every check removal pass)."""
    p = wt / CHECKER_REL
    if not p.is_file():
        raise RuntimeError(f"{CHECKER_REL} missing in {wt}; an absent checker is not an empty roster")
    names, _ = _checker_literals(p.read_text(encoding="utf-8", errors="replace"))
    if not names:
        raise RuntimeError(
            f"the enforced-check roster came back EMPTY for {wt}. CHECKS has enforced entries "
            f"by construction, so an empty read is a broken read, and a broken read would let "
            f"every check removal pass.")
    return names


def declared_retirements(wt: Path) -> dict[str, str]:
    """{check: reason} the tree at `wt` declares retired in the checker's RETIRED_CHECKS."""
    p = wt / CHECKER_REL
    if not p.is_file():
        return {}
    return _checker_literals(p.read_text(encoding="utf-8", errors="replace"))[1]


_FOLD_RE = re.compile(r"folded into ([a-z][a-z0-9_]*)")


# ── materialised clean trees ────────────────────────────────────────────────────────────
class Worktrees:
    """Clean detached worktrees for one run; removed on close."""

    def __init__(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="deltagate-"))
        self.paths: list[Path] = []

    def add(self, ref: str, name: str) -> Path:
        wt = self.tmp / name
        add = _run(["git", "worktree", "add", "--detach", str(wt), ref])
        if add.returncode != 0:
            raise RuntimeError(f"cannot materialise {ref}: {add.stderr[-300:]}")
        self.paths.append(wt)
        return wt

    def close(self) -> None:
        for wt in self.paths:
            _run(["git", "worktree", "remove", "--force", str(wt)])
        shutil.rmtree(self.tmp, ignore_errors=True)
        _run(["git", "worktree", "prune"])


def _stage(wt: Path, base_ref: str) -> None:
    """Make the delta `base_ref..HEAD` appear STAGED inside `wt` (RC-391, second order):
    staged-scope checks ask `git diff --cached` what is being committed, and in a plain
    materialised worktree that answers EMPTY. The caller passes the BASE the delta is judged
    against, never the candidate's parent (RC-548): a PR is several commits, and on a
    `pull_request` run the candidate is the merge commit whose parent IS the base, so
    `HEAD^` staged the whole delta in CI and only the tip commit locally — two answers."""
    reset = _run(["git", "reset", "--soft", base_ref], cwd=wt)
    if reset.returncode != 0:
        raise RuntimeError(f"cannot stage the delta in the worktree: {reset.stderr[-300:]}")


def run_gate(wt: Path, ref_label: str
             ) -> tuple[dict[str, int], dict[str, tuple[frozenset[tuple[str, str]], bool]]]:
    """Run the institutional gate that lives IN `wt`; ({check: violations}, {check: (violation
    identities, truncated)}), fail-closed on a crashed, silent or unparseable run (H1 / RC-390)."""
    proc = _run([sys.executable, "tools/check_institutional_correctness.py", "--enforced-only"], cwd=wt)
    if proc.returncode not in (0, 1) or _BANNER not in proc.stdout:
        raise RuntimeError(
            f"gate did not complete for {ref_label} (rc={proc.returncode}, banner "
            f"{'present' if _BANNER in proc.stdout else 'MISSING'}). Refusing to "
            f"report a count: silence is not cleanliness.\n"
            f"--- tail ---\n{(proc.stdout or proc.stderr)[-600:]}")
    counts = parse_counts(proc.stdout)
    declared = _TOTAL_RE.search(proc.stdout)
    if declared:
        total = int(declared.group(1))
        if total and not counts:
            raise RuntimeError(
                f"gate declared {total} enforced violation(s) for {ref_label} but the "
                f"per-check parser matched NONE — output format has drifted. An "
                f"unreadable FAIL is not a clean tree.")
        if sum(counts.values()) != total:
            raise RuntimeError(
                f"parsed {sum(counts.values())} violation(s) for {ref_label} but the gate "
                f"declared {total}; parser and authority disagree, refusing both.")
    return counts, parse_violation_identities(proc.stdout)


def enforced_counts(ref: str) -> tuple[dict[str, int], dict[str, tuple[frozenset[tuple[str, str]], bool]],
                                        str, set[str]]:
    """({check: violations}, {check: (violation identities, truncated)}, short sha, enforced
    roster) of `ref`, measured in a CLEAN worktree."""
    sha = _run(["git", "rev-parse", "--short", ref]).stdout.strip()
    wts = Worktrees()
    try:
        wt = wts.add(ref, "wt")
        counts, identities = run_gate(wt, ref)
        return counts, identities, sha, enforced_roster(wt)
    finally:
        wts.close()


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


def removed_enforced_checks(base_roster: set[str], head_roster: set[str]) -> list[str]:
    """Enforced checks the base declared and the candidate no longer does (RC-391)."""
    return sorted(base_roster - head_roster)


def split_removals(removed: list[str], declared: set[str]) -> tuple[list[str], list[str]]:
    """(retired, still_blocked). A declaration affects ONLY removal accounting — the counts
    comparison never consults it, so it cannot excuse a violation being ADDED."""
    retired = [n for n in removed if n in declared]
    blocked = [n for n in removed if n not in declared]
    return retired, blocked


def refold_base_counts(base_counts: dict[str, int], folds: dict[str, str],
                       retired: set[str], head_roster: set[str]) -> tuple[dict[str, int], list[str]]:
    """Re-attribute the base's standing debt of a retired-and-folded check to its declared
    survivor. Fail-closed: only checks actually RETIRED by this delta move; the survivor must
    be ENFORCED on the candidate side; only the BASE side is rebucketed, by exactly the count
    it carried, so anything ADDED beyond the move still fails compare()."""
    out = dict(base_counts)
    moved: list[str] = []
    for name in sorted(retired):
        survivor = folds.get(name)
        if not survivor or survivor not in head_roster:
            continue
        count = out.pop(name, 0)
        if not count:
            continue
        out[survivor] = out.get(survivor, 0) + count
        moved.append(f"  {name}: {count} standing violation(s) re-attributed to {survivor}")
    return out, moved


# ── closure commands: a closing ledger row cites one, and it runs here ─────────────────
_BACKTICK_RE = re.compile(r"`([^`]+)`")
#: INTERPRETER-LED, whole first word (a backticked `pytest.yml` is a file name; a bare
#: `tools/x.py` is a file MENTION — the first run of this rule executed one as a command).
_EXECUTABLE_CMD_RE = re.compile(r"^\s*(?:\.venv[\\/]Scripts[\\/]python(?:\.exe)?|python3?|py|pytest|node|npm|npx)(?:\s|$)")
_INTERPRETER_RE = re.compile(r"^\s*(?:\.venv[\\/]Scripts[\\/]python(?:\.exe)?|python3?|py)(?=\s|$)")


def _show(ref: str, rel: str) -> str | None:
    r = _run(["git", "show", f"{ref}:{rel}"])
    return r.stdout if r.returncode == 0 else None


def closing_rows(base_text: str | None, cand_text: str) -> dict:
    """{rc_id: MissionRow} for rows CLOSED/REMEDIATED in the candidate ledger and not so in
    the base — parsed by the ONE ledger parser (tools.mission_latch.rows_from_text)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_mission_latch_for_gate", REPO / "tools/mission_latch.py")
    ml = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ml)  # type: ignore[union-attr]
    base = {r.rc_id: r.status for r in ml.rows_from_text(base_text or "")}
    return {r.rc_id: r for r in ml.rows_from_text(cand_text)
            if r.status in ("CLOSED", "REMEDIATED") and base.get(r.rc_id) not in ("CLOSED", "REMEDIATED")}


def executable_commands(row) -> list[str]:
    """Every CI-executable backticked command in a row's fix cell (a MissionRow, a row line,
    or the cell text)."""
    text = getattr(row, "fix", None)
    if text is None:
        cells = [c.strip() for c in str(row).strip().strip("|").split("|")]
        text = cells[6] if len(cells) >= 7 else str(row)
    return [c.strip() for c in _BACKTICK_RE.findall(text) if _EXECUTABLE_CMD_RE.match(c.strip())]


def run_closure_command(cmd: str, wt: Path, timeout: int = 900) -> tuple[int, str]:
    """Execute one cited command in `wt` with THIS interpreter substituted for the repo-venv
    spellings; the exit code is the proof."""
    text = cmd
    exe = shlex.quote(sys.executable) if os.name != "nt" else f'"{sys.executable}"'
    if _INTERPRETER_RE.match(text):
        text = _INTERPRETER_RE.sub(lambda _m: exe, text, count=1)
    elif text.startswith("pytest"):
        text = f'"{sys.executable}" -m {text}'
    try:
        r = subprocess.run(text, cwd=str(wt), shell=True, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout, env=_clean_env())
    except subprocess.TimeoutExpired:
        return 124, "timed out"
    return r.returncode, (r.stdout + r.stderr)[-800:]


def execute_closures(base_ref: str, cand_wt: Path) -> list[str]:
    """Run the first cited command of every row the delta closes, in the candidate tree.
    One line per failure (a row with no executable command fails too)."""
    cand_text = (cand_wt / _LEDGER_REL).read_text(encoding="utf-8", errors="replace")
    failures: list[str] = []
    for rc, row in sorted(closing_rows(_show(base_ref, _LEDGER_REL), cand_text).items()):
        cmds = executable_commands(row)
        if not cmds:
            failures.append(f"{rc} closes with no CI-executable command (python/pytest/node/npm) in its evidence cell")
            continue
        code, tail = run_closure_command(cmds[0], cand_wt)
        print(f"closure {rc}: `{cmds[0][:120]}` -> exit {code}")
        if code != 0:
            failures.append(f"{rc}: cited closure command exited {code}: {tail[-300:]}")
    return failures


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Fail if the candidate adds an enforced violation the base did not carry")
    ap.add_argument("--base", default="origin/main")
    args = ap.parse_args(argv)
    candidate_ref, candidate_label = "HEAD", "HEAD"

    base_counts, base_ids, base_sha, base_roster = enforced_counts(args.base)
    wts = Worktrees()
    try:
        cand_wt = wts.add(candidate_ref, "cand")
        _stage(cand_wt, args.base)                    # the whole delta since base appears STAGED
        head_sha = _run(["git", "rev-parse", "--short", candidate_ref]).stdout.strip()
        (head_counts, head_ids), head_roster = run_gate(cand_wt, candidate_label), enforced_roster(cand_wt)
        retirements = declared_retirements(cand_wt)
        retired, removed = split_removals(removed_enforced_checks(base_roster, head_roster), set(retirements))
        folds = {n: m.group(1) for n, why in retirements.items() if (m := _FOLD_RE.search(why))}
        base_counts, folded_moves = refold_base_counts(base_counts, folds, set(retired), head_roster)
        added, improved = compare(base_counts, head_counts)
        substituted = identity_regressions(base_ids, head_ids)
        checker_changed = _run(["git", "diff", "--quiet", f"{args.base}", candidate_ref, "--", CHECKER_REL]).returncode != 0
        closure_failures = execute_closures(args.base, cand_wt)
    finally:
        wts.close()

    print(f"base {args.base} ({base_sha}): {sum(base_counts.values())} enforced "
          f"across {len(base_counts)} check(s), {len(base_roster)} enforced check(s) declared")
    print(f"{candidate_label} ({head_sha}): {sum(head_counts.values())} enforced "
          f"across {len(head_counts)} check(s), {len(head_roster)} enforced check(s) declared")
    if checker_changed:
        print(f"\nVALIDATOR CHANGED: {CHECKER_REL} differs from {args.base}. Every count above was "
              f"measured by each tree's OWN predicates; a weakened predicate reads as a paydown. "
              f"Review the checker diff — nothing mechanical can certify it.")
    if improved:
        print("\nPAID DOWN by this delta:")
        print("\n".join(improved))
    if folded_moves:
        print("\nFOLDED by retirement declared in the checker's RETIRED_CHECKS:")
        print("\n".join(folded_moves))
    if retired:
        print("\nRETIRED by declaration in the checker's RETIRED_CHECKS (visible in this diff):")
        print("\n".join(f"  {name}: {retirements[name]}" for name in retired))
    if not added and not substituted and not removed and not closure_failures:
        print("\n[PASS] this delta adds no enforced violation the base did not already carry, "
              "removes no undeclared enforced check, and every row it closes ran its cited "
              "command to exit 0.")
        return 0
    if added:
        print("\n[FAIL] this delta ADDS enforced violations — not done, whatever the "
              "hand-written tests say:")
        print("\n".join(f"  {a.strip()}" for a in added))
    if substituted:
        print("\n[FAIL] this delta SUBSTITUTES a different enforced violation under an "
              "unchanged count — fixing one and introducing another is not paying the debt:")
        print("\n".join(substituted))
    if removed:
        print("\n[FAIL] this delta REMOVES enforced check(s) from the CHECKS roster without "
              f"declaring the retirement in RETIRED_CHECKS of {CHECKER_REL}. Deleting the check "
              "that fails is not paying the debt:")
        print("\n".join(f"  {name}" for name in removed))
    if closure_failures:
        print("\n[FAIL] a ledger row this delta CLOSES did not prove its closure by execution:")
        print("\n".join(f"  {f}" for f in closure_failures))
    return 1


if __name__ == "__main__":
    sys.exit(main())
