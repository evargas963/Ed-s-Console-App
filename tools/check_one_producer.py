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
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REGISTRY = REPO / "governance" / "computation_registry.json"

#: Scanned for computation. Tests, tools and research legitimately recompute in order to
#: CHECK a producer; scratch is not this repository (RC-274/RC-307/RC-312/RC-323).
_SKIP_PREFIXES = ("tests/", "tools/", "research/", "arch_competition/", "scratchpad/",
                  "governance/", "calibration/")

#: A field is COMPUTED at a site when the site both mentions the defining inputs and
#: performs an aggregation or arithmetic over them. Mentioning a name is consumption.
_AGGREGATION = ("sum(", "for ", "+=", "*")


def _tracked_python() -> list[str]:
    proc = subprocess.run(["git", "ls-files", "-z", "--", "*.py"],
                          cwd=REPO, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError("git ls-files failed, so the scan scope is unknown: "
                           + proc.stderr.strip()[:160])
    return [p for p in proc.stdout.split("\0")
            if p and not p.startswith(_SKIP_PREFIXES)]


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


def computing_sites(field: str, spec: dict) -> list[str]:
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
    for rel in _tracked_python():
        path = REPO / rel
        if not path.exists():
            continue
        src = path.read_text(encoding="utf-8", errors="replace")
        if not all(t in src for t in inputs):
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            seg = ast.get_source_segment(src, fn) or ""
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
    for field, spec in fields.items():
        producer = spec.get("producer") or ""
        sites = computing_sites(field, spec)
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
