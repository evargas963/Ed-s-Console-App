"""OPTIONS FLOW FOUNDATION — disposition of the ENTIRE native Schwab options surface (2026-08-26).

OPERATOR REQUIREMENT: useful native Schwab options truth must not be discarded merely because
today's code does not consume it. Every native field must prove ONE of:

    RETAINED_RAW_AND_PROJECTED  raw payload persisted verbatim AND a canonical typed accessor reads it
    RETAINED_RAW                raw payload persisted verbatim, no consumer yet — future use preserved
    DELIBERATELY_EXCLUDED       not retained, with a concrete stated reason

    NATIVE_AVAILABLE_BUT_NOT_RETAINED is NOT an acceptable final state and this tool fails on it.

DESIGN — raw-native preservation plus canonical typed projections, deliberately NOT hundreds of
columns. A vendor payload is stored verbatim as JSON (one column), so no field can be lost by
omission; the handful of fields the product actually computes on get typed accessors layered over
that raw store. Adding a consumer later is a projection change, never a re-collection.

THE SURFACE IS ENUMERATED FROM EVIDENCE, never hand-listed:
  * REST /chains          -> schwab_field_inventory/schwab_canonical_fields.txt (the committed
                             canonical inventory built from live vendor responses)
  * LEVELONE_OPTIONS      -> reports/of_capability_probe/options_20260820T1354Z/frames/
                             LEVELONE_OPTIONS_001_decoded.json (a real captured full SUBS frame)
  * OPTIONS_BOOK          -> ...OPTIONS_BOOK_001_decoded.json (real captured frame, nested levels)

So the matrix cannot drift from the vendor surface without this tool noticing: it re-enumerates and
compares on every run, and the test drives it.

Usage:
    python tools/options_native_field_matrix_v1.py            # validate the committed matrix
    python tools/options_native_field_matrix_v1.py --emit     # rewrite it from current evidence
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

MATRIX_REL = "governance/options_native_field_matrix.json"
CANONICAL_INVENTORY = REPO / "schwab_field_inventory" / "schwab_canonical_fields.txt"
PROBE = REPO / "reports" / "of_capability_probe" / "options_20260820T1354Z" / "frames"

VALID_DISPOSITIONS = ("RETAINED_RAW_AND_PROJECTED", "RETAINED_RAW", "DELIBERATELY_EXCLUDED")
FORBIDDEN_DISPOSITION = "NATIVE_AVAILABLE_BUT_NOT_RETAINED"


def enumerate_rest_chain() -> tuple[list[str], list[str]]:
    """(envelope leaves, per-contract leaves) from the committed canonical inventory."""
    lines = [l.strip() for l in CANONICAL_INVENTORY.read_text(encoding="utf-8").splitlines() if l.strip()]
    chains = [l for l in lines if l.startswith("chains.")]
    envelope = sorted({l.split(".", 1)[1] for l in chains if l.count(".") == 1})
    contract: set[str] = set()
    for c in chains:
        parts = c.split(".")
        if len(parts) > 2 and parts[1] in ("callExpDateMap", "putExpDateMap"):
            leaf = ".".join(parts[2:]).lstrip("*").lstrip(".")
            if leaf:
                contract.add(leaf)
    return envelope, sorted(contract)


def _decoded(name: str) -> dict:
    return json.loads((PROBE / name).read_text(encoding="utf-8"))


def enumerate_levelone_options() -> list[str]:
    """Field names from a real captured full SUBS frame (delta frames carry only changed fields)."""
    return sorted(_decoded("LEVELONE_OPTIONS_001_decoded.json")["content"][0].keys())


def enumerate_options_book() -> dict[str, list[str]]:
    """The three nested levels: frame, per-price-level, per-market-maker."""
    c = _decoded("OPTIONS_BOOK_001_decoded.json")["content"][0]
    out = {"frame": sorted(c.keys()), "price_level": [], "market_maker": []}
    for side in ("BIDS", "ASKS"):
        lv = (c.get(side) or [None])[0]
        if isinstance(lv, dict):
            out["price_level"] = sorted(set(out["price_level"]) | set(lv.keys()))
            mm = (lv.get(side) or [None])[0]
            if isinstance(mm, dict):
                out["market_maker"] = sorted(set(out["market_maker"]) | set(mm.keys()))
    return out


def enumerate_surface() -> dict[str, list[str]]:
    env, contract = enumerate_rest_chain()
    book = enumerate_options_book()
    return {
        "rest_chain_envelope": env,
        "rest_chain_contract": contract,
        "levelone_options": enumerate_levelone_options(),
        "options_book_frame": book["frame"],
        "options_book_price_level": book["price_level"],
        "options_book_market_maker": book["market_maker"],
    }


def validate(matrix: dict) -> list[str]:
    """Problems with the committed matrix, empty when it is complete and honest."""
    problems: list[str] = []
    live = enumerate_surface()
    recorded = matrix.get("surfaces", {})

    for surface, fields in live.items():
        rec = recorded.get(surface)
        if rec is None:
            problems.append(f"{surface}: surface missing from the matrix entirely")
            continue
        missing = [f for f in fields if f not in rec]
        extra = [f for f in rec if f not in fields]
        if missing:
            problems.append(
                f"{surface}: {len(missing)} native field(s) have NO disposition — "
                f"the vendor provides them and the matrix is silent: {missing[:12]}")
        if extra:
            problems.append(
                f"{surface}: {len(extra)} matrix entr(ies) name fields the evidence does not show "
                f"(stale or invented): {extra[:12]}")
        for name, entry in rec.items():
            d = (entry or {}).get("disposition")
            if d == FORBIDDEN_DISPOSITION:
                problems.append(
                    f"{surface}.{name}: disposition is {FORBIDDEN_DISPOSITION}, which the operator "
                    f"requirement forbids as a final state — retain it raw or exclude it with a reason")
            elif d not in VALID_DISPOSITIONS:
                problems.append(f"{surface}.{name}: unknown disposition {d!r}")
            if d == "DELIBERATELY_EXCLUDED" and not str((entry or {}).get("reason", "")).strip():
                problems.append(
                    f"{surface}.{name}: DELIBERATELY_EXCLUDED without a concrete reason — "
                    f"exclusion must be argued, not asserted")
            if d in ("RETAINED_RAW", "RETAINED_RAW_AND_PROJECTED") and not str(
                    (entry or {}).get("retained_in", "")).strip():
                problems.append(f"{surface}.{name}: claims retention but names no store")
    return problems


def surface_counts() -> dict[str, int]:
    return {k: len(v) for k, v in enumerate_surface().items()}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--emit", action="store_true",
                    help="print a skeleton matrix from current evidence (dispositions left blank)")
    args = ap.parse_args(argv)

    if args.emit:
        skeleton = {
            "_generated_by": "tools/options_native_field_matrix_v1.py --emit",
            "_dispositions": list(VALID_DISPOSITIONS),
            "_forbidden": FORBIDDEN_DISPOSITION,
            "surfaces": {s: {f: {"disposition": "", "retained_in": "", "projection": "",
                                 "semantics": "NATIVE", "reason": ""} for f in fields}
                         for s, fields in enumerate_surface().items()},
        }
        print(json.dumps(skeleton, indent=1, sort_keys=True))
        return 0

    path = REPO / MATRIX_REL
    if not path.is_file():
        print(f"[FAIL] {MATRIX_REL} is missing — the native surface has no recorded disposition")
        return 1
    matrix = json.loads(path.read_text(encoding="utf-8"))
    problems = validate(matrix)
    counts = surface_counts()
    print(f"native surface enumerated from evidence: {sum(counts.values())} field names")
    for k, v in counts.items():
        print(f"  {k}: {v}")
    if problems:
        print(f"\n[FAIL] {len(problems)} disposition problem(s):")
        for p in problems:
            print(f"  * {p}")
        return 1
    print("\n[PASS] every native field on every surface carries a disposition, none forbidden")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
