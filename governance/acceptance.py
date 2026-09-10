"""The ONE executor of the acceptance contract (UNIVERSAL_QUANTITATIVE_CLOSURE_AND_NON_BYPASS_V1).

`OPEN_ITEMS.md` is the acceptance specification; its "Requirements" table is the contract.
This module READS, VALIDATES and COMPUTES it. It defines no policy of its own: no population,
no requirement, no waiver and no verdict lives here. Every verdict is COMPUTED from

    S_R  the applicable obligation set, enumerated by the CANONICAL AUTHORITY the row's SCOPE
         names (a `module:function` in the judged tree; `delta:<name>` populations only the
         delta gate can enumerate; `evidence:<REQ>` proven by evidence records;
         `narrowing:<check>` for open properties; `NONE` = NOT_PROVEN by construction);
    W_R  exclusions that exist as AUTHORIZE rows in the TRUSTED BASE contract;
    P_R  obligations carrying proof of at least the row's declared class;
    M_R = A_R - P_R (missing), F_R (proven failed), E_R (invalid evidence), B_R (bypass).

    FAIL(R)        iff |F_R| > 0 or |B_R| > 0 (a demonstrated failure, whatever else is unknown);
    NOT_PROVEN(R)  iff the authority did not resolve, or |M_R| > 0, or |E_R| > 0;
    PASS(R)        otherwise.

A sample may falsify; it never establishes. No percentages, no partial credit.

Shape: PARSE the contract -> RECEIVE authoritative results (SCOPE owners called in the judged
tree, the delta gate's injected populations, evidence records under reports/evidence/) ->
COMPUTE M/F/E/B and the verdict -> EMIT the counts. Populations live with their owners
(`tools.precommit_institutional.trust_anchor_paths` for the enforcement path, the hook seam,
the router, the provenance authority); the falsifiers of `evidence_status` live in the test
suite (tests/test_universal_closure_v1.py), never in this module.

The delta gate (tools/check_delta_adds_no_debt.py --trusted) is the caller that compares the
BASE contract against a CANDIDATE tree; `python governance/acceptance.py --tree <root>` prints
the same computation for one tree.
"""
from __future__ import annotations

import fnmatch
import importlib.util
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# ── contract vocabulary ──────────────────────────────────────────────────────────────────
KINDS = ("FINITE", "OPEN", "AUTHORIZE", "ACCEPT")
GATES = ("MERGE", "PRODUCT")
#: Evidence classes, weakest first. A requirement declares the minimum; evidence of a lower
#: class is INVALID for it (E_R), never "partial".
EVIDENCE_CLASSES = ("STATIC", "ISOLATED_E2E", "REAL_POPULATION", "LIVE_RTH")
EVIDENCE_FLAGS = ("EXACT_HEAD", "RUNTIME_IDENTITY", "OPERATOR_ACCEPT")
VERDICTS = ("PASS", "FAIL", "NOT_PROVEN")
#: AUTHORIZE scopes: what a base-side row may grant (a candidate may only request).
AUTHORIZE_KINDS = ("anchor", "marker", "waive", "retire")

_SECTION_RE = re.compile(r"^## Requirements\b", re.M)
_ROW_RE = re.compile(r"^\|\s*((?:REQ|AUTH|ACC)-[A-Z0-9\-]+)\s*\|(.*)$")
_FOLD_RE = re.compile(r"folded into ([a-z][a-z0-9_]*)")


class ContractError(ValueError):
    """The contract text is not a valid contract - fail closed, never guess."""


@dataclass(frozen=True)
class Requirement:
    id: str
    kind: str
    gate: str
    scope: str
    proof: str
    parent: str
    criterion: str
    line: int

    @property
    def proof_class(self) -> str:
        return self.proof.split("+")[0].strip()

    @property
    def proof_flags(self) -> frozenset[str]:
        return frozenset(p.strip() for p in self.proof.split("+")[1:] if p.strip())


@dataclass
class ObligationResult:
    status: str                     # PROVEN | MISSING | FAIL | INVALID | BYPASS
    detail: str = ""


@dataclass
class Verdict:
    requirement: Requirement
    scope_kind: str
    scope_authority: str
    authority_resolved: bool
    canonical: list[str] = field(default_factory=list)
    waived: list[str] = field(default_factory=list)
    obligations: dict[str, ObligationResult] = field(default_factory=dict)
    adversarial_run: int = 0
    adversarial_caught: int = 0
    narrowing_violations: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def applicable(self) -> list[str]:
        w = set(self.waived)
        return [o for o in self.canonical if o not in w]

    def _count(self, status: str) -> int:
        return sum(1 for o in self.applicable
                   if self.obligations.get(o, ObligationResult("MISSING")).status == status)

    @property
    def proven(self) -> int:
        return self._count("PROVEN")

    @property
    def missing(self) -> int:
        return self._count("MISSING")

    @property
    def failed(self) -> int:
        return self._count("FAIL")

    @property
    def invalid(self) -> int:
        return self._count("INVALID")

    @property
    def bypass(self) -> int:
        return self._count("BYPASS") + len(self.narrowing_violations)

    @property
    def verdict(self) -> str:
        if self.failed or self.bypass:
            return "FAIL"
        if self.requirement.kind == "OPEN" and self.adversarial_run and self.adversarial_caught != self.adversarial_run:
            return "FAIL"
        if not self.authority_resolved or self.missing or self.invalid:
            return "NOT_PROVEN"
        if self.requirement.kind == "OPEN" and not self.applicable:
            return "NOT_PROVEN"
        return "PASS"


# ── contract parsing ─────────────────────────────────────────────────────────────────────
def parse_contract(text: str) -> list[Requirement]:
    """Every REQ-/AUTH-/ACC- row of the Requirements table. Shape errors raise: an
    unreadable contract judges nothing and therefore blocks."""
    m = _SECTION_RE.search(text)
    if not m:
        raise ContractError("OPEN_ITEMS.md has no '## Requirements' section")
    rows: list[Requirement] = []
    start_line = text[: m.start()].count("\n") + 1
    for offset, line in enumerate(text[m.start():].splitlines()):
        if offset and line.startswith("## "):
            break
        rm = _ROW_RE.match(line)
        if not rm:
            continue
        cells = [c.strip() for c in rm.group(2).split("|")]
        if cells and cells[-1] == "":
            cells = cells[:-1]
        rid = rm.group(1)
        if len(cells) != 6:
            raise ContractError(f"{rid}: expected 7 cells (ID|KIND|GATE|SCOPE|PROOF|PARENT|CRITERION), got {len(cells) + 1}")
        kind, gate, scope, proof, parent, criterion = cells
        if kind not in KINDS:
            raise ContractError(f"{rid}: KIND {kind!r} not in {KINDS}")
        if kind in ("FINITE", "OPEN"):
            if not rid.startswith("REQ-"):
                raise ContractError(f"{rid}: a {kind} row must be a REQ- id")
            if gate not in GATES:
                raise ContractError(f"{rid}: GATE {gate!r} not in {GATES}")
            if proof.split("+")[0].strip() not in EVIDENCE_CLASSES:
                raise ContractError(f"{rid}: PROOF class {proof.split('+')[0].strip()!r} not in {EVIDENCE_CLASSES}")
            for fl in proof.split("+")[1:]:
                if fl.strip() not in EVIDENCE_FLAGS:
                    raise ContractError(f"{rid}: PROOF flag {fl.strip()!r} not in {EVIDENCE_FLAGS}")
            if not scope:
                raise ContractError(f"{rid}: empty SCOPE - name the canonical authority, or write `NONE` to state that none is identified")
        elif kind == "AUTHORIZE":
            if not rid.startswith("AUTH-"):
                raise ContractError(f"{rid}: an AUTHORIZE row must be an AUTH- id")
            if scope.split(":", 1)[0] not in AUTHORIZE_KINDS:
                raise ContractError(f"{rid}: AUTHORIZE scope must start with one of {AUTHORIZE_KINDS}")
        elif kind == "ACCEPT":
            if not rid.startswith("ACC-"):
                raise ContractError(f"{rid}: an ACCEPT row must be an ACC- id")
            if not re.match(r"^REQ-[A-Z0-9\-]+@[0-9a-f]{7,40}$", scope):
                raise ContractError(f"{rid}: ACCEPT scope must be <REQ-id>@<sha>")
        rows.append(Requirement(rid, kind, gate, scope, proof, parent, criterion, start_line + offset))
    ids = [r.id for r in rows]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        raise ContractError(f"duplicate contract ids: {dup}")
    by_id = {r.id: r for r in rows}
    for r in rows:
        if r.kind in ("FINITE", "OPEN") and r.parent not in ("-", "") and r.parent not in by_id:
            raise ContractError(f"{r.id}: PARENT {r.parent} is not a row of the contract")
    return rows


def load_contract(root: Path) -> list[Requirement]:
    p = root / "OPEN_ITEMS.md"
    if not p.is_file():
        raise ContractError(f"{p} missing")
    return parse_contract(p.read_text(encoding="utf-8", errors="replace"))


def requirements(rows: list[Requirement]) -> list[Requirement]:
    return [r for r in rows if r.kind in ("FINITE", "OPEN")]


def authorizations(rows: list[Requirement]) -> list[Requirement]:
    return [r for r in rows if r.kind == "AUTHORIZE"]


def acceptances(rows: list[Requirement]) -> list[Requirement]:
    return [r for r in rows if r.kind == "ACCEPT"]


def retirements(rows: list[Requirement]) -> set[str]:
    """Enforced-check names the contract declares retired (`retire:<check>` AUTHORIZE rows).
    Callers pass the BASE contract: the two-step contract (RC-468) - declare on main first,
    remove in a later delta - is the same AUTHORIZE rule every other grant follows."""
    return {a.scope.split(":", 1)[1].split("@", 1)[0].strip()
            for a in authorizations(rows) if a.scope.startswith("retire:")}


def folds(rows: list[Requirement]) -> dict[str, str]:
    """{retired check: survivor} for `retire:` rows whose criterion says 'folded into <x>'."""
    out: dict[str, str] = {}
    for a in authorizations(rows):
        if a.scope.startswith("retire:"):
            f = _FOLD_RE.search(a.criterion)
            if f:
                out[a.scope.split(":", 1)[1].split("@", 1)[0].strip()] = f.group(1)
    return out


# ── contract monotonicity (REPAIR 2: the candidate may not shrink its own judge) ────────
_CLASS_RANK = {c: i for i, c in enumerate(EVIDENCE_CLASSES)}


def contract_regressions(base: list[Requirement], cand: list[Requirement]) -> list[str]:
    """Every way a candidate contract is WEAKER than the base contract. Additions are fine;
    deletions, scope changes, weaker proof, gate demotion and parent moves are reported."""
    out: list[str] = []
    cmap = {r.id: r for r in cand}
    for b in requirements(base):
        c = cmap.get(b.id)
        if c is None:
            out.append(f"{b.id}: requirement DELETED (an unmet acceptance row removed is not closure)")
            continue
        if c.kind != b.kind:
            out.append(f"{b.id}: KIND changed {b.kind} -> {c.kind}")
        if c.scope != b.scope:
            out.append(f"{b.id}: SCOPE authority changed {b.scope!r} -> {c.scope!r} (the population owner is base state)")
        if _CLASS_RANK.get(c.proof_class, -1) < _CLASS_RANK.get(b.proof_class, -1):
            out.append(f"{b.id}: PROOF class weakened {b.proof_class} -> {c.proof_class}")
        if not b.proof_flags <= c.proof_flags:
            out.append(f"{b.id}: PROOF flags dropped {sorted(b.proof_flags - c.proof_flags)}")
        if b.gate == "MERGE" and c.gate != "MERGE":
            out.append(f"{b.id}: GATE demoted MERGE -> {c.gate}")
        if c.parent != b.parent:
            out.append(f"{b.id}: PARENT changed {b.parent!r} -> {c.parent!r}")
    return out


def candidate_only_grants(base: list[Requirement], cand: list[Requirement]) -> list[Requirement]:
    """AUTHORIZE / ACCEPT rows the candidate carries and the base does not: REQUESTS,
    visible and reviewable, ineffective until merged."""
    base_ids = {r.id for r in base}
    return [r for r in cand if r.kind in ("AUTHORIZE", "ACCEPT") and r.id not in base_ids]


# ── scope resolution: the judged tree's own owners enumerate and verify ─────────────────
def load_tree_module(root: Path, dotted: str):
    """Import `dotted` (e.g. `tools.stop_chain`) FROM THE TREE AT `root`, not from this
    process's repo, so a judge reads the owners of the tree it judges. Registered in
    sys.modules under a root-specific name (dataclasses need it)."""
    rel = Path(*dotted.split(".")).with_suffix(".py")
    path = root / rel
    if not path.is_file():
        raise LookupError(f"{rel.as_posix()} is not in the judged tree")
    name = f"_judged_{abs(hash(str(root)))}_{dotted.replace('.', '_')}"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    # the tree stays importable for the module's LIFETIME: its functions import siblings
    # (`from tools.x import ...`) when called, not only at load. Front of the path so the
    # most recently judged tree wins; in the trusted gate every tree carries the base's
    # anchors, so a sibling resolved from an earlier tree is the same base code.
    if str(root) in sys.path:
        sys.path.remove(str(root))
    sys.path.insert(0, str(root))
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def resolve_scope(scope: str, root: Path):
    """Call the `module:function` a row names, in the judged tree, with the tree root.
    Returns a list (population; proof must come from elsewhere) or a dict
    `{obligation: {status, detail}}` (population and proof from ONE owner). Anything else,
    or a missing owner, is LookupError -> NOT_PROVEN. Never a fallback, never a guess."""
    if scope.startswith("delta:"):
        raise LookupError(f"{scope} is a delta population - only the delta gate can enumerate it")
    if ":" not in scope:
        raise LookupError(f"{scope!r} names no canonical authority")
    dotted, fn_name = scope.split(":", 1)
    mod = load_tree_module(root, dotted)
    fn = getattr(mod, fn_name, None)
    if fn is None:
        raise LookupError(f"{dotted} has no {fn_name} in the judged tree")
    result = fn(root)
    if isinstance(result, dict):
        return {str(k): (v if isinstance(v, ObligationResult) else ObligationResult(**v)) for k, v in result.items()}
    if isinstance(result, (list, tuple, set)):
        return sorted(str(x) for x in result)
    raise LookupError(f"{scope} returned {type(result).__name__}, not a population")


# ── evidence records (REPAIR 4) ──────────────────────────────────────────────────────────
EVIDENCE_DIR = "reports/evidence"
_REQUIRED_FIELDS = ("requirement_id", "evidence_class", "candidate_sha", "environment", "source", "captured_at")


def _git(root: Path, *args: str) -> str | None:
    try:
        r = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _code_unchanged_since(root: Path, sha: str) -> tuple[bool, str]:
    """EXACT_HEAD: the evidence's sha is an ancestor of HEAD with no source change between
    them (evidence files and governance prose excluded)."""
    head = _git(root, "rev-parse", "HEAD")
    if not head:
        return False, "tree has no HEAD"
    if _git(root, "merge-base", "--is-ancestor", sha, "HEAD") is None:
        return False, f"{sha[:8]} is not an ancestor of HEAD {head.strip()[:8]}"
    diff = _git(root, "diff", "--name-only", f"{sha}..HEAD", "--", ".",
                f":!{EVIDENCE_DIR}", ":!governance/*.md", ":!OPEN_ITEMS.md", ":!reports/*.md")
    if diff is None:
        return False, "diff unavailable"
    changed = [ln for ln in diff.splitlines() if ln.strip()]
    return (False, f"code moved past the evidence: {changed[:5]}") if changed else (True, "")


def evidence_status(rec: dict, req: Requirement, root: Path) -> ObligationResult:
    missing = [f for f in _REQUIRED_FIELDS if not rec.get(f)]
    if missing:
        return ObligationResult("INVALID", f"evidence lacks {missing}")
    if rec.get("requirement_id") != req.id:
        return ObligationResult("INVALID", "evidence names another requirement")
    cls = str(rec.get("evidence_class"))
    if cls not in EVIDENCE_CLASSES:
        return ObligationResult("INVALID", f"unknown evidence class {cls!r}")
    if _CLASS_RANK[cls] < _CLASS_RANK[req.proof_class]:
        return ObligationResult("INVALID", f"class {cls} < required {req.proof_class}")
    # provenance is independent of payload labels: only the record's own declared
    # environment/source count, never a `live: true` inside a captured payload.
    if cls == "LIVE_RTH" and str(rec.get("environment")).upper() != "LIVE_RTH":
        return ObligationResult("INVALID", "LIVE_RTH class needs environment LIVE_RTH")
    if cls in ("REAL_POPULATION", "LIVE_RTH"):
        pop = rec.get("population") or {}
        if not (pop.get("authority") and pop.get("digest") and pop.get("count")):
            return ObligationResult("INVALID", "real-population evidence lacks population authority/digest/count")
    sha = str(rec.get("candidate_sha"))
    if "EXACT_HEAD" in req.proof_flags:
        ok, why = _code_unchanged_since(root, sha)
        if not ok:
            return ObligationResult("INVALID", why)
    if "RUNTIME_IDENTITY" in req.proof_flags:
        ri = rec.get("runtime_identity") or {}
        if not ri.get("git_sha") or not str(ri.get("git_sha")).startswith(sha[:7]):
            return ObligationResult("INVALID", "runtime identity absent or not the evidence sha")
        if ri.get("dirty") is not False:
            return ObligationResult("INVALID", "runtime identity is not a clean tree")
    return ObligationResult("PROVEN", f"{cls} {sha[:8]} {rec.get('source')}")


def evidence_records(root: Path, req_id: str) -> list[tuple[Path, dict]]:
    d = root / EVIDENCE_DIR / req_id
    out: list[tuple[Path, dict]] = []
    if d.is_dir():
        for p in sorted(d.glob("*.json")):
            try:
                out.append((p, json.loads(p.read_text(encoding="utf-8"))))
            except (OSError, ValueError):
                out.append((p, {"_unreadable": True}))
    return out


# ── verdict computation ──────────────────────────────────────────────────────────────────
def authorized(auths: list[Requirement], kind: str, subject: str, branch: str,
               token: str | None = None) -> bool:
    """A base-side AUTHORIZE row covers (kind, subject, branch[, token]) — the grant grammar:
    `anchor:<glob>@<branch|*>`, `marker:<token>@<glob>@<branch|*>`."""
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


def _waived(req: Requirement, auths: list[Requirement]) -> list[str]:
    out = []
    for a in auths:
        if a.scope.startswith("waive:"):
            parts = a.scope.split(":", 2)
            if len(parts) == 3 and parts[1] == req.id and parts[2]:
                out.append(parts[2])
    return out


def _accepted(req: Requirement, accs: list[Requirement], root: Path) -> bool:
    head = (_git(root, "rev-parse", "HEAD") or "").strip()
    return any(a.scope.split("@", 1)[0] == req.id and head.startswith(a.scope.split("@", 1)[1]) for a in accs)


def narrowing_violations(root: Path, check_name: str) -> list[str]:
    """Run ONE named check of the judged tree's institutional gate; its violations are the
    LOCAL NARROWINGS of an open property (NC-03)."""
    mod = load_tree_module(root, "tools.check_institutional_correctness")
    for name, fn, _enforced in mod.CHECKS:
        if name == check_name:
            return [str(v) for v in fn()]
    raise LookupError(f"{check_name} is not a registered check")


def evaluate(root: Path, contract: list[Requirement], base_contract: list[Requirement] | None = None,
             injected: dict[str, dict] | None = None) -> list[Verdict]:
    """A Verdict per requirement of `contract` against the tree at `root`.

    `base_contract` is the TRUSTED contract: only ITS authorizations and acceptances count,
    and the requirements judged are the base's plus any stricter rows the candidate adds.
    `injected` carries delta populations and results the delta gate measured."""
    trusted = base_contract if base_contract is not None else contract
    auths, accs = authorizations(trusted), acceptances(trusted)
    judged: dict[str, Requirement] = {r.id: r for r in requirements(trusted)}
    for r in requirements(contract):
        judged.setdefault(r.id, r)
    injected = injected or {}
    verdicts: list[Verdict] = []
    for req in judged.values():
        v = Verdict(req, req.kind, req.scope, True)
        v.waived = _waived(req, auths)
        if req.id in injected:
            inj = injected[req.id]
            v.canonical = list(inj.get("canonical", []))
            v.obligations = {k: (o if isinstance(o, ObligationResult) else ObligationResult(**o))
                             for k, o in inj.get("obligations", {}).items()}
            v.adversarial_run = int(inj.get("adversarial_run", 0))
            v.adversarial_caught = int(inj.get("adversarial_caught", 0))
            v.narrowing_violations = list(inj.get("narrowing_violations", []))
            v.notes = list(inj.get("notes", []))
            v.authority_resolved = bool(inj.get("authority_resolved", True))
        elif req.scope == "NONE":
            v.authority_resolved = False
            v.notes.append("no canonical authority identified - NOT_PROVEN by construction")
        elif req.scope.startswith("evidence:"):
            v.canonical = [req.id]
            best: ObligationResult | None = None
            for p, rec in evidence_records(root, req.id):
                st = ObligationResult("INVALID", f"{p.name} unreadable") if rec.get("_unreadable") else evidence_status(rec, req, root)
                if st.status == "PROVEN":
                    best = st
                    break
                if best is None or best.status == "MISSING":
                    best = st
            best = best or ObligationResult("MISSING", "no evidence record")
            if best.status == "PROVEN" and "OPERATOR_ACCEPT" in req.proof_flags and not _accepted(req, accs, root):
                best = ObligationResult("MISSING", "evidence valid; operator ACCEPT row for this head absent (cannot self-certify)")
            v.obligations = {req.id: best}
        elif req.scope.startswith("narrowing:"):
            v.authority_resolved = False
            check_name = req.scope.split(":", 1)[1]
            try:
                v.narrowing_violations = narrowing_violations(root, check_name)
            except Exception as e:  # noqa: BLE001 - an unmeasurable narrowing detector is a bypass, not a pass
                v.narrowing_violations = [f"narrowing detector {check_name} unmeasurable: {e!r}"]
            v.notes.append(f"boundary authority NONE; local narrowings measured by check {check_name}")
        else:
            try:
                result = resolve_scope(req.scope, root)
            except Exception as e:  # noqa: BLE001 - an owner that cannot answer is NOT_PROVEN, never a guess
                v.authority_resolved = False
                v.notes.append(f"authority did not resolve: {e}")
                verdicts.append(v)
                continue
            if isinstance(result, dict):
                v.canonical = sorted(result)
                v.obligations = result
            else:
                v.canonical = list(result)
                v.obligations = {o: ObligationResult("MISSING", "population enumerated; no proof in this context") for o in v.canonical}
        verdicts.append(v)
    return verdicts


# ── report ───────────────────────────────────────────────────────────────────────────────
_MAX_LISTED = 25   # per requirement; every obligation is in --json


def report_lines(verdicts: list[Verdict]) -> list[str]:
    lines: list[str] = []
    for v in verdicts:
        r = v.requirement
        lines.append(f"REQUIREMENT_ID={r.id} SCOPE_KIND={r.kind} GATE={r.gate} SCOPE_AUTHORITY={r.scope} PROOF={r.proof}")
        if r.kind == "FINITE":
            lines.append(f"  CANONICAL_COUNT={len(v.canonical)} WAIVED_COUNT={len([w for w in v.waived if w in v.canonical])} "
                         f"APPLICABLE_COUNT={len(v.applicable)} PROVEN_COUNT={v.proven} MISSING_COUNT={v.missing} "
                         f"FAIL_COUNT={v.failed} INVALID_EVIDENCE_COUNT={v.invalid} BYPASS_COUNT={v.bypass} VERDICT={v.verdict}")
        else:
            lines.append(f"  BOUNDARY_AUTHORITY={r.scope} INVARIANT_ID={r.id} LOCAL_NARROWING_VIOLATIONS={len(v.narrowing_violations)} "
                         f"ADVERSARIAL_MUTATIONS_RUN={v.adversarial_run} ADVERSARIAL_MUTATIONS_CAUGHT={v.adversarial_caught} "
                         f"PROVEN_COUNT={v.proven} MISSING_COUNT={v.missing} FAIL_COUNT={v.failed} INVALID_EVIDENCE_COUNT={v.invalid} VERDICT={v.verdict}")
        for note in v.notes:
            lines.append(f"  note: {note}")
        unproven = [o for o in v.applicable if v.obligations.get(o, ObligationResult("MISSING")).status != "PROVEN"]
        for i, o in enumerate(unproven):
            if i >= _MAX_LISTED:
                lines.append(f"  ... and {len(unproven) - i} more (see --json for every obligation)")
                break
            st = v.obligations.get(o, ObligationResult("MISSING"))
            lines.append(f"  {st.status}: {o} - {st.detail}")
    counts = {k: sum(1 for v in verdicts if v.verdict == k) for k in VERDICTS}
    lines.append(f"TOTAL_REQUIRED_REQUIREMENTS={len(verdicts)} PASS_COUNT={counts['PASS']} "
                 f"FAIL_COUNT={counts['FAIL']} NOT_PROVEN_COUNT={counts['NOT_PROVEN']}")
    return lines


def report_json(verdicts: list[Verdict]) -> dict:
    return {
        "requirements": [{
            "id": v.requirement.id, "kind": v.requirement.kind, "gate": v.requirement.gate,
            "scope": v.requirement.scope, "proof": v.requirement.proof, "verdict": v.verdict,
            "canonical": len(v.canonical), "waived": len(v.waived), "applicable": len(v.applicable),
            "proven": v.proven, "missing": v.missing, "fail": v.failed, "invalid": v.invalid,
            "bypass": v.bypass, "adversarial_run": v.adversarial_run, "adversarial_caught": v.adversarial_caught,
            "notes": v.notes,
            "obligations": {o: {"status": s.status, "detail": s.detail} for o, s in v.obligations.items() if o in set(v.applicable)},
        } for v in verdicts],
        "summary": {k: sum(1 for v in verdicts if v.verdict == k) for k in VERDICTS},
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Compute the acceptance verdicts of ONE tree")
    ap.add_argument("--tree", default=str(REPO), help="tree root to judge (default: this repo)")
    ap.add_argument("--contract", default=None, help="OPEN_ITEMS.md holding the TRUSTED contract (default: the tree's own)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    root = Path(args.tree).resolve()
    cand = load_contract(root)
    base = parse_contract(Path(args.contract).read_text(encoding="utf-8", errors="replace")) if args.contract else None
    verdicts = evaluate(root, cand, base_contract=base)
    print(json.dumps(report_json(verdicts), indent=1) if args.json else "\n".join(report_lines(verdicts)))
    return 0 if all(v.verdict == "PASS" for v in verdicts if v.requirement.gate == "MERGE") else 1


if __name__ == "__main__":
    sys.exit(main())
