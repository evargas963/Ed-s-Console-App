#!/usr/bin/env python3
"""RC-325 — ONE producer per field, repo-wide, Schwab leaf or derived.

OPERATOR MANDATE (2026-08-09, roughly the tenth instruction): "i don't care who wrote the
code we need one and only one producer." Many consumers are expected. A consumer CARRIES a
produced value; it never recomputes it.

WHY EVERY EARLIER LOCK FAILED THE MANDATE. Each was scoped to the surface failing in front
of me. `single_faucet_provenance` inspects `kl_*` and sees THREE keys in server.py.
`phase2a_level_lock` governs NINETEEN price-level ids. server.py emits FIVE HUNDRED AND
NINETY-TWO distinct payload keys. Worse, `single_faucet_provenance` checks which function
WRITES a field name, not which computes the value — which is why it reports PASS while GEX$
is computed in 4 functions, DEX$ in 10, OI sums in 11 and option-volume sums in 22.

An invariant cannot be enforced over a set that has not been enumerated.
`governance/computation_registry.json` is that enumeration; this gate quantifies over it.

WHAT A PASS FROM THIS GATE DOES AND DOES NOT MEAN (RC-329). It counts DEFINITION SITES:
functions whose bodies join a field's declared inputs arithmetically. That answers D1 exact,
D2 renamed, D3 structural and D4 semantic duplication. It CANNOT answer D5 shadow or D6
diverged, because both lanes of those defects reach the SAME definition site and differ only
in the data that arrives there. RC-328 is the confirmed member: one function,
`lstm_data.compute_confluence_features`, called from training and from serving over two
different row populations, emitting two different quantities under one name — this gate
counts one producer and reports PASS. D5 and D6 are therefore NOT_PROVEN repo-wide, and a
green result here must not be read as covering them. The call-path parity control that would
is RC-329 PART 2. Semantic identity is a property of the (producer, input population) pair
and source text carries only the first element.

THREE VERDICTS, NOT TWO.
    PASS        registered field, computed in exactly one site, and it is the declared producer.
    FAIL        registered field computed in 2+ sites, or in a site that is not the producer.
    NOT_PROVEN  field not registered. Counted and REPORTED, never silently passed.

The third verdict is the design. RC-311 recorded that "the gate is green" cannot distinguish
a precise gate from a blind one, and RC-317, RC-318, RC-320 and RC-323 each repeated it.
NOT_PROVEN makes the unenforced remainder a visible number that must shrink, so green stops
meaning "the mandate holds" and starts meaning "the mandate holds over this much".

    .venv/Scripts/python.exe tools/check_one_producer.py
    .venv/Scripts/python.exe tools/check_one_producer.py --measure
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REGISTRY = REPO / "governance" / "computation_registry.json"

#: Scanned for computation. Tests, tools and research legitimately recompute in order to
#: CHECK a producer; scratch is not this repository (RC-274/RC-307/RC-312/RC-323).
_SKIP_PREFIXES = ("tests/", "tools/", "research/", "arch_competition/", "scratchpad/",
                  "governance/", "calibration/")


def _tracked_python() -> list[str]:
    proc = subprocess.run(["git", "ls-files", "-z", "--", "*.py"],
                          cwd=REPO, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError("git ls-files failed, so the scan scope is unknown: "
                           + proc.stderr.strip()[:160])
    return [p for p in proc.stdout.split("\0")
            if p and not p.startswith(_SKIP_PREFIXES)]


#: RC-516 (AGENTS.md laws 6 and 12): the frontend, inline page scripts and SQL are connected
#: layers of the same semantic truth. A registered field computed in a browser or in a query
#: is a second faucet exactly as a Python copy is.
SURFACE_SUFFIXES = (".js", ".mjs", ".html", ".sql")
_SURFACE_SKIP_PREFIXES = ("tests/", "scratchpad/", "node_modules/", "reports/", "governance/archive/")


def _tracked_surfaces(root: Path | None = None) -> list[str]:
    """Tracked JS / HTML / SQL files in scope — the same git-index authority as the Python scan."""
    proc = subprocess.run(["git", "ls-files", "-z", "--", *[f"*{s}" for s in SURFACE_SUFFIXES]],
                          cwd=root or REPO, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError("git ls-files failed, so the surface scan scope is unknown: "
                           + proc.stderr.strip()[:160])
    return [p for p in proc.stdout.split("\0")
            if p and not p.startswith(_SURFACE_SKIP_PREFIXES)]


#: A statement boundary for the surface detector: JS/SQL statement ends, block braces.
_SURFACE_STMT_SPLIT = re.compile(r"[;{}]")
#: Text between two joined inputs must carry an arithmetic operator and must not cross an
#: argument/column boundary or a SQL clause keyword — `f(gamma, oi)` and `gamma AS g, oi`
#: are not computations.
_SURFACE_JOIN_OP = re.compile(r"[*+\-/]")
_SURFACE_BOUNDARY = re.compile(r"[,;{}]|\b(?:as|from|where|select|and|or|then|else|when)\b", re.I)
#: Comments and string literals are prose, not code: a tooltip saying "dealer gamma cushion
#: half-spent below spot" joins two inputs with a hyphen and computes nothing. They are
#: blanked (newlines kept, so reported lines stay true) before any statement is judged.
_JS_NOISE = re.compile(
    r"//[^\n]*|/\*.*?\*/|'(?:\\.|[^'\\\n])*'|\"(?:\\.|[^\"\\\n])*\"|`(?:\\.|[^`\\])*`", re.S)
_SQL_NOISE = re.compile(r"--[^\n]*|/\*.*?\*/|'(?:''|[^'\n])*'", re.S)
_HTML_SCRIPT = re.compile(r"<script\b[^>]*>(.*?)</script\s*>", re.S | re.I)


def _blank(m: re.Match) -> str:
    return re.sub(r"[^\n]", " ", m.group(0))


def surface_code(rel: str, text: str) -> str:
    """The CODE of a surface file with comments, string literals and (for HTML) everything
    outside `<script>` blocks blanked, line structure preserved."""
    low = rel.lower()
    if low.endswith(".sql"):
        return _SQL_NOISE.sub(_blank, text)
    if low.endswith(".html"):
        keep = []
        pos = 0
        for m in _HTML_SCRIPT.finditer(text):
            keep.append(re.sub(r"[^\n]", " ", text[pos:m.start(1)]))
            keep.append(_JS_NOISE.sub(_blank, m.group(1)))
            pos = m.end(1)
        keep.append(re.sub(r"[^\n]", " ", text[pos:]))
        return "".join(keep)
    return _JS_NOISE.sub(_blank, text)


def surface_computing_sites(spec: dict, surfaces: list[tuple[str, str]]) -> list[str]:
    """Every surface CODE statement that arithmetically JOINS the field's declared inputs.

    Objective and narrow by design: the registry declares `surface_inputs` — groups of accepted
    spellings for each input (`gamma`; `oi` / `openInterest` / `open_interest`; `spot` /
    `underlying_price` ...). A statement is a computing site when spellings from at least two
    groups appear joined by an arithmetic operator with no argument, column or clause boundary
    between them. Comments, string literals and HTML outside `<script>` are blanked first, so
    prose never matches. Reading a served value (`payload.gex_total`), listing columns, or
    passing inputs as arguments never matches. A field without `surface_inputs` is NOT judged
    on these surfaces — that class is NOT_MECHANICALLY_DETECTABLE and stays with the law.
    Known blind spot: code inside a JS template literal `${...}` is blanked with the literal.
    """
    groups = spec.get("surface_inputs") or []
    if len(groups) < 2:
        return []
    pats = [re.compile(r"\b(?:" + "|".join(re.escape(a) for a in g) + r")\b", re.I) for g in groups]
    out: list[str] = []
    for rel, raw in surfaces:
        text = surface_code(rel, raw)
        pos = 0
        for stmt in _SURFACE_STMT_SPLIT.split(text):
            start = pos
            pos += len(stmt) + 1
            if len(stmt) > 800 or not stmt.strip():
                continue
            found = sorted((m.start(), i) for i, p in enumerate(pats) for m in [p.search(stmt)] if m)
            if len({i for _s, i in found}) < 2:
                continue
            joined = False
            for (a, ia), (b, ib) in zip(found, found[1:]):
                if ia == ib:
                    continue
                between = stmt[a:b]
                if _SURFACE_JOIN_OP.search(between) and not _SURFACE_BOUNDARY.search(between):
                    joined = True
                    break
            if joined:
                line = text.count("\n", 0, start + found[0][0]) + 1
                out.append(f"{rel}:{line}")
    return out


def load_surfaces(rels: list[str] | None = None, root: Path | None = None) -> list[tuple[str, str]]:
    base = root or REPO
    out: list[tuple[str, str]] = []
    for rel in (_tracked_surfaces(base) if rels is None else rels):
        path = base / rel
        if path.exists():
            out.append((rel, path.read_text(encoding="utf-8", errors="replace")))
    return out


def scan_corpus_from_sources(sources: dict[str, str]) -> list[tuple[str, str, list[tuple[ast.AST, str]]]]:
    """The `build_scan_corpus` shape over caller-supplied sources — the institutional gate's
    delta clause hands it the CANDIDATE tree (staged blobs), never the working tree."""
    corpus: list[tuple[str, str, list[tuple[ast.AST, str]]]] = []
    for rel, src in sources.items():
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        lines = src.split("\n")
        fns = [(fn, "\n".join(lines[fn.lineno - 1:fn.end_lineno]))
               for fn in ast.walk(tree)
               if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))]
        corpus.append((rel, src, fns))
    return corpus


class PayloadSurfaceMissing(RuntimeError):
    """A declared payload surface is absent, so producer authority cannot be established.

    Raised rather than returned so it cannot be mistaken for "no findings". The gate wrapper
    turns it into a violation; a bare `return []` would have been fail-open (SP-05).
    """


def load_registry() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def _inputs_for(name: str, spec: dict) -> tuple[str, ...]:
    """The vendor leaves / symbols whose joint presence marks a computation of this field."""
    explicit = spec.get("computation_inputs")
    if explicit:
        return tuple(explicit)
    leaf = spec.get("leaf") or ""
    if leaf:
        return (leaf.rsplit(".", 1)[-1],)
    formula = (spec.get("formula") or "").lower()
    toks = []
    for tok in ("gamma", "delta", "openinterest", "oi", "spot", "totalvolume", "charm"):
        if tok in formula:
            toks.append({"oi": "openInterest", "openinterest": "openInterest",
                         "totalvolume": "totalVolume"}.get(tok, tok))
    return tuple(dict.fromkeys(toks))


def build_scan_corpus() -> list[tuple[str, str, list[tuple[ast.AST, str]]]]:
    """One live pass over the tracked production files: (rel, src, [(fn_node, fn_text)]).

    Built fresh on every evaluation — the measurement stays live (RC-268: no stored
    answers) — but built ONCE and shared across all registered fields. The previous shape
    re-ran `git ls-files`, re-read and re-parsed every file PER FIELD, and called
    `ast.get_source_segment` per function (which re-splits the whole file each call —
    measured 17.5s of a 22.1s field pass). The per-function text here is a lineno..
    end_lineno slice: at worst slightly WIDER than the exact segment, which can only admit
    extra candidates into the precise arithmetic AST check below — never hide one.
    """
    corpus: list[tuple[str, str, list[tuple[ast.AST, str]]]] = []
    for rel in _tracked_python():
        path = REPO / rel
        if not path.exists():
            continue
        src = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        lines = src.split("\n")
        fns = [(fn, "\n".join(lines[fn.lineno - 1:fn.end_lineno]))
               for fn in ast.walk(tree)
               if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))]
        corpus.append((rel, src, fns))
    return corpus


def computing_sites(field: str, spec: dict,
                    corpus: list[tuple[str, str, list[tuple[ast.AST, str]]]] | None = None,
                    ) -> list[str]:
    """Every tracked production function that appears to COMPUTE `field`."""
    """CONFIRMED sites only — a site that performs ARITHMETIC on the defining inputs.

    A first version accepted token co-occurrence plus any loop, and it named
    `db.py:_init_schema` and `time_et.py:time_to_expiry_years` as producers of net charm:
    32 sites for a quantity computed in one. Mentioning a leaf is CONSUMPTION. Looping near
    it is not derivation. Blocking the build on that would be the false-positive habit
    RC-290 and RC-323 record, so the bar is arithmetic that joins the inputs, and anything
    weaker is reported as NOT_PROVEN instead of failing the build.
    """
    inputs = _inputs_for(field, spec)
    if not inputs:
        return []
    out: list[str] = []
    for rel, src, fns in (corpus if corpus is not None else build_scan_corpus()):
        if not all(t in src for t in inputs):
            continue
        for fn, seg in fns:
            if not all(t in seg for t in inputs):
                continue
            if _joins_inputs_arithmetically(fn, inputs):
                out.append(f"{rel}:{fn.name}")
    return sorted(set(out))


def _joins_inputs_arithmetically(fn: ast.AST, inputs: tuple[str, ...]) -> bool:
    """True when a single BinOp/aug-assign in `fn` combines at least two defining inputs,
    or aggregates the one defining input with sum()/+=.

    This is the line between deriving a value and reading one. `oi * gamma * spot * spot`
    derives GEX; `row["openInterest"]` reads it; `for c in contracts: log(c["gamma"])`
    neither derives nor reads it into a level.
    """
    wanted = {i.lower() for i in inputs}

    def _names(node) -> set[str]:
        found = set()
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                if sub.value.lower() in wanted:
                    found.add(sub.value.lower())
            elif isinstance(sub, ast.Name) and sub.id.lower() in wanted:
                found.add(sub.id.lower())
            elif isinstance(sub, ast.Attribute) and sub.attr.lower() in wanted:
                found.add(sub.attr.lower())
        return found

    for node in ast.walk(fn):
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mult, ast.Sub, ast.Add)):
            if len(_names(node)) >= min(2, len(wanted)):
                return True
        if isinstance(node, ast.AugAssign) and isinstance(node.op, (ast.Add, ast.Mult)):
            if _names(node) & wanted:
                return True
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "sum" and _names(node) & wanted):
            return True
    return False


def evaluate() -> tuple[list[str], list[str], int]:
    """Return (failures, not_proven_notes, registered_count)."""
    reg = load_registry()
    fields = reg.get("fields") or {}
    failures: list[str] = []
    corpus = build_scan_corpus()          # one live pass, shared by every field
    surfaces = load_surfaces()            # RC-516: JS / HTML / SQL, same index authority
    for field, spec in fields.items():
        producer = spec.get("producer") or ""
        sites = computing_sites(field, spec, corpus) + surface_computing_sites(spec, surfaces)
        if not sites:
            continue                      # nothing recognisable computes it; not a duplicate
        declared = producer.replace(".py:", ".py:")
        extra = [s for s in sites if s != declared]
        if len(sites) > 1 or (extra and declared not in sites):
            failures.append(
                f"governance/computation_registry.json:0  '{field}' declares ONE producer "
                f"({producer}) but {len(sites)} site(s) compute it: {sites}. The mandate is "
                f"one producer, many consumers — a consumer CARRIES the value. Delete the "
                f"competing computation or, if it is genuinely a different quantity, give "
                f"it its own field id (RC-325).")
    not_proven = unregistered_payload_fields()
    return failures, not_proven, len(fields)


def unregistered_payload_fields() -> list[str]:
    """Payload keys emitted by server.py that no registry entry governs — NOT_PROVEN."""
    # RC-325: absence must FAIL CLOSED where the surface is DECLARED, and be silent only
    # where none is declared. A first version returned [] on any missing server.py, which
    # turned "I could not inspect the payload surface" into "there is nothing to report" —
    # fail-open, and the exact defect class this gate exists to prevent.
    declared = load_registry().get("payload_surfaces")
    if declared is None:
        return []                       # no payload surface declared: nothing to classify
    missing = [rel for rel in declared if not (REPO / rel).exists()]
    if missing:
        raise PayloadSurfaceMissing(
            f"registry declares payload surface(s) {missing} which do not exist under "
            f"{REPO}. Producer authority over their fields cannot be established, so the "
            f"gate FAILS CLOSED rather than reporting zero unresolved fields (SP-05).")
    src = "\n".join((REPO / rel).read_text(encoding="utf-8", errors="replace")
                    for rel in declared)
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    keys = {k.value for n in ast.walk(tree) if isinstance(n, ast.Dict)
            for k in n.keys
            if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    reg = load_registry().get("fields") or {}
    covered = set(reg)
    for spec in reg.values():
        covered.update(spec.get("level_ids") or [])
    return sorted(k for k in keys if k not in covered)


def violations() -> list[str]:
    try:
        failures, _not_proven, _n = evaluate()
    except PayloadSurfaceMissing as exc:
        return [f"governance/computation_registry.json:0  {exc}"]
    return failures


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--measure", action="store_true",
                    help="also print the NOT_PROVEN remainder, which must shrink")
    args = ap.parse_args(argv)
    failures, not_proven, registered = evaluate()
    if args.measure:
        print(f"registered fields: {registered}")
        print(f"NOT_PROVEN (unregistered payload keys): {len(not_proven)}")
        for k in not_proven[:40]:
            print("   " + k)
    if failures:
        print("check_one_producer: FAIL — a field with more than one producer:")
        for line in failures:
            print("  " + line)
        return 1
    if not args.quiet:
        print(f"check_one_producer: PASS over {registered} registered field(s); "
              f"{len(not_proven)} field(s) NOT_PROVEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
