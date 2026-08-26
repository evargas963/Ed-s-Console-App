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


def _decoded_frames(prefix: str) -> list[dict]:
    """EVERY committed decoded frame for a service, not just the first.

    Corrected 2026-08-26 after review: the census used to read one frame's content[0] (and, for the
    book, its first price level and first nested row). That made "the matrix covers the entire native
    stream surface" untrue as a METHOD even where it happened to be true for this capture — a field
    appearing only in a later frame, a second content entry, or an ask-side level would never be
    censused, so a newly observed vendor field could not be caught mechanically. Measured at the time
    of the fix: first-frame-only would have missed ASKS / ASK_PRICE / NUM_ASKS at price level and
    ASK_VOLUME at the maker level. Union over all frames and all entries now.
    """
    out = []
    for p in sorted(PROBE.glob(f"{prefix}_*_decoded.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (ValueError, OSError):
            continue
    if not out:
        raise AssertionError(f"no committed {prefix} frames under {PROBE} — census evidence missing")
    return out


def enumerate_levelone_options() -> list[str]:
    """UNION of field names across every committed frame and every content entry.

    Delta frames carry only changed fields, so a union is also the only way to see the full surface
    if a full SUBS frame were ever absent from the capture.
    """
    names: set[str] = set()
    for frame in _decoded_frames("LEVELONE_OPTIONS"):
        for entry in frame.get("content") or []:
            if isinstance(entry, dict):
                names |= set(entry.keys())
    return sorted(names)


def enumerate_options_book() -> dict[str, list[str]]:
    """UNION across every committed frame / content entry / price level / nested participant row."""
    frame_keys: set[str] = set()
    level_keys: set[str] = set()
    maker_keys: set[str] = set()
    for frame in _decoded_frames("OPTIONS_BOOK"):
        for entry in frame.get("content") or []:
            if not isinstance(entry, dict):
                continue
            frame_keys |= set(entry.keys())
            for side in ("BIDS", "ASKS"):
                for level in entry.get(side) or []:
                    if not isinstance(level, dict):
                        continue
                    level_keys |= set(level.keys())
                    for maker in level.get(side) or []:
                        if isinstance(maker, dict):
                            maker_keys |= set(maker.keys())
    return {"frame": sorted(frame_keys), "price_level": sorted(level_keys),
            "market_maker": sorted(maker_keys)}


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
            # TEMPORAL CONTRACT (added 2026-08-26 after review): "retained" without a cadence lets a
            # once-a-day copy stand in for a field production receives on every fetch. MEASURED: in
            # 24h production took 4374 chain fetches carrying an envelope and persisted 3 envelope
            # rows. Every retention claim must therefore state its grain, and say so where the grain
            # is coarser than the receive rate.
            if d.startswith("RETAINED_RAW"):
                grain = str((entry or {}).get("temporal_grain", "")).strip()
                if not grain:
                    problems.append(
                        f"{surface}.{name}: RETAINED_RAW without temporal_grain — a retention claim "
                        f"must state HOW OFTEN it is kept versus how often it is received")
                elif "RECEIVED_MORE_OFTEN_THAN_RETAINED" in grain and not str(
                        (entry or {}).get("retention_gap", "")).strip():
                    problems.append(
                        f"{surface}.{name}: grain admits under-retention but names no retention_gap")
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


# ── curated dispositions, kept HERE so the matrix is regenerable by command ────────────────────
_GRAIN_CONTRACT = ("PER_FETCH (snapshots.option_chain_json, selected expiry, every poll) "
                   "+ ONCE_PER_DAY (wide book)")
_GRAIN_ENV = ("ONCE_PER_TICKER_PER_DAY - RECEIVED_MORE_OFTEN_THAN_RETAINED. "
              "Written only by the morning wide capture.")
_GAP_ENV = (
    "MEASURED 2026-08-26 on the production DB: 4374 snapshots carried a chain envelope in 24h while "
    "3 envelope rows were written that day. These are RESPONSE-SPECIFIC values that can change on "
    "every fetch (underlyingPrice, volatility, the whole underlying quote block, and potentially "
    "interestRate/dividendYield), so one morning copy is NOT a faithful record of what production "
    "received. CLOSING IT means writing the envelope per fetch beside snapshots.option_chain_json - "
    "a storage-cost decision on a hot table, deliberately NOT taken unilaterally.")
_RAW_CONTRACT = ("snapshots.option_chain_json (selected expiry, EVERY poll - contract dict stored "
                 "whole); option_chain_morning_full.chain_json (wide book, DTE<=37, once daily)")
_RAW_ENVELOPE = "option_chain_morning_full.chain_envelope_json (NATIVE scalars, written by production)"
_RAW_UNDER = ("option_chain_morning_full.chain_envelope_json -> `underlying` object retained WHOLE "
              "and unflattened; each leaf is censused individually because raw retention justifies "
              "a disposition, never an omission")
_READY = ("writer calibration/options_stream_frames.persist_frame (+ projection "
          "project_book_market_makers), tested against REAL captured frames; evidence today: "
          "reports/of_capability_probe/options_20260820T1354Z/frames/*_raw.json")
_BLOCKED = ("production subscribes NEITHER LEVELONE_OPTIONS nor OPTIONS_BOOK - order_flow_streaming "
            "subscribes LEVELONE_EQUITIES/NASDAQ_BOOK/NYSE_BOOK only, for ONE symbol. Nothing calls "
            "the writer, so NOTHING is retained in production today.")
_PROOF_MAPS = (
    "PROVEN by keyset comparison re-derived 2026-08-26 (n_native=56, n_persisted=58): normalised "
    "NATIVE per-contract leaves MINUS persisted contract keyset = 0 missing. The persisted set "
    "additionally holds breakEven and ssid - vendor fields NEWER than the committed inventory, "
    "retained because the contract dict is stored whole. The maps ARE the contracts; copying them "
    "here duplicates the payload's bulk and adds no field. Re-derivable: "
    "tests/test_options_contract_keyset_no_loss_v1.py")
_PROJ = {
    "strikePrice": "math_exposure_core.compute_exposures_by_strike; math_levels._contract_inputs",
    "openInterest": "math_exposure_core (require_oi); math_levels._contract_inputs",
    "multiplier": "math_exposure_core; math_levels._contract_inputs",
    "volatility": "math_exposure_core.schwab_iv_to_sigma (the ONE IV conversion authority)",
    "gamma": "math_exposure_core.compute_exposures_by_strike (vendor gamma, plausibility-gated)",
    "delta": "math_exposure_core.compute_exposures_by_strike",
    "expirationDate": "time_et.time_to_expiry_years via _contract_inputs",
    "putCall": "math_exposure_core side split",
    "totalVolume": "math_exposure_core order-flow accumulation",
    "daysToExpiration": "terrain_engine._dte_of; 0DTE gamma share",
    "bid": "server chain window / quote surface", "ask": "server chain window / quote surface",
}
_CANON = {
    "BOOK_TIME": "Market Snapshot Time", "NUM_BIDS": "Market Maker Count (bid side)",
    "NUM_ASKS": "Market Maker Count (ask side)", "TOTAL_VOLUME": "Aggregate size at price level",
    "EXCHANGE": "Market Maker ID (vendor documented name; observed values are venue codes)",
    "BID_VOLUME": "Per-market-maker Size (bid)", "ASK_VOLUME": "Per-market-maker Size (ask)",
    "SEQUENCE": ("Per-market-maker Quote Time (RAW decoder name SEQUENCE; vendor doc names it a "
                 "quote time and captured values lag BOOK_TIME by 0-604ms rather than counting)"),
    "BIDS": "Bid side price levels, each holding the nested participant array",
    "ASKS": "Ask side price levels, each holding the nested participant array",
    "BID_PRICE": "Price level (bid)", "ASK_PRICE": "Price level (ask)",
    "key": "Option symbol (frame key)",
}
_BOOK_PROJ = "calibration.options_stream_frames.project_book_market_makers"


def _entry(disposition, store="", proj="", reason="", blocked="", canon="", grain="", gap=""):
    e = {"disposition": disposition, "retained_in": store, "projection": proj,
         "semantics": "NATIVE", "reason": reason, "blocked_on": blocked,
         "temporal_grain": grain, "retention_gap": gap}
    if canon:
        e["canonical_name"] = canon
    return e


def build_matrix() -> dict:
    """The committed matrix, rebuilt from the evidence-backed enumeration plus curated dispositions."""
    surf = enumerate_surface()
    m = {
        "_generated_by": "python tools/options_native_field_matrix_v1.py --emit-curated",
        "_dispositions": list(VALID_DISPOSITIONS),
        "_forbidden": FORBIDDEN_DISPOSITION,
        "_retained_raw_means": (
            "production RECEIVES AND PERSISTS the field TODAY, at the cadence stated in "
            "temporal_grain. Storage code that exists but is never called is "
            "RETENTION_PATH_READY_NOT_WIRED."),
        "_census_method": (
            "UNION over EVERY committed capture frame, every content entry, every price level and "
            "every nested participant row - not the first of each. Corrected 2026-08-26: "
            "first-frame-only would have missed ASKS/ASK_PRICE/NUM_ASKS at price level and "
            "ASK_VOLUME at maker level, and could never mechanically catch a new vendor field."),
        "_census_reconciliation_171_vs_148": {
            "earlier_investigation": 171, "first_matrix": 148, "difference": 23,
            "explanation": (
                "The 23 chains.underlying.* leaves matched NEITHER the depth-1 envelope filter NOR "
                "the call/putExpDateMap filter, so the first enumerator dropped them silently. "
                "Retaining `underlying` as one JSON object does NOT remove its leaves from the "
                "census. 148 + 23 = 171. The enumerator now RAISES if any chains.* leaf matches no "
                "bucket."),
            "every_member_of_the_difference": sorted(surf["rest_chain_underlying"])},
        "_principle": (
            "Raw-native preservation plus canonical typed projections. Vendor payloads are stored "
            "whole so no field is lost by omission in today's parser - demonstrated by breakEven "
            "and ssid, vendor fields postdating the committed inventory, retained anyway. Consumers "
            "are READERS over the raw store. Nothing infers dealer ownership; nothing feeds Decide."),
        "surfaces": {},
    }
    S = m["surfaces"]
    S["rest_chain_envelope"] = {
        f: (_entry("DELIBERATELY_EXCLUDED_WITH_PROOF", reason=_PROOF_MAPS)
            if f in ("callExpDateMap", "putExpDateMap")
            else _entry("RETAINED_RAW", _RAW_ENVELOPE, grain=_GRAIN_ENV, gap=_GAP_ENV))
        for f in surf["rest_chain_envelope"]}
    S["rest_chain_underlying"] = {
        f: _entry("RETAINED_RAW", _RAW_UNDER, grain=_GRAIN_ENV, gap=_GAP_ENV)
        for f in surf["rest_chain_underlying"]}
    S["rest_chain_contract"] = {
        f: _entry("RETAINED_RAW_AND_PROJECTED" if _PROJ.get(f) else "RETAINED_RAW",
                  _RAW_CONTRACT, _PROJ.get(f, ""), grain=_GRAIN_CONTRACT)
        for f in surf["rest_chain_contract"]}
    S["levelone_options"] = {
        f: _entry("RETENTION_PATH_READY_NOT_WIRED", _READY, blocked=_BLOCKED)
        for f in surf["levelone_options"]}
    for s in ("options_book_frame", "options_book_price_level", "options_book_market_maker"):
        S[s] = {f: _entry("RETENTION_PATH_READY_NOT_WIRED", _READY, _BOOK_PROJ,
                          blocked=_BLOCKED, canon=_CANON.get(f, ""))
                for f in surf[s]}
    return m


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--emit", action="store_true",
                    help="print a skeleton matrix from current evidence (dispositions left blank)")
    ap.add_argument("--emit-curated", action="store_true",
                    help="WRITE the committed matrix from evidence + curated dispositions")
    args = ap.parse_args(argv)

    if args.emit_curated:
        matrix = build_matrix()
        (REPO / MATRIX_REL).write_text(
            json.dumps(matrix, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        n = sum(len(v) for v in matrix["surfaces"].values())
        print(f"wrote {MATRIX_REL}: {n} fields across {len(matrix['surfaces'])} surfaces")
        return 0

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
