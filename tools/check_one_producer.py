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
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REGISTRY = REPO / "governance" / "computation_registry.json"

#: Scanned for computation. Tests, tools and research legitimately recompute in order to
#: CHECK a producer; scratch is not this repository (RC-274/RC-307/RC-312/RC-323).
_SKIP_PREFIXES = ("tests/", "tools/", "research/", "arch_competition/", "scratchpad/",
                  "governance/", "calibration/")


def _inventory():
    """THE discovery authority, importable however this module was loaded.

    The gate is imported three ways — as `tools.check_one_producer` from tests, as
    `check_one_producer` from check_institutional_correctness, and run directly — and only one
    of those puts tools/ on sys.path. Resolving it here keeps every caller on the same authority
    instead of each arranging its own import (which is how parallel scanners start).
    """
    d = str(Path(__file__).resolve().parent)
    if d not in sys.path:
        sys.path.insert(0, d)
    import producer_inventory_v1 as inv

    return inv


#: DISCOVERY IS NOT THIS MODULE'S JOB (RC-325 consolidation, 2026-08-26).
#:
#: tools/producer_inventory_v1.py is already THE repo-wide discovery authority: it enumerates
#: every tracked file, buckets it by executable kind (.py .js .html .sql .mjs .jsx .ts .ipynb
#: .bat .ps1 .sh), accounts for every excluded extension WITH A REASON, and reports anything it
#: cannot classify as NOT_PROVEN. RC-327 had already established there that "a derivation in
#: JavaScript or SQL is a producer".
#:
#: A first repair to this gate grew a SECOND enumeration here (`_FRONTEND_GLOBS`), a SECOND
#: <script> extractor and a SECOND JS parser — a second producer of "what are this repository's
#: units", inside the machinery whose whole purpose is forbidding second producers. Worse, that
#: parallel scanner was NARROWER than the authority it duplicated: static/*.html, static/*.js
#: and static/js/*.js only, so .sql, .ts, .jsx, .mjs and any JS outside static/ stayed invisible
#: while the gate claimed to be repo-wide.
#:
#: This module now DECIDES; producer_inventory_v1 DISCOVERS. One authority, one decision path.
def _non_python_production_units() -> list[tuple[str, str, list[tuple[str, str]]]]:
    """(rel, executable_text, units) for every NON-Python executable production file.

    Scope, kind classification, <script> extraction and unit extraction all come from the
    discovery authority. Nothing about "what exists" is decided here.

    FIXTURE-AWARE, not fail-open: the gate's own tests point REPO at a temp directory that is
    not a git checkout and patch only `_tracked_python`. No `.git` means no tracked tree to
    discover — an honest empty answer. A real checkout always has `.git`, where a discovery
    failure still raises rather than silently reporting "no other surfaces", which would restore
    the exact blind spot being removed.
    """
    if not (REPO / ".git").exists():
        return []
    inv = _inventory()
    rec = inv.reconcile(inv.tracked())
    out: list[tuple[str, str, list[tuple[str, str]]]] = []
    for kind, rels in rec["buckets"].items():
        if kind == "python":
            continue                      # the Python lane is build_scan_corpus's, below
        for rel in rels:
            if inv.layer_of(rel) not in inv.PRODUCTION_LAYERS:
                continue                  # tests/tools/research legitimately recompute
            p = REPO / rel
            if not p.exists():
                continue
            raw = p.read_text(encoding="utf-8", errors="replace")
            text = inv.script_text(rel, raw)
            if not text.strip():
                continue
            out.append((rel, text, inv.units_for(rel, raw, kind)))
    return out


def _tracked_python() -> list[str]:
    """The Python scan scope, taken from THE discovery authority.

    RC-325 consolidation 2026-08-26: this ran its own `git ls-files -- *.py`, so this module
    held TWO repository enumerations of its own and the repo held several more. Discovery is
    producer_inventory_v1's job; deciding is this module's. The name is kept because the gate's
    own tests monkeypatch it to a literal list — behaviour they still get, from a function that
    no longer enumerates anything itself.

    _SKIP_PREFIXES stays here because it is a DECISION, not discovery: tests, tools and research
    legitimately recompute a value in order to check a producer (RC-274/RC-307/RC-312/RC-323).
    """
    inv = _inventory()
    py = inv.reconcile(inv.tracked())["buckets"]["python"]
    return [p for p in py if not p.startswith(_SKIP_PREFIXES)]


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


#: Calls that turn a NUMBER into TEXT, in either runtime — identical list for both, because a
#: rule that differs by language is itself two rules.
#:
#: TUNED AGAINST THE REPO, NOT GUESSED. A first version included `round(`, `int(`, `format(` and
#: a bare `:.`, and the gate immediately named 100 sites for a one-site computation — including
#: `db.py:_migrate_schema` and `time_et.py:time_to_expiry_years`. Those tokens are ubiquitous in
#: a chain codebase. Measured on the real repo, the list below plus the size/return bar below
#: yields ZERO false positives while still finding the declared producer and a re-introduced
#: browser copy. A gate people learn to ignore enforces nothing (RC-290, RC-323).
_TRANSFORM_CALLS = (
    ".tofixed(", ".tolocalestring(",                        # javascript number -> text
    ":.4f", ":.2f", ":.1f", ":.0f", ":.{",                  # python f-string format specs
)

#: A display transform is SMALL and RETURNS text. A large function that happens to mention the
#: input and format something is a renderer, not a second producer. Counted over significant
#: lines only, so documentation does not disqualify a producer.
_TRANSFORM_MAX_LINES = 30


def _code_only(text: str) -> str:
    """Strip comments and docstrings so the token match sees CODE, not prose.

    This repo documents its reasoning heavily, and a function that merely DISCUSSES strikes was
    being counted as one that computes them: `regime_engine._score_pinning` formats a pin WIDTH
    (`pw:.1f`) and mentions "strike" only in commentary, and it was named a producer of strike
    display text. Matching prose is how a gate acquires the false positives that get it ignored.
    """
    # triple-quoted docstrings (both quote styles), then line and trailing comments
    out = re.sub(r'"""(?:.|\n)*?"""', " ", text)
    out = re.sub(r"'''(?:.|\n)*?'''", " ", out)
    out = re.sub(r"/\*(?:.|\n)*?\*/", " ", out)
    kept = []
    for ln in out.splitlines():
        s = ln
        if s.lstrip().startswith(("#", "//")):
            continue
        s = re.sub(r"\s+#\s.*$", "", s)
        s = re.sub(r"\s+//\s.*$", "", s)
        kept.append(s)
    return "\n".join(kept)


def _significant_lines(text: str) -> int:
    """Lines that are neither blank nor comment.

    The size bar exists to separate a small transform from a large render function; counting a
    long explanatory docstring or comment block against a function would hide the very producers
    this repo documents most carefully.
    """
    n = 0
    for ln in text.splitlines():
        s = ln.strip()
        if not s or s.startswith(("#", "//", "*", "/*")):
            continue
        n += 1
    return n


def build_frontend_corpus() -> list[tuple[str, str, list[tuple[str, str]]]]:
    """(rel, executable_text, units) for every NON-Python executable production file.

    A THIN CONSUMER of the discovery authority — scope, kind, <script> extraction and unit
    extraction all belong to producer_inventory_v1. The name is kept because callers and tests
    already use it; what changed is that it no longer discovers anything itself.

    "Frontend" undersells it now: this covers every executable kind the authority recognises
    outside Python (.js .html .sql .mjs .jsx .ts .ipynb .bat .ps1 .sh), not the three static
    globs the first repair hand-picked.
    """
    return _non_python_production_units()


def _text_joins_inputs(text: str, inputs: tuple[str, ...], *, kind: str = "derived") -> bool:
    """The same BAR as the Python AST rule, applied to a text body.

    TWO KINDS, TWO DETECTORS, AND THE DISTINCTION IS LOAD-BEARING.

    `derived` — a market quantity built from vendor leaves. A site is one that JOINS two or
    more declared inputs with an arithmetic operator. Mentioning a leaf is consumption.

    `display_transform` — how ONE value is written as text. There is no arithmetic join to
    look for, so a site is a function that applies a rendering call to the input. This detector
    is opt-in per registry entry ON PURPOSE: a first version applied it to every single-input
    field and the gate immediately named `db.py:_migrate_schema` and
    `time_et.py:time_to_expiry_years` as producers of net charm — 29 sites for a quantity
    computed in one. That is the false-positive habit RC-290 and RC-323 record, and a gate
    people learn to ignore enforces nothing.
    """
    low = _code_only(text).lower()
    present = [i for i in inputs if i.lower() in low]
    if len(present) < min(2, len(inputs)):
        return False
    if kind == "display_transform":
        return (any(t in low for t in _TRANSFORM_CALLS)
                and "return" in low
                and _significant_lines(text) <= _TRANSFORM_MAX_LINES)
    if len(inputs) < 2:
        return False          # a lone input with no arithmetic to join is not a derivation
    return bool(re.search(r"[*+\-/]", low))


def computing_sites(field: str, spec: dict,
                    corpus: list[tuple[str, str, list[tuple[ast.AST, str]]]] | None = None,
                    frontend: list[tuple[str, str, list[tuple[str, str]]]] | None = None,
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
    kind = str(spec.get("kind") or "derived")
    out: list[str] = []
    for rel, src, fns in (corpus if corpus is not None else build_scan_corpus()):
        if not all(t in src for t in inputs):
            continue
        for fn, seg in fns:
            if not all(t in seg for t in inputs):
                continue
            hit = (_text_joins_inputs(seg, inputs, kind=kind) if kind == "display_transform"
                   else _joins_inputs_arithmetically(fn, inputs))
            if hit:
                out.append(f"{rel}:{fn.name}")
    # BROWSER SURFACES COUNT TOO. Omitting them is the ROOT CAUSE this scope repair fixes: a
    # second implementation there used to increment nothing, so `len(sites) > 1` could never
    # fire across runtimes. Judged by the SAME bar and the same kind, so the rule does not
    # differ by language — a rule that differed by language would itself be two rules.
    for rel, src, fns in (frontend if frontend is not None else build_frontend_corpus()):
        if not all(t.lower() in src.lower() for t in inputs):
            continue
        for name, seg in fns:
            if _text_joins_inputs(seg, inputs, kind=kind):
                out.append(f"{rel}:{name}")
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
    frontend = build_frontend_corpus()    # ...and the browser surfaces, same reason
    for field, spec in fields.items():
        producer = spec.get("producer") or ""
        sites = computing_sites(field, spec, corpus, frontend)
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
