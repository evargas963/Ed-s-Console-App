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
    python tools/check_delta_adds_no_debt.py --index         # origin/main -> staged INDEX

RC-391 added the two things the pre-commit seam needs from it:
  * --index measures the EXACT staged index, not HEAD. At pre-commit, HEAD is the commit
    you are adding to, so it cannot see the change being made; the working tree sees too
    much. Only the index is the commit.
  * The enforced-check ROSTER is compared as well as the counts, read from the existing
    authority (check_institutional_correctness.CHECKS) on each side. Counts alone cannot
    tell "fixed the violations" from "deleted the check", and the second reads as a large
    paydown.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
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

#: The gate's OWN total, e.g. `... GATE: FAIL (56 enforced violation(s))`. This is the
#: authority my per-check parse must reconcile with (RC-390).
_TOTAL_RE = re.compile(r"GATE: FAIL \((\d+) enforced violation")


#: Read the ROSTER of enforced checks from a materialised side, using that side's OWN
#: `check_institutional_correctness.CHECKS` — the repo's existing authority on what is
#: enforced. RC-391: violation COUNTS alone cannot see a check being deleted or renamed;
#: a removed check reports 0 on the candidate side, which reads as a paydown. No second
#: registry is introduced: the roster IS CHECKS, read where it lives.
_ROSTER_CODE = (
    "import importlib.util,sys;"
    "s=importlib.util.spec_from_file_location('_cic','tools/check_institutional_correctness.py');"
    "m=importlib.util.module_from_spec(s);sys.modules['_cic']=m;s.loader.exec_module(m);"
    "print('ROSTER_BEGIN');"
    "print('\\n'.join(sorted(n for n,_f,e in m.CHECKS if e)));"
    "print('ROSTER_END')"
)


#: Variables that BIND git to a specific repository, index or object store. A pre-commit
#: hook runs with several of them exported, and they are inherited by every child process.
#: RC-391, measured: with the seam wired in, `git diff --cached` run INSIDE a freshly
#: materialised measurement worktree read the CALLER'S index, so `research_before_act`
#: reported the caller's staged files and the candidate scored +1 against its own base. The
#: worktrees are the isolation this tool is built on; an inherited GIT_INDEX_FILE silently
#: dissolves it, and the contamination reads as NEW DEBT, i.e. it blocks honest commits.
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


def parse_roster(stdout: str) -> set[str]:
    """Enforced check names between the sentinels; anything else is a failed read."""
    if "ROSTER_BEGIN" not in stdout or "ROSTER_END" not in stdout:
        raise RuntimeError(
            "could not read the enforced-check roster: the CHECKS sentinels are absent. "
            "An unreadable roster is not an empty roster — refusing to report one.")
    body = stdout.split("ROSTER_BEGIN", 1)[1].split("ROSTER_END", 1)[0]
    names = {line.strip() for line in body.splitlines() if line.strip()}
    if not names:
        raise RuntimeError(
            "the enforced-check roster came back EMPTY. check_institutional_correctness."
            "CHECKS has enforced entries by construction, so an empty read is a broken "
            "read, and a broken read would let every check removal pass.")
    return names


def enforced_roster(wt: Path) -> set[str]:
    """The enforced names declared by CHECKS *in the materialised side at `wt`*."""
    proc = _run([sys.executable, "-c", _ROSTER_CODE], cwd=wt)
    if proc.returncode != 0:
        raise RuntimeError(
            f"cannot read CHECKS roster (rc={proc.returncode}); silence is not an empty "
            f"roster.\n--- tail ---\n{(proc.stderr or proc.stdout)[-600:]}")
    return parse_roster(proc.stdout)


def index_candidate() -> str:
    """A dangling commit whose tree is the EXACT staged INDEX, parented on HEAD.

    The precommit question is "does what I am ABOUT TO COMMIT add debt?", and HEAD cannot
    answer it: HEAD is the previous commit, so a staged regression is invisible and a
    staged paydown is unseen. The working tree cannot answer it either — it carries
    unstaged scratch that is not part of the commit, which is the contaminated-measurement
    class this tool was built against.

    `write-tree` snapshots the index and nothing else, so additions, deletions and PARTIAL
    staging of a file are all honoured exactly as git will record them, and unstaged edits
    are structurally excluded. The commit is never referenced, so it leaves no branch, no
    tag and no moved HEAD behind.
    """
    # AMBIENT env here, deliberately, and nowhere else in this tool: git points a hook at
    # the index it is about to commit via GIT_INDEX_FILE, so the caller's bindings are
    # exactly what makes "the index" mean the right index. The measurement worktrees get
    # _clean_env() for the opposite reason — there, an inherited binding is contamination.
    env = dict(os.environ)
    # An unset committer identity must not be able to fail this gate open.
    env.update({
        "GIT_AUTHOR_NAME": "delta-gate", "GIT_AUTHOR_EMAIL": "delta-gate@local",
        "GIT_COMMITTER_NAME": "delta-gate", "GIT_COMMITTER_EMAIL": "delta-gate@local",
    })
    tree = _run(["git", "write-tree"], env=env)
    if tree.returncode != 0 or not tree.stdout.strip():
        raise RuntimeError(f"cannot snapshot the index: {tree.stderr[-300:]}")
    head = _run(["git", "rev-parse", "HEAD"], env=env)
    if head.returncode != 0 or not head.stdout.strip():
        raise RuntimeError(f"cannot resolve HEAD: {head.stderr[-300:]}")
    made = _run(["git", "commit-tree", tree.stdout.strip(), "-p", head.stdout.strip(),
                 "-m", "delta-gate index candidate (unreferenced)"], env=env)
    if made.returncode != 0 or not made.stdout.strip():
        raise RuntimeError(f"cannot build the index candidate: {made.stderr[-300:]}")
    return made.stdout.strip()


#: Evidence the enforced catalogue reads that lives OUTSIDE the tree — gitignored, local,
#: and therefore absent from any materialised worktree. `research_before_act` reads the turn
#: audit log; with it missing, that check fires on every candidate no matter what the change
#: is. Copied in, never written back.
_LOCAL_EVIDENCE = ("reports/turn_self_audit_log.jsonl",)


def _stage_the_delta(wt: Path, ref: str) -> None:
    """Make the candidate's own change appear STAGED inside its worktree.

    RC-391, second order. Several enforced checks — `research_before_act`,
    `check_recursive_five_why_front_loaded` — ask `git diff --cached` what is being
    committed. In a materialised worktree HEAD is the candidate and the index matches it, so
    that question answers EMPTY and those checks fall silent on both sides. They would then
    be structurally incapable of failing at the very seam they were written for, which is a
    check removed by accident rather than by edit — the thing the roster comparison exists
    to refuse. `reset --soft <parent>` moves HEAD back one commit and leaves the index
    holding the candidate tree, so `git diff --cached` is EXACTLY the change under commit.
    """
    parent = _run(["git", "rev-parse", "--verify", "--quiet", f"{ref}^"], cwd=wt)
    if parent.returncode != 0 or not parent.stdout.strip():
        raise RuntimeError(
            f"cannot resolve the parent of {ref}, so the change under commit cannot be "
            f"staged for the checks that ask what is being committed: {parent.stderr[-200:]}")
    reset = _run(["git", "reset", "--soft", parent.stdout.strip()], cwd=wt)
    if reset.returncode != 0:
        raise RuntimeError(f"cannot stage the delta in the worktree: {reset.stderr[-300:]}")


def _copy_local_evidence(wt: Path) -> None:
    for rel in _LOCAL_EVIDENCE:
        src = REPO / rel
        if src.is_file():
            dst = wt / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)


def enforced_counts(ref: str, stage_delta: bool = False) -> tuple[dict[str, int], str, set[str]]:
    """({check: violations}, short sha, enforced roster) measured in a CLEAN worktree.

    `stage_delta` is set for the CANDIDATE side only: the base carries no change, so its
    staged set is correctly empty, while the candidate's must be the change under commit.
    """
    sha = _run(["git", "rev-parse", "--short", ref]).stdout.strip()
    with tempfile.TemporaryDirectory(prefix="deltagate-") as tmp:
        wt = Path(tmp) / "wt"
        add = _run(["git", "worktree", "add", "--detach", str(wt), ref])
        if add.returncode != 0:
            raise RuntimeError(f"cannot materialise {ref}: {add.stderr[-300:]}")
        try:
            if stage_delta:
                _stage_the_delta(wt, ref)
            _copy_local_evidence(wt)
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
            counts = parse_counts(proc.stdout)
            # RC-390 — residual fail-open, found by Cursor AFTER the first H1 fix. The
            # banner and exit code prove the gate RAN; they do not prove I UNDERSTOOD it.
            # If the per-check regex misses (format drift, a renamed check), counts is {}
            # while the banner still says FAIL, and compare() then reports a fabricated
            # "71 -> 0 (-71)" and PASSES. Reproduced before fixing. The gate prints its own
            # total, so reconcile against it: a parse that disagrees with the authority is
            # a PARSE FAILURE, never a finding — and a silent misparse always reads in the
            # flattering direction.
            declared = _TOTAL_RE.search(proc.stdout)
            if declared:
                total = int(declared.group(1))
                if total and not counts:
                    raise RuntimeError(
                        f"gate declared {total} enforced violation(s) for {ref} but the "
                        f"per-check parser matched NONE — output format has drifted. An "
                        f"unreadable FAIL is not a clean tree.")
                if sum(counts.values()) != total:
                    raise RuntimeError(
                        f"parsed {sum(counts.values())} violation(s) for {ref} but the gate "
                        f"declared {total}; parser and authority disagree, refusing both.")
            return counts, sha, enforced_roster(wt)
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


def removed_enforced_checks(base_roster: set[str], head_roster: set[str]) -> list[str]:
    """Enforced checks the base declared and the candidate no longer does.

    RC-391 — the blind spot in a pure count comparison. Deleting a failing check, flipping
    it to advisory, or renaming it makes its count vanish from the candidate side, and the
    count comparison reads that as a PAYDOWN: it prints `-71` and passes. Removal of
    enforcement is the single most valuable thing to detect, so it must be measured on the
    roster, not inferred from counts. A rename is a removal plus an addition; the removal
    half blocks, so a rename cannot masquerade as a paydown either.
    """
    return sorted(base_roster - head_roster)



# ── BASE-SIDE CACHE (RC-466) ────────────────────────────────────────────────────────
# The base measurement is a pure function of: the base COMMIT (content-addressed), THIS
# driver file (its parsing regexes decide what a count is), the copied-in local evidence
# files, and the interpreter. Re-running it for an unchanged base was ~half the gate's
# wall time on every local invocation. The key covers every input; the CANDIDATE side is
# never cached (it changes each run by definition). Every cache failure falls back to a
# fresh measurement - the cache can cost seconds, never correctness.

def _base_cache_path() -> Path | None:
    r = _run(["git", "rev-parse", "--git-dir"])
    if r.returncode != 0 or not r.stdout.strip():
        return None
    git_dir = Path(r.stdout.strip())
    if not git_dir.is_absolute():
        git_dir = REPO / git_dir
    return git_dir / "delta_base_cache.json"


def _base_cache_key(base_ref: str) -> str | None:
    r = _run(["git", "rev-parse", base_ref])
    if r.returncode != 0 or not r.stdout.strip():
        return None
    h = hashlib.sha256()
    h.update(r.stdout.strip().encode())
    try:
        h.update(Path(__file__).read_bytes())          # parsing logic lives here
    except OSError:
        return None
    for rel in _LOCAL_EVIDENCE:                        # copied into the base worktree
        f = REPO / rel
        try:
            h.update(f.read_bytes() if f.is_file() else b"<absent>")
        except OSError:
            return None
    h.update(sys.version.encode())
    return h.hexdigest()


def _read_base_cache(key: str | None):
    if not key:
        return None
    path = _base_cache_path()
    try:
        if path is None or not path.is_file():
            return None
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("key") != key:
            return None
        counts = {str(k): int(v) for k, v in doc["counts"].items()}
        return counts, str(doc["sha"]), set(doc["roster"])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None                                    # fail-open: recompute


def _write_base_cache(key: str | None, counts, sha, roster) -> None:
    if not key:
        return
    path = _base_cache_path()
    if path is None:
        return
    try:
        path.write_text(json.dumps({
            "key": key, "counts": counts, "sha": sha, "roster": sorted(roster),
        }), encoding="utf-8")
    except OSError:
        pass                                           # cache is best-effort


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Fail if the candidate adds an enforced violation the base did not carry")
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--index", action="store_true",
                    help="measure the exact staged INDEX (the pre-commit question) instead "
                         "of HEAD; unstaged work is structurally excluded")
    args = ap.parse_args(argv)

    if args.index:
        candidate_ref, candidate_label = index_candidate(), "staged INDEX"
    else:
        candidate_ref, candidate_label = "HEAD", "HEAD"

    cache_key = _base_cache_key(args.base)
    cached = _read_base_cache(cache_key)
    if cached is not None:
        base_counts, base_sha, base_roster = cached
        print(f"base side: cache hit for {args.base} ({base_sha}) - re-measure with a "
              f"changed base/driver/evidence, or delete .git/delta_base_cache.json")
    else:
        base_counts, base_sha, base_roster = enforced_counts(args.base)
        _write_base_cache(cache_key, base_counts, base_sha, base_roster)
    head_counts, head_sha, head_roster = enforced_counts(candidate_ref, stage_delta=True)
    added, improved = compare(base_counts, head_counts)
    removed = removed_enforced_checks(base_roster, head_roster)

    print(f"base {args.base} ({base_sha}): {sum(base_counts.values())} enforced "
          f"across {len(base_counts)} check(s), {len(base_roster)} enforced check(s) declared")
    print(f"{candidate_label} ({head_sha}): {sum(head_counts.values())} enforced "
          f"across {len(head_counts)} check(s), {len(head_roster)} enforced check(s) declared")
    if improved:
        print("\nPAID DOWN by this delta:")
        print("\n".join(improved))
    if not added and not removed:
        print(f"\n[PASS] this delta adds no enforced violation the base did not already "
              f"carry, and removes no enforced check.")
        return 0
    if added:
        print("\n[FAIL] this delta ADDS enforced violations — not done, whatever the "
              "hand-written tests say:")
        print("\n".join(f"  {a.strip()}" for a in added))
    if removed:
        print("\n[FAIL] this delta REMOVES enforced check(s) from the CHECKS roster. "
              "Deleting the check that fails is not paying the debt:")
        print("\n".join(f"  {name}" for name in removed))
    print("\nThese checks are already owned by the repo and encode failure modes this "
          "change's own tests did not imagine. Fix them, then re-run.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
