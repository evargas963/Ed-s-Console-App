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
    python tools/check_delta_adds_no_debt.py --trusted --candidate <ref> [--branch <name>]

RC-391 added the two things the pre-commit seam needs from it:
  * --index measures the EXACT staged index, not HEAD. At pre-commit, HEAD is the commit
    you are adding to, so it cannot see the change being made; the working tree sees too
    much. Only the index is the commit.
  * The enforced-check ROSTER is compared as well as the counts, read from the existing
    authority (check_institutional_correctness.CHECKS) on each side. Counts alone cannot
    tell "fixed the violations" from "deleted the check", and the second reads as a large
    paydown.

UNIVERSAL_QUANTITATIVE_CLOSURE_AND_NON_BYPASS_V1 (2026-09-10, RC-539/RC-540) made this the
TRUSTED cross-tree judge (`--trusted`, run from the BASE branch's copy of this file by
.github/workflows/trusted-closure.yml):
  * the candidate is judged by the BASE validator — the base's trust-anchor files
    (governance.acceptance.trust_anchor_paths, derived from the enforcement wiring) are
    overlaid onto a copy of the candidate tree before the institutional gate runs, so a
    predicate weakened in the candidate never judges the candidate;
  * a candidate change to any trust anchor needs a base-side AUTHORIZE row; when authorized,
    the candidate's validator must report no fewer violations than the base's on BOTH trees
    (a validator cannot certify its own weakening);
  * the BASE acceptance contract (OPEN_ITEMS.md Requirements) judges the candidate: rows
    may not be deleted or weakened, MERGE rows must PASS, PRODUCT rows may not regress;
  * escape markers the delta ADDS need a base-side `marker:` authorization;
  * ledger rows the delta CLOSES have their cited command EXECUTED here, exit 0 required;
  * the operating-process re-date rule runs here too (local hook parity).
Every result is reported as counts in the acceptance report; nothing is a percentage.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import importlib.util
import json
import os
import re
import shlex
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

CHECKER_REL = "tools/check_institutional_correctness.py"
# The institutional gate, the commit seam's roster reader and the operating-process lock are
# invoked below by LITERAL path inside the call that runs or loads them, so the local hook
# owners are demonstrably the remote owners (REQ-GOV-LOCAL-REMOTE-PARITY follows tool paths
# handed to calls, never mentions).

#: Variables that BIND git to a specific repository, index or object store. A pre-commit
#: hook runs with several of them exported, and they are inherited by every child process.
#: RC-391, measured: with the seam wired in, `git diff --cached` run INSIDE a freshly
#: materialised measurement worktree read the CALLER'S index, so a staged-scope check
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


# ── the enforced roster: ONE static reader (precommit_institutional._enforced_roster) ──
# RC-391 read the roster by EXECUTING each side's checker module. The trusted judge must
# read the candidate as DATA, so the roster is now the same static AST parse the commit
# seam uses — one reader, two callers (REQ-GOV-LOCAL-REMOTE-PARITY).
def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod             # dataclasses resolve the defining module through sys.modules
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def parse_roster(source: str) -> set[str]:
    """Enforced check names from the checker SOURCE; an empty read is a failed read."""
    seam = _load_module(REPO / "tools/precommit_institutional.py", "_precommit_institutional")
    names = seam._enforced_roster(source)
    if not names:
        raise RuntimeError(
            "the enforced-check roster came back EMPTY. check_institutional_correctness."
            "CHECKS has enforced entries by construction, so an empty read is a broken "
            "read, and a broken read would let every check removal pass.")
    return set(names)


def enforced_roster(wt: Path) -> set[str]:
    """The enforced names declared by CHECKS *in the materialised side at `wt`*."""
    p = wt / CHECKER_REL
    if not p.is_file():
        raise RuntimeError(f"{CHECKER_REL} missing in {wt}; an absent checker is not an empty roster")
    return parse_roster(p.read_text(encoding="utf-8", errors="replace"))


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


def _stage_the_delta(wt: Path, ref: str) -> None:
    """Make the candidate's own change appear STAGED inside its worktree.

    RC-391, second order. Staged-scope enforced checks ask `git diff --cached` what is
    being committed. In a materialised worktree HEAD is the candidate and the index matches it, so
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


def _stage_against(wt: Path, base_ref: str) -> None:
    """Stage the WHOLE branch delta (base..candidate) in `wt`, so staged-scope checks see
    every change the merge would land, not only the last commit (the trusted judge asks
    what the PR does, not what its tip commit does)."""
    reset = _run(["git", "reset", "--soft", base_ref], cwd=wt)
    if reset.returncode != 0:
        raise RuntimeError(f"cannot stage the branch delta in the worktree: {reset.stderr[-300:]}")


def run_gate(wt: Path, ref_label: str) -> dict[str, int]:
    """Run the institutional gate that lives IN `wt` and return {check: violations},
    fail-closed on a crashed or unparseable run."""
    proc = _run([sys.executable, "tools/check_institutional_correctness.py", "--enforced-only"], cwd=wt)
    # FAIL CLOSED (Cursor hole audit H1). As first shipped this returned
    # parse_counts(stdout) unconditionally, and parse_counts("") is {} — so a
    # crashed gate, an import error, or a changed output format rendered the side
    # as ZERO violations, printed PASS, and invented a "PAID DOWN" line. A lock
    # that cannot distinguish CLEAN from SILENT is the RC-90 class. The gate's own
    # summary banner is the proof it actually ran to completion.
    if proc.returncode not in (0, 1) or _BANNER not in proc.stdout:
        raise RuntimeError(
            f"gate did not complete for {ref_label} (rc={proc.returncode}, banner "
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
                f"gate declared {total} enforced violation(s) for {ref_label} but the "
                f"per-check parser matched NONE — output format has drifted. An "
                f"unreadable FAIL is not a clean tree.")
        if sum(counts.values()) != total:
            raise RuntimeError(
                f"parsed {sum(counts.values())} violation(s) for {ref_label} but the gate "
                f"declared {total}; parser and authority disagree, refusing both.")
    return counts


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
            return run_gate(wt, ref), sha, enforced_roster(wt)
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


# ── DECLARED RETIREMENT (RC-468; BASE-SIDE since the teardown, 2026-08-24) ──────────
# The roster comparison above refuses SILENT removal (RC-391). Before RC-468 it also
# refused DELIBERATE removal, which made the enforced set append-only forever — the
# governance surface could only grow, never be right-sized. RC-468's seam read the
# declaration from the CANDIDATE, which the operator identified as self-authorization: the
# same delta could declare a protection retired AND spend that declaration to pass this
# gate. The declaration is therefore honored ONLY from the BASE (origin/main): retiring
# a check is two operator-merged steps — (1) an ordinary delta adds the row (nothing is
# removed yet, the row is plainly visible in review), (2) a later delta removes the
# check, legalized by the row that is ALREADY on main. A candidate-side row excuses
# nothing. UNIVERSAL_QUANTITATIVE_CLOSURE_V1: the declaration is an `AUTHORIZE retire:`
# row of the OPEN_ITEMS.md Requirements contract — the ONE base-side grant mechanism
# (anchors, markers, waivers, retirements); the former governance/retired_checks.md
# manifest is git history.
def _base_contract_rows(ref: str) -> list:
    """The Requirements rows of the tree at `ref` (callers pass the BASE ref). A missing
    or unreadable contract declares nothing — fail-closed toward blocking."""
    proc = _run(["git", "show", f"{ref}:OPEN_ITEMS.md"], cwd=REPO)
    if proc.returncode != 0:
        return []
    A = _load_module(REPO / _ACCEPTANCE_REL, "_acceptance_for_grants")
    try:
        return A.parse_contract(proc.stdout)
    except A.ContractError:
        return []


def declared_retirements(ref: str) -> set[str]:
    """Names the tree at `ref` declares retired (`AUTHORIZE retire:<check>` rows)."""
    A = _load_module(REPO / _ACCEPTANCE_REL, "_acceptance_for_grants")
    return A.retirements(_base_contract_rows(ref))


def split_removals(removed: list[str], declared: set[str]) -> tuple[list[str], list[str]]:
    """(retired, still_blocked). Declaration affects ONLY removal accounting — the counts
    comparison never consults it, so a manifest row cannot excuse a violation being ADDED."""
    retired = [n for n in removed if n in declared]
    blocked = [n for n in removed if n not in declared]
    return retired, blocked


# ── DECLARED FOLD (SIMPLICITY REHAB consolidation, 2026-08-24) ──────────────────────
# A consolidation retires a check's REGISTRATION while its full validation keeps running
# inside a surviving check (e.g. rc_numeric_claims_cite_a_command inside root_cause_log).
# The violations do not go away — they move to the survivor's name — so a pure per-name
# count comparison reads the exact same standing debt as NEW debt on the survivor and
# blocks an honest consolidation. The `retire:` row that legalises the retirement also
# declares where the substance went ("... folded into <survivor> ..." in its criterion),
# so the fold is read from the SAME reviewed declaration and no second registry exists.
def declared_folds(ref: str) -> dict[str, str]:
    """{retired check: declared survivor} from the BASE contract's `retire:` rows whose
    criterion says 'folded into <survivor>'; nothing declared -> fail-closed toward blocking."""
    A = _load_module(REPO / _ACCEPTANCE_REL, "_acceptance_for_grants")
    return A.folds(_base_contract_rows(ref))


def refold_base_counts(
    base_counts: dict[str, int], folds: dict[str, str],
    retired: set[str], head_roster: set[str],
) -> tuple[dict[str, int], list[str]]:
    """Re-attribute the base's STANDING debt of a retired-and-folded check to its declared
    survivor, so a consolidation reads as the move it is rather than as new debt.

    Guardrails, each fail-closed toward blocking:
      * only checks actually RETIRED by this delta (removed from the roster AND declared in
        the manifest) are eligible — a fold phrase on a still-live check moves nothing;
      * the declared survivor must be ENFORCED on the candidate side — folding into a
        deleted or advisory check would launder the debt away, so it is refused;
      * only the BASE side is rebucketed, and only by the exact count the base carried, so
        any violation the candidate ADDS beyond the moved debt still fails compare().
    Returns (rebucketed_counts, human lines describing each move).
    """
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


# ═════════════════════════════════════════════════════════════════════════════════════
# TRUSTED JUDGE (UNIVERSAL_QUANTITATIVE_CLOSURE_AND_NON_BYPASS_V1)
# ═════════════════════════════════════════════════════════════════════════════════════
_ACCEPTANCE_REL = "governance/acceptance.py"
_LEDGER_REL = "governance/root_cause_log.md"
_LEDGER_ROW_RE = re.compile(r"^\|\s*(RC-\d+)\s*\|\s*([A-Z_]+)\s*\|")
_BACKTICK_RE = re.compile(r"`([^`]+)`")
#: Commands CI can execute as closure proof. Live probes (curl, SELECT, sqlite3 on the
#: production DB, PowerShell) are evidence of a session, not of the tree.
_EXECUTABLE_CMD_RE = re.compile(r"^\s*(?:\.venv[\\/]Scripts[\\/]python(?:\.exe)?|python3?|py|pytest|node|npm|npx|tools/)\b")
_INTERPRETER_RE = re.compile(r"^\s*(?:\.venv[\\/]Scripts[\\/]python(?:\.exe)?|python3?|py)\b")


class Worktrees:
    """Materialised clean trees for the trusted run; removed on exit."""

    def __init__(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="trusted-"))
        self.paths: list[Path] = []

    def add(self, ref: str, name: str) -> Path:
        wt = self.tmp / name
        add = _run(["git", "worktree", "add", "--detach", str(wt), ref])
        if add.returncode != 0:
            raise RuntimeError(f"cannot materialise {ref}: {add.stderr[-300:]}")
        self.paths.append(wt)
        return wt

    def copy(self, src: Path, name: str) -> Path:
        """A second copy of a materialised tree (same git dir binding via .git file)."""
        dst = self.tmp / name
        shutil.copytree(src, dst, symlinks=True)
        self.paths.append(dst)
        return dst

    def close(self) -> None:
        for wt in self.paths:
            _run(["git", "worktree", "remove", "--force", str(wt)])
        shutil.rmtree(self.tmp, ignore_errors=True)
        _run(["git", "worktree", "prune"])


def overlay(src_root: Path, dst_root: Path, rels: list[str]) -> list[str]:
    """Copy `rels` from src_root over dst_root (mkdir as needed). Returns what was copied.
    A path absent in src is left as the destination has it (the base declares no opinion)."""
    copied = []
    for rel in rels:
        s = src_root / rel
        if not s.is_file():
            continue
        d = dst_root / rel
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(s, d)
        copied.append(rel)
    return copied


def _diff_names(base_ref: str, cand_ref: str, paths: list[str] | None = None) -> list[str]:
    args = ["git", "diff", "--name-only", f"{base_ref}..{cand_ref}"]
    if paths:
        args += ["--", *paths]
    r = _run(args)
    if r.returncode != 0:
        raise RuntimeError(f"git diff failed: {r.stderr[-300:]}")
    return [l.strip().replace("\\", "/") for l in r.stdout.splitlines() if l.strip()]


def _show(ref: str, rel: str) -> str | None:
    r = _run(["git", "show", f"{ref}:{rel}"])
    return r.stdout if r.returncode == 0 else None


def _branch_name(explicit: str | None) -> str:
    if explicit:
        return explicit
    for var in ("GITHUB_HEAD_REF",):
        if os.environ.get(var):
            return os.environ[var]
    r = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    return r.stdout.strip() if r.returncode == 0 else ""


def _auth_matches(auths, kind: str, subject: str, branch: str, token: str | None = None) -> bool:
    """A base-side AUTHORIZE row covers (kind, subject, branch)."""
    for a in auths:
        parts = a.scope.split(":", 1)
        if len(parts) != 2 or parts[0] != kind:
            continue
        body = parts[1]
        if kind == "anchor":
            pat, _, br = body.partition("@")
            if fnmatch.fnmatch(subject, pat) and (br in ("*", branch)):
                return True
        elif kind == "marker":
            tok, _, rest = body.partition("@")
            pat, _, br = rest.partition("@")
            if token == tok and fnmatch.fnmatch(subject, pat) and (br in ("*", branch)):
                return True
    return False


def marker_tokens(checker_source: str) -> set[str]:
    """Every escape token the base gate honours, read from the gate's own source: string
    constants shaped `<word>-ok` (plus `OUT-OF-SCOPE`, the universal-scope escape)."""
    toks = set(re.findall(r"['\"]([a-z][a-z0-9\-]*-ok)['\"]", checker_source))
    toks |= set(re.findall(r"#\s*([a-z][a-z0-9\-]*-ok)\s*:", checker_source))
    toks.add("OUT-OF-SCOPE")
    return toks


def added_marker_lines(base_ref: str, cand_ref: str, tokens: set[str]) -> list[tuple[str, int, str]]:
    """(path, line, token) for every ADDED line in the delta carrying an escape token."""
    r = _run(["git", "diff", "-U0", f"{base_ref}..{cand_ref}"])
    if r.returncode != 0:
        raise RuntimeError(f"git diff failed: {r.stderr[-300:]}")
    out: list[tuple[str, int, str]] = []
    path, line = "", 0
    for ln in r.stdout.splitlines():
        if ln.startswith("+++ "):
            path = ln[4:].strip()
            path = path[2:] if path.startswith("b/") else path
            continue
        m = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)", ln)
        if m:
            line = int(m.group(1))
            continue
        if ln.startswith("+") and not ln.startswith("+++"):
            body = ln[1:]
            if path in (CHECKER_REL, "OPEN_ITEMS.md", _LEDGER_REL) or (path.startswith("governance/") and path.endswith(".md")):
                line += 1
                continue                      # the gate's own token table and prose are not escapes
            for tok in tokens:
                if tok in body:
                    out.append((path, line, tok))
                    break
            line += 1
    return out


def ledger_rows(text: str) -> dict[str, str]:
    return {m.group(1): m.group(2) for m in (_LEDGER_ROW_RE.match(l) for l in text.splitlines()) if m}


def closing_rows(base_text: str | None, cand_text: str) -> dict[str, str]:
    """{rc_id: full row} for rows that are CLOSED/REMEDIATED in the candidate and were not
    in the base (absent, or another status)."""
    base = ledger_rows(base_text or "")
    out: dict[str, str] = {}
    for line in cand_text.splitlines():
        m = _LEDGER_ROW_RE.match(line)
        if not m:
            continue
        rc, st = m.group(1), m.group(2)
        if st in ("CLOSED", "REMEDIATED") and base.get(rc) not in ("CLOSED", "REMEDIATED"):
            out[rc] = line
    return out


def executable_commands(row: str) -> list[str]:
    cells = [c.strip() for c in row.strip().strip("|").split("|")]
    evidence = cells[6] if len(cells) >= 7 else row
    return [c.strip() for c in _BACKTICK_RE.findall(evidence) if _EXECUTABLE_CMD_RE.match(c.strip())]


def run_closure_command(cmd: str, wt: Path, timeout: int = 900) -> tuple[int, str]:
    """Execute one cited command in the candidate tree with THIS interpreter substituted for
    the repo-venv spellings; the exit code is the proof."""
    text = cmd
    exe = shlex.quote(sys.executable) if os.name != "nt" else f'"{sys.executable}"'
    if _INTERPRETER_RE.match(text):
        # a callable replacement: a Windows interpreter path carries backslashes that a
        # replacement STRING would read as regex escapes (`\U` -> PatternError)
        text = _INTERPRETER_RE.sub(lambda _m: exe, text, count=1)
    elif text.startswith("pytest"):
        text = f'"{sys.executable}" -m {text}'
    elif text.startswith("tools/"):
        text = f'"{sys.executable}" {text}'
    try:
        r = subprocess.run(text, cwd=str(wt), shell=True, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout, env=_clean_env())
    except subprocess.TimeoutExpired:
        return 124, "timed out"
    return r.returncode, (r.stdout + r.stderr)[-800:]


def _obl(status: str, detail: str = "") -> dict:
    return {"status": status, "detail": detail}


def validator_weakening(base_roster: set[str], removed: list[str],
                        cand_self: dict[str, int], trusted_counts: dict[str, int],
                        cand_on_base: dict[str, int], base_counts: dict[str, int]) -> dict[str, str]:
    """{check: why} for every base check the CANDIDATE validator reports FEWER violations
    for than the BASE validator on the same tree — on the candidate tree (own vs trusted)
    or on the base tree (candidate validator vs base validator). A stricter validator
    reports more and is never flagged; a name-preserving gut (NC-09) reports fewer on the
    tree that carries what it stopped seeing."""
    out: dict[str, str] = {}
    for name in sorted(base_roster):
        if name in removed:
            continue
        weaker = []
        if cand_self.get(name, 0) < trusted_counts.get(name, 0):
            weaker.append(f"candidate tree: own {cand_self.get(name, 0)} < base validator {trusted_counts.get(name, 0)}")
        if cand_on_base.get(name, 0) < base_counts.get(name, 0):
            weaker.append(f"base tree: candidate validator {cand_on_base.get(name, 0)} < base validator {base_counts.get(name, 0)}")
        if weaker:
            out[name] = "; ".join(weaker)
    return out


def trusted_main(args) -> int:
    branch = _branch_name(args.branch)
    base_ref = args.base
    cand_ref = args.candidate or "HEAD"
    base_sha = _run(["git", "rev-parse", base_ref]).stdout.strip()
    cand_sha = _run(["git", "rev-parse", cand_ref]).stdout.strip()
    if not base_sha or not cand_sha:
        print(f"[FAIL] cannot resolve base {base_ref!r} or candidate {cand_ref!r}")
        return 1
    print(f"TRUSTED CLOSURE: base {base_ref} ({base_sha[:8]}) judges candidate {cand_ref} ({cand_sha[:8]}) on branch {branch!r}")
    blocks: list[str] = []
    injected: dict[str, dict] = {}
    wts = Worktrees()
    try:
        base_wt = wts.add(base_sha, "base")
        cand_wt = wts.add(cand_sha, "cand")
        _stage_against(cand_wt, base_sha)
        # BASE acceptance code. In CI this file itself runs from the base branch, so the copy
        # beside it IS the base's; a base that predates the module (the bootstrap delta that
        # introduces it) has none, and the judge's own copy is the only trusted one there is.
        acc_path = base_wt / _ACCEPTANCE_REL
        if not acc_path.is_file():
            acc_path = REPO / _ACCEPTANCE_REL
            print(f"BOOTSTRAP: base {base_sha[:8]} carries no {_ACCEPTANCE_REL}; the judge's own copy is used")
        A = _load_module(acc_path, "_base_acceptance")

        # ── contract (REPAIR 2) ──
        base_text = _show(base_sha, "OPEN_ITEMS.md") or ""
        cand_text = (cand_wt / "OPEN_ITEMS.md").read_text(encoding="utf-8", errors="replace")
        bootstrap = not A._SECTION_RE.search(base_text)
        try:
            cand_contract = A.parse_contract(cand_text)
        except A.ContractError as e:
            blocks.append(f"candidate OPEN_ITEMS.md contract unreadable: {e}")
            cand_contract = []
        if bootstrap:
            print("BOOTSTRAP: the base carries no Requirements contract; the candidate's contract is the trusted contract for this delta only.")
            base_contract = cand_contract
        else:
            base_contract = A.parse_contract(base_text)
        auths = A.authorizations(base_contract)
        regressions = A.contract_regressions(base_contract, cand_contract) if not bootstrap else []
        requests = A.candidate_only_grants(base_contract, cand_contract)
        base_reqs = [r.id for r in A.requirements(base_contract)]
        injected["REQ-GOV-CONTRACT-MONOTONIC"] = {
            "canonical": base_reqs,
            "obligations": {rid: (_obl("FAIL", "; ".join(x for x in regressions if x.startswith(rid + ":")))
                                  if any(x.startswith(rid + ":") for x in regressions) else _obl("PROVEN", "row intact"))
                            for rid in base_reqs},
            "notes": ([f"candidate-only grant requested, not effective: {r.id} {r.scope}" for r in requests]
                      + (["bootstrap: base carries no contract"] if bootstrap else [])),
        }
        for x in regressions:
            blocks.append(f"acceptance contract weakened by the candidate: {x}")

        # ── trust anchors (REPAIR 3) ──
        try:
            anchors = A.trust_anchor_paths(base_wt)
        except LookupError as e:
            # the base predates an owner the derivation asks for (bootstrap): the anchors
            # are what the base can enumerate about itself, never less than the judge's set
            print(f"BOOTSTRAP: base cannot enumerate every anchor owner ({e}); using the judge's derivation on the base tree where it resolves")
            anchors = sorted({".pre-commit-config.yaml", CHECKER_REL, "tools/check_delta_adds_no_debt.py"} |
                             set(A.workflow_files(base_wt)) | set("/".join(p) for _n, p in A.load_tree_module(base_wt, "tools.stop_chain").HOOK_WIRINGS))
            seen: set[str] = set()
            for a in list(anchors):
                if a.endswith(".py"):
                    A._tools_imports(base_wt, a, seen)
            anchors = sorted(set(anchors) | seen)
        changed_anchors = set(_diff_names(base_sha, cand_sha, anchors))
        # anchors the candidate ADDS under tools/ that base does not know are not anchors yet
        anchor_obl = {}
        for rel in anchors:
            if rel not in changed_anchors:
                anchor_obl[rel] = _obl("PROVEN", "identical to base")
            elif _auth_matches(auths, "anchor", rel, branch):
                anchor_obl[rel] = _obl("PROVEN", "changed; authorized by a base-side anchor: row")
            else:
                anchor_obl[rel] = _obl("BYPASS", "changed with NO base-side authorization")
                blocks.append(f"trust anchor {rel} changed without a base-side AUTHORIZE anchor: row")
        injected["REQ-GOV-TRUST-ANCHORS"] = {"canonical": anchors, "obligations": anchor_obl}

        # ── the judged tree: candidate data under the BASE validator ──
        judged = wts.copy(cand_wt, "judged")
        copied = overlay(base_wt, judged, anchors)
        print(f"judged tree: candidate + {len(copied)} base trust-anchor file(s) overlaid")
        base_counts = run_gate(base_wt, "base")
        base_roster = enforced_roster(base_wt)
        trusted_counts = run_gate(judged, "candidate (base validator)")
        cand_roster = enforced_roster(cand_wt)
        retired, removed = split_removals(removed_enforced_checks(base_roster, cand_roster),
                                          declared_retirements(base_ref))
        base_counts_f, folded = refold_base_counts(base_counts, declared_folds(base_ref), set(retired), cand_roster)
        added, improved = compare(base_counts_f, trusted_counts)
        roster_obl: dict[str, dict] = {}
        for name in sorted(base_roster):
            b, h = base_counts_f.get(name, 0), trusted_counts.get(name, 0)
            if name in removed:
                roster_obl[name] = _obl("BYPASS", "removed from the candidate roster without a base-side retirement row")
            elif h > b:
                roster_obl[name] = _obl("FAIL", f"{b} -> {h} under the base validator")
            else:
                roster_obl[name] = _obl("PROVEN", f"{b} -> {h} under the base validator")
        for a in added:
            blocks.append(f"adds enforced violation(s) under the BASE validator: {a.strip()}")
        for n in removed:
            blocks.append(f"removes enforced check {n} without a base-side retirement row")

        # ── validator monotonicity (only when a validator changed, and was authorized) ──
        validator_changed = any(rel.endswith(".py") for rel in changed_anchors)
        if validator_changed and not any(o["status"] == "BYPASS" for o in anchor_obl.values()):
            cand_self = run_gate(cand_wt, "candidate (own validator)")
            base_under_cand = wts.copy(base_wt, "base_under_cand")
            overlay(cand_wt, base_under_cand, [a for a in anchors if a.endswith(".py")])
            cand_on_base = run_gate(base_under_cand, "base (candidate validator)")
            for name, why in validator_weakening(base_roster, removed, cand_self, trusted_counts,
                                                 cand_on_base, base_counts).items():
                roster_obl[name] = _obl("BYPASS", "validator weakened: " + why)
                blocks.append(f"validator weakened for {name}: " + why)
            print("validator monotonicity measured on both trees (candidate validator vs base validator)")
        injected["REQ-GOV-TRUSTED-VALIDATOR"] = {"canonical": sorted(base_roster), "obligations": roster_obl,
                                                "notes": ([f"retired by base-side declaration: {', '.join(retired)}"] if retired else []) + folded}

        # ── escape markers (REPAIR 5) ──
        tokens = marker_tokens((base_wt / CHECKER_REL).read_text(encoding="utf-8", errors="replace"))
        added_markers = added_marker_lines(base_sha, cand_sha, tokens)
        marker_obl = {}
        for path, line, tok in added_markers:
            key = f"{path}:{line}:{tok}"
            if _auth_matches(auths, "marker", path, branch, token=tok):
                marker_obl[key] = _obl("PROVEN", "authorized by a base-side marker: row")
            else:
                marker_obl[key] = _obl("BYPASS", "escape marker added by the same delta with no base-side authorization")
                blocks.append(f"escape marker {tok} added at {path}:{line} without a base-side AUTHORIZE marker: row")
        injected["REQ-GOV-MARKER-AUTHORITY"] = {"canonical": sorted(marker_obl), "obligations": marker_obl}

        # ── closure commands execute (REPAIR 5) ──
        closing = closing_rows(_show(base_sha, _LEDGER_REL), (cand_wt / _LEDGER_REL).read_text(encoding="utf-8", errors="replace"))
        close_obl = {}
        for rc, row in sorted(closing.items()):
            cmds = executable_commands(row)
            if not cmds:
                close_obl[rc] = _obl("FAIL", "closes with no CI-executable command (python/pytest/node/tools/) in its evidence cell")
                blocks.append(f"{rc} closes without a CI-executable command; a live probe alone does not close a row")
                continue
            code, tail = run_closure_command(cmds[0], cand_wt)
            if code == 0:
                close_obl[rc] = _obl("PROVEN", f"executed `{cmds[0][:120]}` -> exit 0")
            else:
                close_obl[rc] = _obl("FAIL", f"executed `{cmds[0][:120]}` -> exit {code}: {tail[-300:]}")
                blocks.append(f"{rc}: cited closure command exited {code}")
        injected["REQ-GOV-CLOSURE-COMMANDS"] = {"canonical": sorted(closing), "obligations": close_obl}

        # ── operating-process re-date rule (local hook parity) ──
        opl = _load_module(base_wt / "tools/operating_process_lock.py", "_base_opl")
        redate = opl.rc_redate_violations(cand_wt)
        for msg in redate:
            blocks.append(f"re-date rule (operating_process_lock): {msg}")

        # ── evidence-class invariant: the owner's own falsifiers ──
        run, caught, fails = A.evidence_adversarial()
        injected["REQ-GOV-EVIDENCE-CLASS"] = {
            "canonical": ["evidence_status"], "adversarial_run": run, "adversarial_caught": caught,
            "obligations": {"evidence_status": _obl("PROVEN" if not fails else "FAIL", "; ".join(fails) or f"{caught}/{run} mutations caught")},
            "notes": fails,
        }
        if fails:
            blocks.append("evidence-class invariant: " + "; ".join(fails))

        # ── acceptance verdicts: candidate (base module, judged tree) vs base ──
        cand_verdicts = A.evaluate(judged, cand_contract, base_contract=base_contract, injected=injected)
        base_verdicts = {v.requirement.id: v for v in A.evaluate(base_wt, base_contract, base_contract=base_contract)} if not bootstrap else {}
        rank = {"PASS": 2, "NOT_PROVEN": 1, "FAIL": 0}
        for v in cand_verdicts:
            rid, gate = v.requirement.id, v.requirement.gate
            if gate == "MERGE" and v.verdict != "PASS":
                blocks.append(f"MERGE requirement {rid} is {v.verdict}")
            bv = base_verdicts.get(rid)
            if bv is not None and gate == "PRODUCT":
                if rank[v.verdict] < rank[bv.verdict] or v.missing > bv.missing or v.failed > bv.failed:
                    blocks.append(f"PRODUCT requirement {rid} regressed: base {bv.verdict} (missing {bv.missing}, fail {bv.failed}) -> candidate {v.verdict} (missing {v.missing}, fail {v.failed})")
        print("\n".join(A.report_lines(cand_verdicts)))
        if args.report_json:
            Path(args.report_json).write_text(json.dumps({
                "base": base_sha, "candidate": cand_sha, "branch": branch, "bootstrap": bootstrap,
                "blocks": blocks, "requests": [f"{r.id} {r.scope}" for r in requests],
                "improved": [i.strip() for i in improved],
                **A.report_json(cand_verdicts)}, indent=1), encoding="utf-8")
    finally:
        wts.close()

    if improved:
        print("\nPAID DOWN by this delta:")
        print("\n".join(improved))
    if requests:
        print("\nAUTHORIZATION/ACCEPT rows this candidate REQUESTS (inert until merged):")
        print("\n".join(f"  {r.id}: {r.scope}" for r in requests))
    if blocks:
        print("\n[FAIL] TRUSTED CLOSURE — this delta may not merge:")
        print("\n".join(f"  - {b}" for b in blocks))
        return 1
    print("\n[PASS] TRUSTED CLOSURE — every MERGE requirement PASS, no PRODUCT regression, no bypass.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Fail if the candidate adds an enforced violation the base did not carry")
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--index", action="store_true",
                    help="measure the exact staged INDEX (the pre-commit question) instead "
                         "of HEAD; unstaged work is structurally excluded")
    ap.add_argument("--trusted", action="store_true",
                    help="the trusted cross-tree judge: base validator + base contract judge the candidate")
    ap.add_argument("--candidate", default=None, help="candidate ref for --trusted (default HEAD)")
    ap.add_argument("--branch", default=None, help="candidate branch name for AUTHORIZE matching (default: GITHUB_HEAD_REF or the checked-out branch)")
    ap.add_argument("--report-json", default=None, help="write the acceptance report JSON here")
    args = ap.parse_args(argv)

    if args.trusted:
        return trusted_main(args)

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
    # TEARDOWN 2026-08-24: declarations are read from the BASE, never the candidate —
    # a delta cannot mint the authorization for its own protection-removal (two-step
    # contract: declare on main first, remove in a later delta).
    retired, removed = split_removals(
        removed_enforced_checks(base_roster, head_roster),
        declared_retirements(args.base))
    base_counts, folded_moves = refold_base_counts(
        base_counts, declared_folds(args.base), set(retired), head_roster)
    added, improved = compare(base_counts, head_counts)

    print(f"base {args.base} ({base_sha}): {sum(base_counts.values())} enforced "
          f"across {len(base_counts)} check(s), {len(base_roster)} enforced check(s) declared")
    print(f"{candidate_label} ({head_sha}): {sum(head_counts.values())} enforced "
          f"across {len(head_counts)} check(s), {len(head_roster)} enforced check(s) declared")
    if improved:
        print("\nPAID DOWN by this delta:")
        print("\n".join(improved))
    if folded_moves:
        print("\nFOLDED by consolidation declared in the base OPEN_ITEMS.md `retire:` rows "
              "(base-side standing debt re-attributed to the declared survivor — moved, "
              "not new, and anything ADDED beyond it still fails):")
        print("\n".join(folded_moves))
    if retired:
        print("\nRETIRED by base-side `AUTHORIZE retire:` rows in OPEN_ITEMS.md (RC-468):")
        print("\n".join(f"  {name}" for name in retired))
    if not added and not removed:
        tail = ("every removed check is declared retired by a base-side row"
                if retired else "removes no enforced check")
        print(f"\n[PASS] this delta adds no enforced violation the base did not already "
              f"carry, and {tail}.")
        return 0
    if added:
        print("\n[FAIL] this delta ADDS enforced violations — not done, whatever the "
              "hand-written tests say:")
        print("\n".join(f"  {a.strip()}" for a in added))
    if removed:
        print("\n[FAIL] this delta REMOVES enforced check(s) from the CHECKS roster "
              "without a base-side `AUTHORIZE retire:` row in OPEN_ITEMS.md. Deleting the "
              "check that fails is not paying the debt:")
        print("\n".join(f"  {name}" for name in removed))
    print("\nThese checks are already owned by the repo and encode failure modes this "
          "change's own tests did not imagine. Fix them, then re-run.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
