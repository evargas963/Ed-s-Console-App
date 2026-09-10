"""The ONE executable acceptance authority (UNIVERSAL_QUANTITATIVE_CLOSURE_AND_NON_BYPASS_V1).

`OPEN_ITEMS.md` is the acceptance specification. Its "Requirements" table is the machine-read
contract this module executes; nothing here stores a verdict — every verdict is COMPUTED from

    S_R  the applicable obligation set, enumerated by the CANONICAL AUTHORITY named in the row
         (never by the implementation under judgment, never by a test, never by a fixture);
    W_R  exclusions that exist as AUTHORIZE rows in the TRUSTED BASE contract (a candidate may
         request one by adding a row; it becomes effective only once it is on main);
    P_R  obligations carrying evidence of at least the row's declared class;
    M_R = A_R - P_R (missing), F_R (proven failed), E_R (invalid evidence), B_R (bypass).

    PASS(R)        iff |M_R| == |F_R| == |E_R| == |B_R| == 0 and the authority resolved.
    FAIL(R)        iff |F_R| > 0 or |B_R| > 0.
    NOT_PROVEN(R)  otherwise (missing obligations, invalid evidence, unresolvable authority).

A sample may falsify; it never establishes. There are no percentages and no partial credit.

The delta gate (tools/check_delta_adds_no_debt.py --trusted) is the caller that compares the
BASE contract against a CANDIDATE tree; `python governance/acceptance.py --tree <root>` prints
the same computation for one tree.
"""
from __future__ import annotations

import ast
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
#: Binding flags a requirement may add to its class.
EVIDENCE_FLAGS = ("EXACT_HEAD", "RUNTIME_IDENTITY", "OPERATOR_ACCEPT")
VERDICTS = ("PASS", "FAIL", "NOT_PROVEN")

_SECTION_RE = re.compile(r"^## Requirements\b", re.M)
_ROW_RE = re.compile(r"^\|\s*((?:REQ|AUTH|ACC)-[A-Z0-9\-]+)\s*\|(.*)$")


class ContractError(ValueError):
    """The contract text is not a valid contract — fail closed, never guess."""


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
    status: str                     # PROVEN | MISSING | FAIL | INVALID | BYPASS | WAIVED
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

    # ── counts (the only arithmetic permitted) ──
    @property
    def applicable(self) -> list[str]:
        return [o for o in self.canonical if o not in set(self.waived)]

    def _count(self, status: str) -> int:
        return sum(1 for o in self.applicable if self.obligations.get(o, ObligationResult("MISSING")).status == status)

    @property
    def proven(self) -> int:
        return self._count("PROVEN")

    @property
    def missing(self) -> int:
        return sum(1 for o in self.applicable
                   if self.obligations.get(o, ObligationResult("MISSING")).status == "MISSING")

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
            return "FAIL"           # a demonstrated failure or bypass is FAIL whatever else is unknown
        if not self.authority_resolved:
            return "NOT_PROVEN"
        if self.requirement.kind == "OPEN":
            if self.adversarial_run and self.adversarial_caught != self.adversarial_run:
                return "FAIL"
            if not self.applicable or self.missing or self.invalid:
                return "NOT_PROVEN"
            return "PASS"
        if self.missing or self.invalid:
            return "NOT_PROVEN"
        if not self.applicable:
            # an empty applicable set is a PASS only when the authority resolved and said so
            return "PASS"
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
        # trailing empty cell from the closing pipe
        if cells and cells[-1] == "":
            cells = cells[:-1]
        if len(cells) != 6:
            raise ContractError(f"{rm.group(1)}: expected 7 cells (ID|KIND|GATE|SCOPE|PROOF|PARENT|CRITERION), got {len(cells) + 1}")
        kind, gate, scope, proof, parent, criterion = cells
        rid = rm.group(1)
        if kind not in KINDS:
            raise ContractError(f"{rid}: KIND {kind!r} not in {KINDS}")
        if kind in ("FINITE", "OPEN"):
            if not rid.startswith("REQ-"):
                raise ContractError(f"{rid}: a {kind} row must be a REQ- id")
            if gate not in GATES:
                raise ContractError(f"{rid}: GATE {gate!r} not in {GATES}")
            pc = proof.split("+")[0].strip()
            if pc not in EVIDENCE_CLASSES:
                raise ContractError(f"{rid}: PROOF class {pc!r} not in {EVIDENCE_CLASSES}")
            for fl in proof.split("+")[1:]:
                if fl.strip() not in EVIDENCE_FLAGS:
                    raise ContractError(f"{rid}: PROOF flag {fl.strip()!r} not in {EVIDENCE_FLAGS}")
            if not scope:
                raise ContractError(f"{rid}: empty SCOPE — a requirement names its canonical authority or is NOT_PROVEN by construction; write `NONE` to say so explicitly")
        elif kind == "AUTHORIZE":
            if not rid.startswith("AUTH-"):
                raise ContractError(f"{rid}: an AUTHORIZE row must be an AUTH- id")
            if not re.match(r"^(anchor|marker|waive):", scope):
                raise ContractError(f"{rid}: AUTHORIZE scope must be anchor:<path>@<branch>, marker:<token>@<path>@<branch> or waive:<REQ>:<obligation>")
        elif kind == "ACCEPT":
            if not rid.startswith("ACC-"):
                raise ContractError(f"{rid}: an ACCEPT row must be an ACC- id")
            if not re.match(r"^REQ-[A-Z0-9\-]+@[0-9a-f]{7,40}$", scope):
                raise ContractError(f"{rid}: ACCEPT scope must be <REQ-id>@<sha>")
        rows.append(Requirement(rid, kind, gate, scope, proof, parent, criterion,
                                start_line + offset))
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


# ── contract monotonicity (REPAIR 2: the candidate may not shrink its own judge) ────────
_CLASS_RANK = {c: i for i, c in enumerate(EVIDENCE_CLASSES)}


def contract_regressions(base: list[Requirement], cand: list[Requirement]) -> list[str]:
    """Every way a candidate contract is WEAKER than the base contract, as human lines.
    Additions are fine (a stricter contract is recognized); deletions, scope changes,
    weaker proof, gate demotion, parent changes and self-granted AUTHORIZE/ACCEPT rows are
    reported. An empty list means the candidate contract is at least as strict."""
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
    """AUTHORIZE / ACCEPT rows the candidate carries and the base does not. They are
    REQUESTS: visible, reviewable, and ineffective until merged."""
    base_ids = {r.id for r in base}
    return [r for r in cand if r.kind in ("AUTHORIZE", "ACCEPT") and r.id not in base_ids]


# ── canonical population authorities ────────────────────────────────────────────────────
# Each returns sorted obligation identifiers for ONE tree, read from the owner that defines
# the domain. None of them keeps a hand list of members: the wiring, the router, the roster
# and the provenance roots are the populations. A function raising LookupError means the
# authority could not be identified, and the requirement is NOT_PROVEN — never invented.

def _read(root: Path, rel: str) -> str:
    p = root / rel
    if not p.is_file():
        raise LookupError(f"{rel} missing")
    return p.read_text(encoding="utf-8", errors="replace")


def enforced_check_roster(root: Path) -> list[str]:
    """CHECKS = [(name, fn, True), ...] of the tree's own institutional gate — static AST."""
    tree = ast.parse(_read(root, "tools/check_institutional_correctness.py"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "CHECKS" for t in node.targets):
            if not isinstance(node.value, ast.List):
                raise LookupError("CHECKS is not a list literal")
            names = []
            for elt in node.value.elts:
                if isinstance(elt, ast.Tuple) and len(elt.elts) >= 3:
                    nm, en = elt.elts[0], elt.elts[2]
                    if (isinstance(nm, ast.Constant) and isinstance(nm.value, str)
                            and isinstance(en, ast.Constant) and en.value is True):
                        names.append(nm.value)
            if not names:
                raise LookupError("CHECKS carries no enforced entry — an empty roster is a broken read")
            return sorted(names)
    raise LookupError("CHECKS not found")


_TOOL_TOKEN_RE = re.compile(r"tools[/\\]([A-Za-z0-9_]+)\.py")
_TOOL_MODULE_RE = re.compile(r"\btools\.([A-Za-z0-9_]+)\b")


def hook_wiring_files(root: Path) -> list[str]:
    """The live host wirings, from the seam's own enumeration in tools/stop_chain.py
    (HOOK_WIRINGS) when present; the two known hosts otherwise."""
    try:
        src = _read(root, "tools/stop_chain.py")
        tree = ast.parse(src)
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == "HOOK_WIRINGS" for t in node.targets):
                out = []
                for elt in ast.walk(node.value):
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str) and elt.value.endswith((".json",)):
                        out.append(elt.value)
                if out:
                    return sorted(set(out))
    except LookupError:
        pass
    return [".claude/settings.json", ".cursor/hooks.json"]


def hook_guard_modules(root: Path) -> list[str]:
    """Every executable the hook wiring runs on an event: the tools named in a hook command
    (chain entries and bare guards) plus every member of the `*_CHAIN` rosters those chain
    executors declare. The canonical enumeration of the hook seam (AGENTS.md Close
    contract): a guard wired into either host is a member the day it is wired."""
    mods: set[str] = set()
    for rel in hook_wiring_files(root):
        p = root / rel
        if not p.is_file():
            continue
        for tok in _TOOL_TOKEN_RE.findall(p.read_text(encoding="utf-8", errors="replace")):
            mods.add(tok)
    for chain in [m for m in sorted(mods) if m.endswith("_chain")]:
        p = root / "tools" / f"{chain}.py"
        if not p.is_file():
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id.endswith("_CHAIN") for t in node.targets):
                for c in ast.walk(node.value):
                    if isinstance(c, ast.Constant) and isinstance(c.value, str) and c.value.startswith("tools."):
                        mods.add(c.value.split(".", 1)[1])
    if not mods:
        raise LookupError("no hook wiring names a tool — the hook seam is unreadable")
    return sorted(f"tools/{m}.py" for m in mods if (root / "tools" / f"{m}.py").is_file())


def _hooks_fail_closed_status(root: Path) -> dict[str, ObligationResult]:
    """Run every hook executable on an UNREADABLE payload; a guard that exits 0 on input it
    cannot read waves the event through (REPAIR 5). Exit 2 is the hosts' block code; any
    non-zero exit is a refusal."""
    out: dict[str, ObligationResult] = {}
    for rel in hook_guard_modules(root):
        try:
            r = subprocess.run([sys.executable, str(root / rel)], cwd=str(root),
                               input="{not json", capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=120)
            rc = r.returncode
        except (OSError, subprocess.SubprocessError) as e:
            out[rel] = ObligationResult("INVALID", f"could not execute: {e}")
            continue
        out[rel] = (ObligationResult("PROVEN", f"exit {rc} on unreadable payload") if rc != 0
                    else ObligationResult("FAIL", "exit 0 on an unreadable payload — fails OPEN"))
    return out


def remote_invoked_tools(root: Path) -> set[str]:
    """Tool basenames the required remote workflows execute, transitively through imports:
    tokens on workflow `run:` lines, plus everything under tools/ those tools import."""
    seen: set[str] = set()
    direct: set[str] = set()
    for wf in workflow_files(root):
        text = (root / wf).read_text(encoding="utf-8", errors="replace")
        for tok in _TOOL_TOKEN_RE.findall(text):
            direct.add(tok)
        for m in re.finditer(r"python\s+-m\s+([A-Za-z0-9_\.]+)", text):
            direct.add(m.group(1))
    for tok in sorted(direct):
        _tools_imports(root, f"tools/{tok}.py", seen)
    return direct | {s.removeprefix("tools/").removesuffix(".py") for s in seen}


def _precommit_parity_status(root: Path) -> dict[str, ObligationResult]:
    """Per local hook: its deciding owner (the last tools/ token of the entry, or the
    `python -m <module>` it runs) is executed by a remote workflow, directly or through
    the delta gate's imports. A hook whose owner never runs remotely is a rule a `SKIP=`
    or `--no-verify` locally turns into a remotely admissible violation."""
    remote = remote_invoked_tools(root)
    out: dict[str, ObligationResult] = {}
    for hook, entry in precommit_hook_entries(root).items():
        toks = _TOOL_TOKEN_RE.findall(entry)
        m = re.search(r"python\s+-m\s+([A-Za-z0-9_\.]+)", entry)
        owner = toks[-1] if toks else (m.group(1) if m else entry.split()[0])
        if owner in remote:
            out[hook] = ObligationResult("PROVEN", f"owner {owner} runs remotely")
        else:
            out[hook] = ObligationResult("MISSING", f"owner {owner} is executed by no workflow")
    return out


def precommit_hooks(root: Path) -> list[str]:
    """Hook ids of .pre-commit-config.yaml (the local commit seam's own enumeration)."""
    text = _read(root, ".pre-commit-config.yaml")
    ids = re.findall(r"^\s*-\s*id:\s*([A-Za-z0-9_\-]+)\s*$", text, re.M)
    if not ids:
        raise LookupError("no hook ids in .pre-commit-config.yaml")
    return sorted(ids)


def precommit_hook_entries(root: Path) -> dict[str, str]:
    text = _read(root, ".pre-commit-config.yaml")
    out: dict[str, str] = {}
    cur = None
    for line in text.splitlines():
        m = re.match(r"^\s*-\s*id:\s*([A-Za-z0-9_\-]+)\s*$", line)
        if m:
            cur = m.group(1)
            continue
        m = re.match(r"^\s*entry:\s*(.+?)\s*$", line)
        if m and cur:
            out[cur] = m.group(1)
    return out


def workflow_files(root: Path) -> list[str]:
    """Every workflow GitHub can run: the directory IS the population by GitHub's definition."""
    d = root / ".github" / "workflows"
    if not d.is_dir():
        raise LookupError(".github/workflows missing")
    return sorted(f".github/workflows/{p.name}" for p in d.iterdir() if p.suffix in (".yml", ".yaml"))


def _tools_imports(root: Path, rel: str, seen: set[str]) -> None:
    """Transitive tools/* modules imported by `rel` (module-level or in-function)."""
    p = root / rel
    if rel in seen or not p.is_file():
        return
    seen.add(rel)
    try:
        tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return
    names: set[str] = set()
    # a tool a script RUNS (subprocess argv, `python tools/x.py`) is part of its behaviour
    # exactly as an import is; the delta gate runs the institutional gate this way.
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for tok in _TOOL_TOKEN_RE.findall(node.value):
                names.add(tok)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            mod = node.module
            if mod.startswith("tools."):
                names.add(mod.split(".", 1)[1].split(".")[0])
            elif node.level == 0 and (root / "tools" / f"{mod}.py").is_file() and rel.startswith("tools/"):
                names.add(mod)                      # bare sibling import used when run as a script
            if mod == "tools":
                for a in node.names:
                    names.add(a.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("tools."):
                    names.add(a.name.split(".", 1)[1].split(".")[0])
    for n in sorted(names):
        _tools_imports(root, f"tools/{n}.py", seen)


def trust_anchor_paths(root: Path) -> list[str]:
    """The files whose content decides what the enforcement path DOES, derived from the
    enforcement wiring itself (no hand list): hook wirings and the guard modules they run,
    the pre-commit config and the tools its entries run, every workflow, the institutional
    gate and everything under tools/ it imports, the delta gate, this module and the
    retirement manifest. A candidate change to any of them is judged by the BASE copy and
    lands only with a base-side AUTHORIZE row (REPAIR 3)."""
    anchors: set[str] = set(hook_wiring_files(root))
    anchors.update(hook_guard_modules(root))
    anchors.add(".pre-commit-config.yaml")
    for entry in precommit_hook_entries(root).values():
        for tok in _TOOL_TOKEN_RE.findall(entry):
            anchors.add(f"tools/{tok}.py")
    anchors.update(workflow_files(root))
    for wf in workflow_files(root):
        for tok in _TOOL_TOKEN_RE.findall((root / wf).read_text(encoding="utf-8", errors="replace")):
            anchors.add(f"tools/{tok}.py")
    anchors.update({"tools/check_institutional_correctness.py", "tools/check_delta_adds_no_debt.py",
                    "governance/acceptance.py", "governance/retired_checks.md"})
    seen: set[str] = set()
    for a in sorted(anchors):
        if a.startswith("tools/") and a.endswith(".py"):
            _tools_imports(root, a, seen)
    anchors.update(seen)
    return sorted(a for a in anchors if (root / a).is_file())


def ui_pages(root: Path) -> list[str]:
    """Static HTML pages the router serves: PAGE routes of the provenance root population
    (reconciled bidirectionally with server.py by tests/test_provenance_v1.py) resolved to
    the `static/*.html` literal their handler reads. The router is the authority; a file
    under static/ that no route serves is not a page."""
    sys.path.insert(0, str(root))
    try:
        ns: dict = {}
        exec(compile(_read(root, "governance/provenance_roots.py"), "provenance_roots", "exec"), ns)
        routes = ns["ROUTES"]
    finally:
        sys.path.pop(0)
    page_routes = {r for r, (cls, _p) in routes.items() if cls == "PAGE"}
    src = _read(root, "server.py")
    tree = ast.parse(src)
    pages: set[str] = set()
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        routed = None
        for d in node.decorator_list:
            if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                    and d.func.attr in ("get", "post") and d.args
                    and isinstance(d.args[0], ast.Constant) and d.args[0].value in page_routes):
                routed = d.args[0].value
        if routed is None:
            continue
        for c in ast.walk(node):
            if isinstance(c, ast.Constant) and isinstance(c.value, str) and c.value.endswith(".html"):
                rel = c.value.replace("\\", "/")
                if "static/" in rel:
                    pages.add(rel[rel.index("static/"):])
                elif "/" not in rel:
                    pages.add(f"static/{rel}")
    if not pages:
        raise LookupError("no PAGE route resolves to a static HTML file")
    return sorted(p for p in pages if (root / p).is_file())


def provenance_roots(root: Path) -> list[str]:
    """Every material root of the provenance population (MarketState fields, engine inputs,
    PRODUCER routes) — the ONE-computation obligation set (PA-2). Proven = a producer row
    closes the root; OPEN = MISSING. Structural closure is not semantic truth; the row's
    criterion says so."""
    ns: dict = {}
    exec(compile(_read(root, "governance/provenance_roots.py"), "provenance_roots", "exec"), ns)
    out: list[str] = []
    for r, (cls, prod) in ns["ROUTES"].items():
        if cls == "PRODUCER":
            out.append(f"route:{r}")
    for f in ns["MARKET_STATE"]:
        out.append(f"market_state:{f}")
    for (file, fn), args in ns["ENGINE_INPUTS"].items():
        for a in args:
            out.append(f"engine:{file}:{fn}:{a}")
    if not out:
        raise LookupError("provenance roots empty")
    return sorted(out)


def _provenance_root_status(root: Path) -> dict[str, ObligationResult]:
    ns: dict = {}
    exec(compile(_read(root, "governance/provenance_roots.py"), "provenance_roots", "exec"), ns)
    out: dict[str, ObligationResult] = {}
    for r, (cls, prod) in ns["ROUTES"].items():
        if cls == "PRODUCER":
            out[f"route:{r}"] = ObligationResult("PROVEN" if prod else "MISSING", prod or "OPEN root")
    for f, (cat, prod) in ns["MARKET_STATE"].items():
        out[f"market_state:{f}"] = ObligationResult("PROVEN" if prod else "MISSING", prod or f"OPEN ({cat})")
    for (file, fn), args in ns["ENGINE_INPUTS"].items():
        for a, prod in args.items():
            out[f"engine:{file}:{fn}:{a}"] = ObligationResult("PROVEN" if prod else "MISSING", prod or "OPEN")
    return out


AUTHORITIES = {
    "governance.acceptance:enforced_check_roster": enforced_check_roster,
    "governance.acceptance:trust_anchor_paths": trust_anchor_paths,
    "governance.acceptance:hook_guard_modules": hook_guard_modules,
    "governance.acceptance:precommit_hooks": precommit_hooks,
    "governance.acceptance:ui_pages": ui_pages,
    "governance.acceptance:provenance_roots": provenance_roots,
}


def resolve_population(scope: str, root: Path) -> list[str]:
    """S_R for a FINITE row. `delta:<name>` populations exist only inside the delta gate
    (they are the set of things this change does) and are injected by it."""
    if scope.startswith("delta:"):
        raise LookupError(f"{scope} is a delta population — only the delta gate can enumerate it")
    fn = AUTHORITIES.get(scope)
    if fn is None:
        raise LookupError(f"no canonical authority registered for {scope!r}")
    return list(fn(root))


# ── evidence records (REPAIR 4) ──────────────────────────────────────────────────────────
EVIDENCE_DIR = "reports/evidence"
_REQUIRED_FIELDS = ("requirement_id", "evidence_class", "candidate_sha", "environment", "source",
                    "captured_at")


def _git(root: Path, *args: str) -> str | None:
    try:
        r = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _code_unchanged_since(root: Path, sha: str) -> tuple[bool, str]:
    """EXACT_HEAD: the evidence's sha must be an ancestor of the tree's HEAD with no source
    change between them (evidence files and governance prose excluded). Evidence for a
    commit that the code has moved past is evidence for something else."""
    head = _git(root, "rev-parse", "HEAD")
    if not head:
        return False, "tree has no HEAD"
    if _git(root, "merge-base", "--is-ancestor", sha, "HEAD") is None:
        return False, f"{sha[:8]} is not an ancestor of HEAD {head.strip()[:8]}"
    diff = _git(root, "diff", "--name-only", f"{sha}..HEAD", "--", ".",
                f":!{EVIDENCE_DIR}", ":!governance/*.md", ":!OPEN_ITEMS.md", ":!reports/*.md")
    if diff is None:
        return False, "diff unavailable"
    changed = [l for l in diff.splitlines() if l.strip()]
    if changed:
        return False, f"code moved past the evidence: {changed[:5]}"
    return True, ""


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


def evidence_adversarial(work: Path | None = None) -> tuple[int, int, list[str]]:
    """The evidence-class invariant carries its own falsifiers (REQ-GOV-EVIDENCE-CLASS is an
    OPEN requirement: it is proven by attacks failing, never by an example passing).
    Builds a scratch git repository with two commits and drives every mutation class the
    mission names — NC-13 synthetic-as-live, NC-14 wrong identity, NC-15 missing provenance,
    plus the honest positive (NC-21) — through `evidence_status`. Returns
    (mutations_run, mutations_caught, failures)."""
    import tempfile
    req = Requirement("REQ-X", "OPEN", "PRODUCT", "evidence:REQ-X",
                      "LIVE_RTH+EXACT_HEAD+RUNTIME_IDENTITY", "-", "", 0)
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="evidence-nc-") as tmp:
        root = Path(work or tmp) / "repo"
        root.mkdir(parents=True, exist_ok=True)
        env = {"GIT_AUTHOR_NAME": "nc", "GIT_AUTHOR_EMAIL": "nc@local",
               "GIT_COMMITTER_NAME": "nc", "GIT_COMMITTER_EMAIL": "nc@local"}

        def g(*a: str) -> str:
            import os
            r = subprocess.run(["git", *a], cwd=str(root), capture_output=True, text=True,
                               env={**os.environ, **env}, check=True)
            return r.stdout.strip()
        g("init", "-q")
        (root / "app.py").write_text("x = 1\n", encoding="utf-8")
        g("add", "app.py"); g("commit", "-q", "-m", "one")
        sha1 = g("rev-parse", "HEAD")
        base_rec = {"requirement_id": "REQ-X", "evidence_class": "LIVE_RTH", "candidate_sha": sha1,
                    "environment": "LIVE_RTH", "source": "capture.mjs", "captured_at": "2026-09-10T14:00:00Z",
                    "population": {"authority": "router", "digest": "abc", "count": 7},
                    "runtime_identity": {"git_sha": sha1, "dirty": False}}
        cases = [
            ("NC-21 honest positive", dict(base_rec), "PROVEN"),
            ("NC-13 synthetic offered as live (class ISOLATED_E2E)", {**base_rec, "evidence_class": "ISOLATED_E2E"}, "INVALID"),
            ("NC-13 payload label live:true is not provenance", {**base_rec, "environment": "OFFLINE_CI", "payload": {"live": True, "source": "terrain_live_cache"}}, "INVALID"),
            ("NC-14 wrong sha", {**base_rec, "candidate_sha": "0" * 40, "runtime_identity": {"git_sha": "0" * 40, "dirty": False}}, "INVALID"),
            ("NC-14 dirty runtime", {**base_rec, "runtime_identity": {"git_sha": sha1, "dirty": True}}, "INVALID"),
            ("NC-15 missing runtime identity", {k: v for k, v in base_rec.items() if k != "runtime_identity"}, "INVALID"),
            ("NC-15 missing population", {k: v for k, v in base_rec.items() if k != "population"}, "INVALID"),
            ("NC-15 missing source", {k: v for k, v in base_rec.items() if k != "source"}, "INVALID"),
        ]
        run = caught = 0
        for name, rec, expect in cases:
            run += 1
            got = evidence_status(rec, req, root).status
            if got == expect:
                caught += 1
            else:
                failures.append(f"{name}: expected {expect}, got {got}")
        # NC-14 code moved past the evidence: a second commit that changes source
        (root / "app.py").write_text("x = 2\n", encoding="utf-8")
        g("add", "app.py"); g("commit", "-q", "-m", "two")
        run += 1
        got = evidence_status(dict(base_rec), req, root).status
        if got == "INVALID":
            caught += 1
        else:
            failures.append(f"NC-14 code moved past evidence sha: expected INVALID, got {got}")
    return run, caught, failures


def evidence_records(root: Path, req_id: str) -> list[tuple[Path, dict]]:
    d = root / EVIDENCE_DIR / req_id
    out: list[tuple[Path, dict]] = []
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.json")):
        try:
            out.append((p, json.loads(p.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            out.append((p, {"_unreadable": True}))
    return out


# ── verdict computation ──────────────────────────────────────────────────────────────────
def _waived(req: Requirement, auths: list[Requirement]) -> list[str]:
    out = []
    for a in auths:
        if a.scope.startswith("waive:"):
            _w, rid, obl = (a.scope.split(":", 2) + ["", ""])[:3]
            if rid == req.id and obl:
                out.append(obl)
    return out


def _accepted(req: Requirement, accs: list[Requirement], root: Path) -> bool:
    head = (_git(root, "rev-parse", "HEAD") or "").strip()
    for a in accs:
        rid, sha = a.scope.split("@", 1)
        if rid == req.id and head.startswith(sha):
            return True
    return False


def evaluate(root: Path, contract: list[Requirement], base_contract: list[Requirement] | None = None,
             injected: dict[str, dict] | None = None) -> list[Verdict]:
    """Compute a Verdict per requirement of `contract` against the tree at `root`.

    `base_contract` is the TRUSTED contract; when given, only ITS authorizations and
    acceptances count (W_R from base), and the requirements judged are the base's plus any
    stricter rows the candidate adds. `injected` carries delta populations and results the
    delta gate measured (`{req_id: {"canonical": [...], "obligations": {...}, ...}}`)."""
    trusted = base_contract if base_contract is not None else contract
    auths, accs = authorizations(trusted), acceptances(trusted)
    judged: dict[str, Requirement] = {r.id: r for r in requirements(trusted)}
    for r in requirements(contract):
        judged.setdefault(r.id, r)             # stricter candidate additions are recognized
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
            v.notes.append("no canonical authority identified — NOT_PROVEN by construction")
        elif req.scope.startswith("evidence:"):
            # one obligation: the requirement itself, proven by evidence records of class.
            v.canonical = [req.id]
            recs = evidence_records(root, req.id)
            best: ObligationResult | None = None
            for p, rec in recs:
                if rec.get("_unreadable"):
                    st = ObligationResult("INVALID", f"{p.name} unreadable")
                else:
                    st = evidence_status(rec, req, root)
                if st.status == "PROVEN":
                    best = st
                    break
                if best is None or best.status == "MISSING":
                    best = st
            if best is None:
                best = ObligationResult("MISSING", "no evidence record")
            if best.status == "PROVEN" and "OPERATOR_ACCEPT" in req.proof_flags and not _accepted(req, accs, root):
                best = ObligationResult("MISSING", "evidence valid; operator ACCEPT row for this head absent (cannot self-certify)")
            v.obligations = {req.id: best}
        elif req.kind == "FINITE":
            try:
                v.canonical = resolve_population(req.scope, root)
            except LookupError as e:
                v.authority_resolved = False
                v.notes.append(str(e))
                verdicts.append(v)
                continue
            verifier = VERIFIERS.get(req.scope)
            if verifier is None:
                v.obligations = {o: ObligationResult("MISSING", "no verifier ran in this context") for o in v.canonical}
            else:
                v.obligations = verifier(root, v.canonical)
        elif req.scope.startswith("narrowing:"):
            # An OPEN requirement with NO boundary authority yet (NOT_PROVEN by construction)
            # whose known LOCAL NARROWINGS are detected by a named institutional check: any
            # narrowing the check finds on this tree is a FAIL of the requirement (NC-03),
            # and a clean run is never a proof of the open property.
            v.authority_resolved = False
            check_name = req.scope.split(":", 1)[1]
            try:
                v.narrowing_violations = narrowing_violations(root, check_name)
            except Exception as e:  # noqa: BLE001 - an unmeasurable narrowing detector is a bypass, not a pass
                v.narrowing_violations = [f"narrowing detector {check_name} unmeasurable: {e!r}"]
            v.notes.append(f"boundary authority NONE; local narrowings measured by check {check_name}")
        else:   # OPEN with an invariant scope the gate did not inject
            v.authority_resolved = False
            v.notes.append("open-domain invariant not measured in this run")
        verdicts.append(v)
    return verdicts


def narrowing_violations(root: Path, check_name: str) -> list[str]:
    """Run ONE named check of the tree's institutional gate and return its violations as
    strings. The gate module is loaded from `root` (in the judged tree that is the BASE
    validator overlaid on candidate data)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_cic_narrowing", root / "tools" / "check_institutional_correctness.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    sys.path.insert(0, str(root))
    try:
        spec.loader.exec_module(mod)   # type: ignore[union-attr]
    finally:
        sys.path.pop(0)
    fn = None
    for name, f, _enforced in mod.CHECKS:
        if name == check_name:
            fn = f
    if fn is None:
        raise LookupError(f"{check_name} is not a registered check")
    return [str(v) for v in fn()]


def _ui_pages_status(root: Path, pages: list[str]) -> dict[str, ObligationResult]:
    """Per page: the static-binding predicate of tools/check_ui_data_integration.py."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_uidi", root / "tools" / "check_ui_data_integration.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)   # type: ignore[union-attr]
    hits = mod.static_binding_violations(pages=pages, repo=root)
    bad: dict[str, list[str]] = {}
    for rel, line, msg in hits:
        bad.setdefault(rel, []).append(f"{line}: {msg}")
    return {p: (ObligationResult("FAIL", "; ".join(bad[p][:3])) if p in bad else ObligationResult("PROVEN", "static binding clean"))
            for p in pages}


#: Standalone verifiers, keyed by the SCOPE authority whose population they judge. The
#: population comes from AUTHORITIES; a verifier only says PROVEN/FAIL/MISSING per member.
#: Populations judged across two trees (`delta:*`, the roster, the anchors) are verified by
#: the delta gate and injected.
VERIFIERS = {
    "governance.acceptance:provenance_roots": lambda root, pop: _provenance_root_status(root),
    "governance.acceptance:ui_pages": _ui_pages_status,
    "governance.acceptance:hook_guard_modules": lambda root, pop: _hooks_fail_closed_status(root),
    "governance.acceptance:precommit_hooks": lambda root, pop: _precommit_parity_status(root),
}


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
        shown = 0
        unproven = [o for o in v.applicable
                    if v.obligations.get(o, ObligationResult("MISSING")).status != "PROVEN"]
        for o in unproven:
            st = v.obligations.get(o, ObligationResult("MISSING"))
            if shown >= _MAX_LISTED:
                lines.append(f"  ... and {len(unproven) - shown} more (see --json for every obligation)")
                break
            lines.append(f"  {st.status}: {o} - {st.detail}")
            shown += 1
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
            "bypass": v.bypass, "adversarial_run": v.adversarial_run,
            "adversarial_caught": v.adversarial_caught, "notes": v.notes,
            "obligations": {o: {"status": s.status, "detail": s.detail} for o, s in v.obligations.items()
                            if o in set(v.applicable)},
        } for v in verdicts],
        "summary": {k: sum(1 for v in verdicts if v.verdict == k) for k in VERDICTS},
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Compute the acceptance verdicts of ONE tree")
    ap.add_argument("--tree", default=str(REPO), help="tree root to judge (default: this repo)")
    ap.add_argument("--contract", default=None, help="OPEN_ITEMS.md to read the TRUSTED contract from (default: the tree's own)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    root = Path(args.tree).resolve()
    cand = load_contract(root)
    base = parse_contract(Path(args.contract).read_text(encoding="utf-8", errors="replace")) if args.contract else None
    verdicts = evaluate(root, cand, base_contract=base)
    if args.json:
        print(json.dumps(report_json(verdicts), indent=1))
    else:
        print("\n".join(report_lines(verdicts)))
    return 0 if all(v.verdict == "PASS" for v in verdicts if v.requirement.gate == "MERGE") else 1


if __name__ == "__main__":
    sys.exit(main())
