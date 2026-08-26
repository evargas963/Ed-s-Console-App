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

#: DISPOSITIONS — deliberately separate "we keep this today" from "we could keep this".
#: Corrected 2026-08-26 after review: the first version let LEVELONE_OPTIONS and OPTIONS_BOOK be
#: called RETAINED_RAW because a writer module EXISTS, while production subscribes to neither
#: service. That made "zero unretained" reachable with an INERT WRITER, which is exactly the kind of
#: paper closure this matrix is supposed to prevent. Storage capability is now its own state.
VALID_DISPOSITIONS = (
    "RETAINED_RAW_AND_PROJECTED",     # production receives + persists it today AND a typed reader consumes it
    "RETAINED_RAW",                   # production really receives + persists it today; no consumer yet
    "RETENTION_PATH_READY_NOT_WIRED", # writer+projection exist and are tested, but production
                                      # subscribes/calls NOTHING -> the field is NOT retained today
    "CAPTURE_ONLY",                   # exists solely as committed probe evidence
    "DELIBERATELY_EXCLUDED_WITH_PROOF",  # not retained, with a concrete reason AND cited proof of no loss
    "UNAVAILABLE",                    # vendor does not actually deliver it to us
)
#: States that do NOT count as retention. RETAINED_RAW means production RECEIVES AND PERSISTS the
#: field today — never merely that storage code exists for it.
NOT_RETAINED_STATES = ("RETENTION_PATH_READY_NOT_WIRED", "CAPTURE_ONLY", "UNAVAILABLE")
FORBIDDEN_DISPOSITION = "NATIVE_AVAILABLE_BUT_NOT_RETAINED"


def enumerate_rest_chain() -> tuple[list[str], list[str], list[str]]:
    """(envelope, underlying, per-contract) leaves from the committed canonical inventory.

    EVERY chains.* leaf must land in exactly one bucket. Corrected 2026-08-26 after review: the
    first version bucketed only depth-1 keys and keys under call/putExpDateMap, so the 23
    `chains.underlying.*` leaves matched NEITHER filter and vanished from the census entirely —
    the census reported 148 where the investigation had found 171. Being retained inside a raw
    nested object justifies a RETAINED disposition; it never justifies being absent from the matrix.
    A completeness assertion below makes that class of silent drop impossible to reintroduce.
    """
    lines = [l.strip() for l in CANONICAL_INVENTORY.read_text(encoding="utf-8").splitlines() if l.strip()]
    chains = [l for l in lines if l.startswith("chains.")]
    envelope, underlying, contract = set(), set(), set()
    unbucketed = []
    for c in chains:
        parts = c.split(".")
        if len(parts) == 2:
            envelope.add(parts[1])
        elif parts[1] == "underlying":
            underlying.add(".".join(parts[2:]))
        elif parts[1] in ("callExpDateMap", "putExpDateMap"):
            leaf = ".".join(parts[2:]).lstrip("*").lstrip(".")
            # the bare "*" is the contract OBJECT placeholder (the expiry->strike map node), not a
            # vendor field; it is the single accounted-for non-leaf in the inventory.
            if leaf:
                contract.add(leaf)
        else:
            unbucketed.append(c)
    if unbucketed:
        raise AssertionError(
            f"{len(unbucketed)} chains.* leaf/leaves matched no bucket and would have been dropped "
            f"from the census: {unbucketed[:10]}")
    return sorted(envelope), sorted(underlying), sorted(contract)


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
    env, underlying, contract = enumerate_rest_chain()
    book = enumerate_options_book()
    return {
        "rest_chain_envelope": env,
        "rest_chain_underlying": underlying,
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
            if d == "DELIBERATELY_EXCLUDED_WITH_PROOF" and not str((entry or {}).get("reason", "")).strip():
                problems.append(
                    f"{surface}.{name}: excluded without a concrete reason AND cited proof — "
                    f"exclusion must be argued and demonstrated, not asserted")
            if d.startswith("RETAINED_RAW") and not str((entry or {}).get("retained_in", "")).strip():
                problems.append(
                    f"{surface}.{name}: claims RETAINED_RAW but names no store. RETAINED_RAW means "
                    f"production RECEIVES AND PERSISTS it today, not that storage code exists")
            # A not-yet-wired path must say what is missing, so nobody reads it as retention.
            if d in NOT_RETAINED_STATES and not str((entry or {}).get("blocked_on", "")).strip():
                problems.append(
                    f"{surface}.{name}: {d} must state blocked_on (what is not wired) — otherwise an "
                    f"inert writer reads as retention")
    return problems


def retention_reality(matrix: dict) -> dict[str, int]:
    """Honest tally: what production actually keeps today vs what is merely ready."""
    tally: dict[str, int] = {}
    for fields in matrix.get("surfaces", {}).values():
        for entry in fields.values():
            d = (entry or {}).get("disposition", "?")
            tally[d] = tally.get(d, 0) + 1
    return tally


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
