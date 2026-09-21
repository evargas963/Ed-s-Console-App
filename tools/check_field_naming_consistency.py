#!/usr/bin/env python3
"""RC-292 — a registered field's canonical serialization name is the ONLY name it may be
written under on a declared payload surface.

WHY check_one_producer.py DOES NOT ALREADY COVER THIS. That gate proves a field is computed
in exactly one place; it says nothing about what KEY the computed value is written under.
GSF and GRC were each computed in exactly one place (math_levels.py:compute_gamma_support_
levels, PASS under that gate) and STILL shipped on the payload under two independent,
undocumented names — `kl_gsf` and `gsf` — with nothing keeping the two in sync until this
session's naming-consolidation fix (2026-09-21) merged them into one deliberate alias pair.
One producer, many silent names, is a real defect this repo already suffered from and had no
mechanical gate for.

WHAT THIS GATE CHECKS. A `computation_registry.json` field entry MAY opt in by declaring
`source_key` (the literal string used to pull the value FROM the producer's own result or
cache — e.g. the terrain-cache lookup key `"gsf"`) and `serialized_as` (every payload key
currently reviewed to carry that value — e.g. `["gsf", "kl_gsf"]`). For every field that
opts in, this gate AST-walks each declared `payload_surfaces` file, finds every assignment
whose right-hand side is a call passing that field's `source_key` as its one positional
string argument (the shape of `_g("gsf")` / `t.get("gsf")`), and flags any assignment TARGET
key — including every target of a chained assignment like `md["kl_gsf"] = md["gsf"] = ...`
— that is not already in that field's `serialized_as` list.

WHAT A PASS DOES AND DOES NOT MEAN. It covers only fields that opted in with BOTH schema
keys; a field registered without them is not checked by this gate at all (it is still
covered, separately, by check_one_producer's producer-count enforcement). It also only
catches drift that reuses the SAME source_key — a genuinely new access path to the same
underlying value under a different source_key would not be caught here; that is a
computation_registry.json registration gap, not a naming-consistency gap, and is
check_one_producer's NOT_PROVEN remainder to close.

    .venv/Scripts/python.exe tools/check_field_naming_consistency.py
    .venv/Scripts/python.exe tools/check_field_naming_consistency.py --measure
"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REGISTRY = REPO / "governance" / "computation_registry.json"


def load_registry() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def naming_checked_fields(reg: dict) -> dict[str, dict]:
    """Fields that opted into this gate by declaring BOTH source_key and serialized_as."""
    return {field: spec for field, spec in (reg.get("fields") or {}).items()
            if spec.get("source_key") and spec.get("serialized_as")}


def _target_key(node: ast.AST) -> str | None:
    """The literal string an assignment target names, e.g. `md["gsf"]` -> "gsf"."""
    if (isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)):
        return node.slice.value
    return None


def _call_source_key(node: ast.AST) -> str | None:
    """If `node` is a call with exactly one positional string-literal argument, return it.

    Matches `_g("gsf")` and an equally-shaped `t.get("gsf")` — any callee name, because the
    repo's own terrain-overlay convention wraps the cache lookup in a local lambda (`_g`)
    rather than calling `.get` at the write site (RC-122's `_terrain_kl_overlay`).
    """
    if isinstance(node, ast.Call) and len(node.args) == 1 and not node.keywords:
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
    return None


def naming_violations(reg: dict | None = None) -> list[str]:
    reg = reg if reg is not None else load_registry()
    checked = naming_checked_fields(reg)
    if not checked:
        return []
    by_source_key: dict[str, list[tuple[str, dict]]] = {}
    for field, spec in checked.items():
        by_source_key.setdefault(spec["source_key"], []).append((field, spec))

    surfaces = reg.get("payload_surfaces") or []
    out: list[str] = []
    for rel in surfaces:
        path = REPO / rel
        if not path.exists():
            out.append(f"{rel}:0  declared payload surface does not exist — naming gate "
                       f"FAILS CLOSED rather than reporting zero drift (SP-05 precedent).")
            continue
        src = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(src)
        except SyntaxError as exc:
            out.append(f"{rel}:0  could not parse — {exc}")
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            sk = _call_source_key(node.value)
            if sk is None or sk not in by_source_key:
                continue
            target_keys = [k for t in node.targets for k in (_target_key(t),) if k]
            if not target_keys:
                continue
            for field, spec in by_source_key[sk]:
                allowed = set(spec["serialized_as"])
                drift = sorted(k for k in target_keys if k not in allowed)
                if drift:
                    out.append(
                        f"{rel}:{node.lineno}  '{field}' (source_key={sk!r}) written to "
                        f"undocumented payload key(s) {drift} — not in its registered "
                        f"serialized_as {sorted(allowed)}. Either this is a real new "
                        f"serialization name (add it to serialized_as in "
                        f"governance/computation_registry.json after confirming it really "
                        f"is the same value) or it is fresh naming drift (RC-292) and should "
                        f"reuse an already-registered name instead.")
    return sorted(set(out))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--measure", action="store_true",
                    help="also print which fields are covered by this gate")
    args = ap.parse_args(argv)
    reg = load_registry()
    checked = naming_checked_fields(reg)
    if args.measure:
        print(f"naming-checked fields: {len(checked)}")
        for name in sorted(checked):
            print("   " + name)
    v = naming_violations(reg)
    if v:
        print("check_field_naming_consistency: FAIL — undocumented serialization name(s):")
        for line in v:
            print("  " + line)
        return 1
    if not args.quiet:
        print(f"check_field_naming_consistency: PASS over {len(checked)} "
              f"naming-checked field(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
