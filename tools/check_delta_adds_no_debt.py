"""Did MY change add debt? Compare the enforced gate between a base and a candidate.

WHY THIS EXISTS (RC-387): tests an author writes only encode the failure modes that author
imagined; the repo already owns ~75 checks encoding modes nobody imagined, written by past
incidents. This points that surface at a delta and asks one question: does the candidate carry
any enforced violation the base did not? Two design choices decide whether it is useful:
CLEAN detached worktrees on both sides (a dirty tree carries scratch that is not the change),
and pre-existing violations reported SEPARATELY, never summed into a verdict.

Usage:
    python tools/check_delta_adds_no_debt.py                 # origin/main -> HEAD (the candidate lane)
    python tools/check_delta_adds_no_debt.py --base <ref>
    python tools/check_delta_adds_no_debt.py --index         # origin/main -> staged INDEX
    python tools/check_delta_adds_no_debt.py --trusted --candidate <ref> [--branch <name>]

TWO LANES, one file (UNIVERSAL_QUANTITATIVE_CLOSURE_V1, RC-539/RC-540; simplified 2026-09-10):

  CANDIDATE LANE (`--base`, run by .github/workflows/hardening.yml from the candidate's own
  code — ordinary untrusted CI): the count/roster comparison above, and the EXECUTION of every
  closure command a ledger row the delta CLOSES cites (exit 0 or the row does not close).
  Candidate code runs here by design; this lane proves the candidate's own claims run.

  TRUSTED LANE (`--trusted`, run by .github/workflows/trusted-closure.yml from the BASE
  branch's copy of this file): the base judges the candidate AS DATA. The base's trust-anchor
  files (`tools.precommit_institutional.trust_anchor_paths`, derived from the enforcement
  wiring) are overlaid onto a copy of the candidate before the institutional gate runs, so a
  predicate weakened in the candidate never judges the candidate; a candidate change to any
  anchor needs a base-side `AUTHORIZE anchor:` row; the BASE contract (OPEN_ITEMS.md
  Requirements) judges the candidate (rows may not be deleted or weakened, MERGE rows must
  PASS, PRODUCT rows may not regress); escape markers the delta ADDS need a base-side
  `marker:` row; a closing ledger row must CITE a CI-executable command (the candidate lane
  executes it); the re-date rule runs here too. No candidate code is executed in this lane.
  No bootstrap fallback: a base that carries no acceptance executor or no contract cannot
  judge, and the verdict is NOT_PROVEN — never a smaller population, never the judge's own copy.
"""
from __future__ import annotations

import argparse
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

#: `FAIL [name] (ENFORCED) — N violation(s):`  — the em dash varies by console encoding.
_FAIL_RE = re.compile(r"FAIL \[([a-z_0-9]+)\].*?(\d+) violation")
#: The gate prints this on every completed run; its ABSENCE means the run died.
_BANNER = "INSTITUTIONAL CORRECTNESS GATE:"
#: The gate's OWN total, which the per-check parse must reconcile with (RC-390).
_TOTAL_RE = re.compile(r"GATE: FAIL \((\d+) enforced violation")

CHECKER_REL = "tools/check_institutional_correctness.py"
_ACCEPTANCE_REL = "governance/acceptance.py"
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


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod             # dataclasses resolve the defining module through sys.modules
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _seam():
    """The commit seam beside THIS file: the ONE static roster reader and the enforcement-path
    population owner (tools/precommit_institutional.py)."""
    return _load_module(REPO / "tools/precommit_institutional.py", "_precommit_institutional")


def _acceptance(path: Path = REPO / _ACCEPTANCE_REL, name: str = "_acceptance_for_grants"):
    return _load_module(path, name)


def parse_counts(stdout: str) -> dict[str, int]:
    return {m.group(1): int(m.group(2)) for m in _FAIL_RE.finditer(stdout)}


def enforced_roster(wt: Path) -> set[str]:
    """The enforced names declared by CHECKS *in the materialised side at `wt`* — a STATIC
    parse by the commit seam's reader, never an executed candidate checker. An absent checker
    or an empty roster is a broken read (it would let every check removal pass)."""
    if not (wt / CHECKER_REL).is_file():
        raise RuntimeError(f"{CHECKER_REL} missing in {wt}; an absent checker is not an empty roster")
    try:
        return set(_seam().enforced_roster(wt))
    except LookupError as e:
        raise RuntimeError(f"the enforced-check roster came back EMPTY for {wt}: {e}") from e


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


def index_candidate() -> str:
    """A dangling commit whose tree is the EXACT staged INDEX, parented on HEAD (RC-391): the
    pre-commit question is "does what I am ABOUT TO COMMIT add debt?", which neither HEAD
    (the previous commit) nor the working tree (unstaged scratch) can answer."""
    # AMBIENT env here, deliberately: git points a hook at the index it is about to commit via
    # GIT_INDEX_FILE. The measurement worktrees get _clean_env() for the opposite reason.
    env = dict(os.environ)
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


def _stage(wt: Path, base_ref: str) -> None:
    """Make the delta `base_ref..HEAD` appear STAGED inside `wt` (RC-391, second order):
    staged-scope checks ask `git diff --cached` what is being committed, and in a plain
    materialised worktree that answers EMPTY. `reset --soft` moves HEAD to the base and
    leaves the index holding the candidate tree, so the staged set IS the delta."""
    reset = _run(["git", "reset", "--soft", base_ref], cwd=wt)
    if reset.returncode != 0:
        raise RuntimeError(f"cannot stage the delta in the worktree: {reset.stderr[-300:]}")


def run_gate(wt: Path, ref_label: str) -> dict[str, int]:
    """Run the institutional gate that lives IN `wt` and return {check: violations},
    fail-closed on a crashed, silent or unparseable run (H1 / RC-390)."""
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
    return counts


def enforced_counts(ref: str) -> tuple[dict[str, int], str, set[str]]:
    """({check: violations}, short sha, enforced roster) of `ref`, measured in a CLEAN worktree."""
    sha = _run(["git", "rev-parse", "--short", ref]).stdout.strip()
    wts = Worktrees()
    try:
        wt = wts.add(ref, "wt")
        return run_gate(wt, ref), sha, enforced_roster(wt)
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
    """Enforced checks the base declared and the candidate no longer does (RC-391): deleting,
    demoting or renaming a failing check reads as a PAYDOWN to a count comparison."""
    return sorted(base_roster - head_roster)


# ── DECLARED RETIREMENT (RC-468; BASE-SIDE) and DECLARED FOLD ───────────────────────────
# A retirement is legal only when an `AUTHORIZE retire:<check>` row is ALREADY on the base
# (two operator-merged steps; a candidate-side row excuses nothing). A `retire:` row whose
# criterion says `folded into <survivor>` re-attributes the base's standing debt of the
# retired check to the survivor, so a consolidation reads as the move it is.
def _base_contract_rows(ref: str) -> list:
    """The Requirements rows of the tree at `ref` (callers pass the BASE ref). A missing or
    unreadable contract declares nothing — fail-closed toward blocking."""
    proc = _run(["git", "show", f"{ref}:OPEN_ITEMS.md"], cwd=REPO)
    if proc.returncode != 0:
        return []
    A = _acceptance()
    try:
        return A.parse_contract(proc.stdout)
    except A.ContractError:
        return []


def declared_retirements(ref: str) -> set[str]:
    return _acceptance().retirements(_base_contract_rows(ref))


def declared_folds(ref: str) -> dict[str, str]:
    return _acceptance().folds(_base_contract_rows(ref))


def split_removals(removed: list[str], declared: set[str]) -> tuple[list[str], list[str]]:
    """(retired, still_blocked). Declaration affects ONLY removal accounting — the counts
    comparison never consults it, so a row cannot excuse a violation being ADDED."""
    retired = [n for n in removed if n in declared]
    blocked = [n for n in removed if n not in declared]
    return retired, blocked


def refold_base_counts(
    base_counts: dict[str, int], folds: dict[str, str],
    retired: set[str], head_roster: set[str],
) -> tuple[dict[str, int], list[str]]:
    """Re-attribute the base's standing debt of a retired-and-folded check to its declared
    survivor. Fail-closed guardrails: only checks actually RETIRED by this delta move; the
    survivor must be ENFORCED on the candidate side; only the BASE side is rebucketed, by
    exactly the count it carried, so anything ADDED beyond the move still fails compare()."""
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


# ── closure commands: a closing ledger row cites one; the candidate lane executes it ────
_BACKTICK_RE = re.compile(r"`([^`]+)`")
#: Commands CI can execute as closure proof: INTERPRETER-LED, and the interpreter must be the
#: whole first word (a backticked `pytest.yml` is a file name; the first hardening run of this
#: rule executed a backticked `tools/stop_chain.py` MENTION as a command, so a bare tools/ path
#: is a file name too — a tool is cited as `python tools/x.py`). Live probes (curl, SELECT,
#: PowerShell) are evidence of a session, not of the tree.
_EXECUTABLE_CMD_RE = re.compile(r"^\s*(?:\.venv[\\/]Scripts[\\/]python(?:\.exe)?|python3?|py|pytest|node|npm|npx)(?:\s|$)")
_INTERPRETER_RE = re.compile(r"^\s*(?:\.venv[\\/]Scripts[\\/]python(?:\.exe)?|python3?|py)(?=\s|$)")


def closing_rows(base_text: str | None, cand_text: str) -> dict:
    """{rc_id: MissionRow} for rows CLOSED/REMEDIATED in the candidate ledger and not so in the
    base ledger — parsed by the ONE ledger parser (tools.mission_latch.rows_from_text)."""
    ml = _load_module(REPO / "tools/mission_latch.py", "_mission_latch_for_gate")
    base = {r.rc_id: r.status for r in ml.rows_from_text(base_text or "")}
    return {r.rc_id: r for r in ml.rows_from_text(cand_text)
            if r.status in ("CLOSED", "REMEDIATED") and base.get(r.rc_id) not in ("CLOSED", "REMEDIATED")}


def executable_commands(row) -> list[str]:
    """Every CI-executable backticked command in a row's fix/evidence cell (a MissionRow, a
    full row line, or the cell text)."""
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
    """CANDIDATE LANE: run the first cited command of every row the delta closes, in the
    candidate tree. Returns one line per failure (a row with no executable command fails too)."""
    base_text = _show(base_ref, _LEDGER_REL)
    cand_text = (cand_wt / _LEDGER_REL).read_text(encoding="utf-8", errors="replace")
    failures: list[str] = []
    for rc, row in sorted(closing_rows(base_text, cand_text).items()):
        cmds = executable_commands(row)
        if not cmds:
            failures.append(f"{rc} closes with no CI-executable command (python/pytest/node/npm) in its evidence cell")
            continue
        code, tail = run_closure_command(cmds[0], cand_wt)
        print(f"closure {rc}: `{cmds[0][:120]}` -> exit {code}")
        if code != 0:
            failures.append(f"{rc}: cited closure command exited {code}: {tail[-300:]}")
    return failures


# ═════════════════════════════════════════════════════════════════════════════════════
# TRUSTED JUDGE — the base judges the candidate as DATA
# ═════════════════════════════════════════════════════════════════════════════════════
def overlay(src_root: Path, dst_root: Path, rels: list[str]) -> list[str]:
    """Copy `rels` from src_root over dst_root. A path absent in src is left as the
    destination has it (the base declares no opinion)."""
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
    if os.environ.get("GITHUB_HEAD_REF"):
        return os.environ["GITHUB_HEAD_REF"]
    r = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    return r.stdout.strip() if r.returncode == 0 else ""


def marker_tokens(checker_source: str) -> set[str]:
    """Every escape token the base gate honours, read from the gate's own source: string
    constants shaped `<word>-ok` (plus `OUT-OF-SCOPE`, the universal-scope escape)."""
    toks = set(re.findall(r"['\"]([a-z][a-z0-9\-]*-ok)['\"]", checker_source))
    toks |= set(re.findall(r"#\s*([a-z][a-z0-9\-]*-ok)\s*:", checker_source))
    toks.add("OUT-OF-SCOPE")
    return toks


_COMMENT_START_RE = re.compile(r"(?:#|//|<!--|/\*)")
#: Files whose text about markers is the mechanism, never an escape.
_MARKER_MECHANISM_FILES = {CHECKER_REL, "tools/check_delta_adds_no_debt.py", _ACCEPTANCE_REL}


def added_marker_lines(base_ref: str, cand_ref: str, tokens: set[str]) -> list[tuple[str, int, str]]:
    """(path, line, token) for every ADDED code line in the delta carrying an escape token IN
    A COMMENT — the only position where the gate honours one. A token in a string literal or
    in prose escapes nothing and is not counted."""
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
            skip = path in _MARKER_MECHANISM_FILES or path.endswith((".md", ".txt", ".json", ".jsonl", ".csv"))
            cm = None if skip else _COMMENT_START_RE.search(body)
            if cm is not None:
                comment = body[cm.start():]
                for tok in tokens:
                    if tok in comment:
                        out.append((path, line, tok))
                        break
            line += 1
    return out


def _obl(status: str, detail: str = "") -> dict:
    return {"status": status, "detail": detail}


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
    requests: list = []
    improved: list[str] = []
    wts = Worktrees()
    try:
        base_wt = wts.add(base_sha, "base")
        cand_wt = wts.add(cand_sha, "cand")
        _stage(cand_wt, base_sha)

        # ── the judge is the BASE's, or there is no judge ──
        acc_path = base_wt / _ACCEPTANCE_REL
        if not acc_path.is_file():
            print(f"\n[NOT_PROVEN] TRUSTED CLOSURE — base {base_sha[:8]} carries no {_ACCEPTANCE_REL}: "
                  f"the base cannot judge this candidate. Landing this delta is the operator's word, "
                  f"not a machine verdict.")
            return 1
        A = _acceptance(acc_path, "_base_acceptance")
        try:
            base_contract = A.parse_contract(_show(base_sha, "OPEN_ITEMS.md") or "")
        except A.ContractError as e:
            print(f"\n[NOT_PROVEN] TRUSTED CLOSURE — base {base_sha[:8]} carries no readable Requirements "
                  f"contract ({e}): the base cannot judge this candidate.")
            return 1
        try:
            cand_contract = A.parse_contract((cand_wt / "OPEN_ITEMS.md").read_text(encoding="utf-8", errors="replace"))
        except A.ContractError as e:
            blocks.append(f"candidate OPEN_ITEMS.md contract unreadable: {e}")
            cand_contract = []
        auths = A.authorizations(base_contract)

        # ── contract monotonicity ──
        regressions = A.contract_regressions(base_contract, cand_contract)
        requests = A.candidate_only_grants(base_contract, cand_contract)
        base_reqs = [r.id for r in A.requirements(base_contract)]
        injected["REQ-GOV-CONTRACT-MONOTONIC"] = {
            "canonical": base_reqs,
            "obligations": {rid: (_obl("FAIL", "; ".join(x for x in regressions if x.startswith(rid + ":")))
                                  if any(x.startswith(rid + ":") for x in regressions) else _obl("PROVEN", "row intact"))
                            for rid in base_reqs},
            "notes": [f"candidate-only grant requested, not effective: {r.id} {r.scope}" for r in requests],
        }
        for x in regressions:
            blocks.append(f"acceptance contract weakened by the candidate: {x}")

        # ── trust anchors: the base enumerates its own enforcement path, or NOT_PROVEN ──
        try:
            anchors = A.load_tree_module(base_wt, "tools.precommit_institutional").trust_anchor_paths(base_wt)
            anchor_resolved = True
        except (LookupError, AttributeError, A.ContractError) as e:
            anchors, anchor_resolved = [], False
            blocks.append(f"base {base_sha[:8]} cannot enumerate its trust anchors ({e}); the anchor "
                          f"population is NOT_PROVEN and no smaller population stands in for it")
        changed_anchors = set(_diff_names(base_sha, cand_sha, anchors)) if anchors else set()
        anchor_obl = {}
        for rel in anchors:
            if rel not in changed_anchors:
                anchor_obl[rel] = _obl("PROVEN", "identical to base")
            elif A.authorized(auths, "anchor", rel, branch):
                anchor_obl[rel] = _obl("PROVEN", "changed; authorized by a base-side anchor: row")
            else:
                anchor_obl[rel] = _obl("BYPASS", "changed with NO base-side authorization")
                blocks.append(f"trust anchor {rel} changed without a base-side AUTHORIZE anchor: row")
        injected["REQ-GOV-TRUST-ANCHORS"] = {"canonical": anchors, "obligations": anchor_obl,
                                            "authority_resolved": anchor_resolved}

        # ── the judged tree: candidate DATA under the BASE validator ──
        judged = wts.copy(cand_wt, "judged")
        copied = overlay(base_wt, judged, anchors)
        print(f"judged tree: candidate + {len(copied)} base trust-anchor file(s) overlaid")
        base_counts = run_gate(base_wt, "base")
        base_roster = enforced_roster(base_wt)
        trusted_counts = run_gate(judged, "candidate (base validator)")
        cand_roster = enforced_roster(cand_wt)                     # static parse: data, not execution
        retired, removed = split_removals(removed_enforced_checks(base_roster, cand_roster),
                                          A.retirements(base_contract))
        base_counts_f, folded = refold_base_counts(base_counts, A.folds(base_contract), set(retired), cand_roster)
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
        injected["REQ-GOV-TRUSTED-VALIDATOR"] = {"canonical": sorted(base_roster), "obligations": roster_obl,
                                                "notes": ([f"retired by base-side declaration: {', '.join(retired)}"] if retired else []) + folded}

        # ── escape markers ──
        tokens = marker_tokens((base_wt / CHECKER_REL).read_text(encoding="utf-8", errors="replace"))
        marker_obl = {}
        for path, line, tok in added_marker_lines(base_sha, cand_sha, tokens):
            key = f"{path}:{line}:{tok}"
            if A.authorized(auths, "marker", path, branch, token=tok):
                marker_obl[key] = _obl("PROVEN", "authorized by a base-side marker: row")
            else:
                marker_obl[key] = _obl("BYPASS", "escape marker added by the same delta with no base-side authorization")
                blocks.append(f"escape marker {tok} added at {path}:{line} without a base-side AUTHORIZE marker: row")
        injected["REQ-GOV-MARKER-AUTHORITY"] = {"canonical": sorted(marker_obl), "obligations": marker_obl}

        # ── closure rows cite an executable command (DATA); the candidate lane executes it ──
        closing = closing_rows(_show(base_sha, _LEDGER_REL), (cand_wt / _LEDGER_REL).read_text(encoding="utf-8", errors="replace"))
        close_obl = {}
        for rc, row in sorted(closing.items()):
            cmds = executable_commands(row)
            if cmds:
                close_obl[rc] = _obl("PROVEN", f"cites `{cmds[0][:120]}`; executed by the candidate lane (hardening)")
            else:
                close_obl[rc] = _obl("FAIL", "closes with no CI-executable command (python/pytest/node/npm) in its evidence cell")
                blocks.append(f"{rc} closes without a CI-executable command; a live probe alone does not close a row")
        injected["REQ-GOV-CLOSURE-COMMANDS"] = {"canonical": sorted(closing), "obligations": close_obl}

        # ── operating-process re-date rule (local hook parity) ──
        opl = _load_module(base_wt / "tools/operating_process_lock.py", "_base_opl")
        for msg in opl.rc_redate_violations(cand_wt):
            blocks.append(f"re-date rule (operating_process_lock): {msg}")

        # ── acceptance verdicts: candidate (base module, judged tree) vs base ──
        cand_verdicts = A.evaluate(judged, cand_contract, base_contract=base_contract, injected=injected)
        base_verdicts = {v.requirement.id: v for v in A.evaluate(base_wt, base_contract, base_contract=base_contract)}
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
                "base": base_sha, "candidate": cand_sha, "branch": branch,
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


# ═════════════════════════════════════════════════════════════════════════════════════
# CANDIDATE LANE
# ═════════════════════════════════════════════════════════════════════════════════════
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

    base_counts, base_sha, base_roster = enforced_counts(args.base)
    wts = Worktrees()
    try:
        cand_wt = wts.add(candidate_ref, "cand")
        _stage(cand_wt, f"{candidate_ref}^")          # the change under commit appears STAGED
        head_sha = _run(["git", "rev-parse", "--short", candidate_ref]).stdout.strip()
        head_counts, head_roster = run_gate(cand_wt, candidate_label), enforced_roster(cand_wt)
        # Declarations are read from the BASE, never the candidate (two-step contract).
        retired, removed = split_removals(
            removed_enforced_checks(base_roster, head_roster),
            declared_retirements(args.base))
        base_counts, folded_moves = refold_base_counts(
            base_counts, declared_folds(args.base), set(retired), head_roster)
        added, improved = compare(base_counts, head_counts)
        closure_failures = execute_closures(args.base, cand_wt)
    finally:
        wts.close()

    print(f"base {args.base} ({base_sha}): {sum(base_counts.values())} enforced "
          f"across {len(base_counts)} check(s), {len(base_roster)} enforced check(s) declared")
    print(f"{candidate_label} ({head_sha}): {sum(head_counts.values())} enforced "
          f"across {len(head_counts)} check(s), {len(head_roster)} enforced check(s) declared")
    if improved:
        print("\nPAID DOWN by this delta:")
        print("\n".join(improved))
    if folded_moves:
        print("\nFOLDED by consolidation declared in the base OPEN_ITEMS.md `retire:` rows:")
        print("\n".join(folded_moves))
    if retired:
        print("\nRETIRED by base-side `AUTHORIZE retire:` rows in OPEN_ITEMS.md (RC-468):")
        print("\n".join(f"  {name}" for name in retired))
    if not added and not removed and not closure_failures:
        tail = ("every removed check is declared retired by a base-side row"
                if retired else "removes no enforced check")
        print(f"\n[PASS] this delta adds no enforced violation the base did not already "
              f"carry, {tail}, and every row it closes ran its cited command to exit 0.")
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
    if closure_failures:
        print("\n[FAIL] a ledger row this delta CLOSES did not prove its closure by execution:")
        print("\n".join(f"  {f}" for f in closure_failures))
    return 1


if __name__ == "__main__":
    sys.exit(main())
