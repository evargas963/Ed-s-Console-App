"""ONE FAUCET, verified against the RUNNING SERVER (RC-262).

Every other lock in this repository is a static assertion about source text.
`check_single_spot_authority` bans the string ``chain_underlying_spot(`` in two
files and calls spot settled — it has never compared two values. On 2026-08-06
that gate was green while fourteen endpoints returned spot prices spanning
769.79 to 775.43, and `book_imbalance_5` came back -0.328 from one endpoint and
+0.0380 from another: opposite signs on a directional signal.

A static check cannot see that. Only asking the server twice can.

WHAT THIS ENFORCES
    A field polled once and read everywhere (RH-F1). If two endpoints both
    publish a field, they are two faucets, and two faucets that disagree put
    contradictory numbers on two screens with nothing to detect it.

WHAT IT DELIBERATELY DOES NOT FLAG
    * Multi-subject collections and time series. A value pulled from the first
      row of a radar or a history is a different subject, not a competing
      faucet, and comparing them would manufacture failures.
    * Monotonic counters, generation ids and timestamps. Two samples taken
      milliseconds apart SHOULD differ; flagging them trains people to ignore
      the check.
    * Fields only one endpoint publishes. One faucet is the goal, not a defect.

The exclusions are data, not prose, so they can be audited and argued with.

Classification: DIAGNOSTIC_TOOL — non-authoritative.
Needs a running server. Exit 2 when unreachable. Must not be cited as PASS,
ENFORCED, or merge-blocking. rehab_daily_scan may invoke it recommend-only
(`--skip-if-down`). Not a commit/CI lock: a live multi-endpoint compare cannot
be satisfied in offline CI and must not be wrapped in `|| true`.

Run:  python tools/check_one_faucet_live.py [--base URL] [--ticker SYM] [--json]
Exit: 0 all shared fields agree · 1 a disagreement · 2 server unreachable
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from typing import Any

DEFAULT_BASE = "http://127.0.0.1:8000"
DEFAULT_TICKER = "SPY"
TIMEOUT_SEC = 25

#: Scoped to ONE subject at the CURRENT instant. Only these are comparable.
SINGLE_SUBJECT: tuple[str, ...] = (
    "/api/spot",
    "/api/fast-quote",
    "/api/state",
    "/api/live/state",
    "/api/live/plane",
    "/api/terrain",
    "/api/terrain/strikes",
    "/api/levels",
    "/api/forces",
    "/api/liquidity-snapshot",
    "/api/analytics/state",
    "/api/analytics/light",
    "/api/desk/structure",
    "/api/exposure/flow",
    "/api/exposure/book",
    "/api/debug/charm",
    "/api/diagnostics/l1",
    "/api/level_crosses",
    "/api/price-levels",
)

#: Excluded WITH A REASON, so the exclusion is reviewable rather than silent.
EXCLUDED: dict[str, str] = {
    "/api/terrain/radar": "collection of different subjects",
    "/api/desk/radar": "collection of different subjects",
    "/api/exposure/history": "historical series, not the current instant",
    "/api/bars1m": "time series",
    "/api/expiries": "list of expiries, not a subject snapshot",
    "/api/stream": "server-sent events, never terminates",
    "/api/analytics/light/stream": "server-sent events, never terminates",
}

#: Structural or meta fields — not domain measurements.
META: frozenset[str] = frozenset({
    "ok", "status", "error", "reason", "message", "detail", "schema_version",
    "as_of", "as_of_utc", "ts", "timestamp", "generated_at", "source", "note",
    "ticker", "subject", "symbol", "count", "n", "rows", "items", "data",
    "available", "empty_reason", "version", "build", "mode", "kind", "label",
    "method", "basis", "provenance", "confidence", "explain", "formula",
})

#: Suffixes/names that legitimately differ between two samples.
VOLATILE_SUFFIXES: tuple[str, ...] = (
    "_ts", "_ts_utc", "_at", "_at_utc", "_seq", "_total", "_count",
    "_generation_id", "_age_sec", "_elapsed_ms", "_duration_sec", "_ms",
    "_timestamp", "_timestamp_utc", "_utc",
)
VOLATILE_EXACT: frozenset[str] = frozenset({
    "now", "uptime", "latency", "elapsed", "age_sec",
})


def is_volatile(name: str) -> bool:
    """A field whose value is expected to move between two samples."""
    return name in VOLATILE_EXACT or name.endswith(VOLATILE_SUFFIXES)


#: Keys whose value NAMES the subject of the row it sits in. A list of such rows is
#: not "many subjects" — it is a keyed map written as a list, and each id is one
#: comparable subject. Phase 2A: /api/levels ships `levels: [{"id","price"}, ...]`,
#: which the list rule below made invisible to this check — the exact payload shape
#: the operator asked it to compare.
ROW_ID_KEYS: tuple[str, ...] = ("id", "level_id", "tag", "name")
#: Keys carrying that row's number.
ROW_VALUE_KEYS: tuple[str, ...] = ("price", "value", "level", "px")


def keyed_row_leaves(obj: Any, out: dict[str, Any] | None = None,
                     depth: int = 0) -> dict[str, Any]:
    """Numeric values from id-keyed rows inside lists, keyed `<id>` (lowercased).

    Deliberately narrow: only a row that NAMES itself is descended into. A radar row
    or a history frame has no self-naming id key and is still skipped, so this does
    not reintroduce the "row zero of two collections" comparison the list rule exists
    to prevent.
    """
    if out is None:
        out = {}
    if depth > 6:
        return out
    if isinstance(obj, dict):
        for value in obj.values():
            if isinstance(value, (dict, list)):
                keyed_row_leaves(value, out, depth + 1)
        return out
    if isinstance(obj, list):
        for item in obj:
            if not isinstance(item, dict):
                continue
            rid = next((item[k] for k in ROW_ID_KEYS
                        if isinstance(item.get(k), str)), None)
            val = next((item[k] for k in ROW_VALUE_KEYS
                        if isinstance(item.get(k), (int, float))
                        and not isinstance(item.get(k), bool)), None)
            if rid is not None and val is not None:
                out.setdefault(f"level:{rid.strip().lower()}", val)
            keyed_row_leaves(item, out, depth + 1)
    return out


def numeric_leaves(obj: Any, out: dict[str, Any] | None = None,
                   depth: int = 0) -> dict[str, Any]:
    """Scalar numeric leaves keyed by bare field name, plus id-keyed level rows.

    Bare lists are NOT descended into for anonymous rows: a list element is one row
    among many and comparing row zero of two different collections is not a faucet
    comparison. Rows that NAME themselves are the exception — see keyed_row_leaves.
    """
    if out is None:
        out = {}
    if depth > 5:
        return out
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, dict):
                numeric_leaves(value, out, depth + 1)
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                out.setdefault(key.lower(), value)
    if depth == 0:
        keyed_row_leaves(obj, out, 0)
    return out


#: Extra query needed to put an endpoint in the SAME semantic scope as the others.
#: /api/liquidity-snapshot defaults to the PREMARKET checkpoint, which is a different
#: cutoff and therefore legitimately different numbers; asking it for `live` is what
#: makes its level rows comparable with /api/levels at all (Phase 2A).
ENDPOINT_PARAMS: dict[str, str] = {
    "/api/liquidity-snapshot": "&snapshot=live",
}


def fetch(base: str, endpoint: str, ticker: str) -> dict[str, Any] | None:
    url = f"{base}{endpoint}?ticker={ticker}{ENDPOINT_PARAMS.get(endpoint, '')}"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SEC) as response:
            return json.loads(response.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None


def census(base: str, ticker: str) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Poll every endpoint CONCURRENTLY, so the sample is one instant.

    RC-269: polling nineteen endpoints in sequence takes about fifteen seconds.
    During active trading that window IS the apparent disagreement -- the first
    endpoint is asked at t=0 and the last at t=15, so every field derived from
    spot differs for no reason but the clock. The count swung 6, 12, 13, 14 for
    an unchanged repository, and no post-hoc correction repairs a sampling
    method that spans the thing it is trying to hold still.

    Concurrency collapses the window from the SUM of the latencies to roughly
    the SLOWEST one. What remains after that is structural disagreement.
    """
    from concurrent.futures import ThreadPoolExecutor

    produced: dict[str, dict[str, Any]] = defaultdict(dict)
    unreachable: list[str] = []
    with ThreadPoolExecutor(max_workers=len(SINGLE_SUBJECT)) as pool:
        results = list(zip(SINGLE_SUBJECT, pool.map(
            lambda e: fetch(base, e, ticker), SINGLE_SUBJECT)))
    for endpoint, payload in results:
        if payload is None:
            unreachable.append(endpoint)
            continue
        for name, value in numeric_leaves(payload).items():
            if name in META or name.startswith("_") or is_volatile(name):
                continue
            produced[name][endpoint] = value
    return produced, unreachable


def confirm_disagreements(base: str, ticker: str,
                          multi: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Cross-endpoint disagreement that EXCEEDS the field's own drift.

    RC-269: a single pass reported 14 disagreements and then 6 seconds later,
    because polling nineteen endpoints takes seconds and the price moves
    between the first call and the last -- so every field derived from spot
    "disagrees" purely from being sampled at different instants. A count that
    swings 6-14 for the same repository cannot carry an exact-equality ratchet,
    and it is noisiest during market hours, which is when it matters.

    So each field is measured against ITSELF first. A second full pass gives
    every field a self-drift: how far it moved with no faucet disagreement
    involved. Only spread LARGER than that drift is reported, and the field
    must still disagree on the second pass. A structural disagreement survives
    both; a moving price cancels.

    Fails toward REPORTING: with no drift measurement available, any spread is
    reported rather than assumed benign.
    """
    second, _ = census(base, ticker)
    confirmed: dict[str, dict[str, Any]] = {}
    for field, faucets in multi.items():
        values = list(faucets.values())
        if len(set(values)) < 2:
            continue
        spread = max(values) - min(values)

        other = second.get(field, {})
        drift = 0.0
        for endpoint, value in faucets.items():
            if endpoint in other:
                drift = max(drift, abs(other[endpoint] - value))

        if drift and spread <= drift:
            continue                        # moved, did not disagree
        if other and len(set(other.values())) < 2:
            continue                        # agreed on the confirming pass
        confirmed[field] = faucets
    return confirmed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--ticker", default=DEFAULT_TICKER)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--skip-if-down", action="store_true",
                        dest="skip_if_down",
                        help="exit 0 instead of 2 when the server is not "
                             "running (for commit hooks; no server means no "
                             "measurement, not a pass)")
    # RC-270: there is deliberately NO --max, --tolerance or ceiling. One was
    # added twice this session -- 13, then 6 -- and both were wrong, because a
    # count that measures 5, 12, 12, 13 across consecutive runs cannot carry a
    # threshold at all. More importantly the operator never asked for one. Any
    # disagreement fails. If that blocks a commit, the answer is to fix the
    # field, not to widen the gate.
    args = parser.parse_args(argv)

    if fetch(args.base, "/api/spot", args.ticker) is None:
        sys.stderr.write(
            f"one-faucet: server unreachable at {args.base}. This check needs a "
            "running server -- it verifies behaviour, not source text.\n")
        # A stopped server is NOT a passing repository, so an interactive run
        # still reports 2. But wired as a commit hook it must not block: no
        # server means no measurement, and refusing every commit made outside
        # market hours would get the hook removed. --skip-if-down states that
        # choice out loud at the call site rather than hiding it here.
        if args.skip_if_down:
            sys.stderr.write("one-faucet: --skip-if-down, not blocking\n")
            return 0
        return 2

    produced, unreachable = census(args.base, args.ticker)
    multi = {f: m for f, m in produced.items() if len(m) > 1}
    disagreeing = confirm_disagreements(args.base, args.ticker, multi)

    findings = []
    for field, faucets in sorted(disagreeing.items(), key=lambda kv: -len(kv[1])):
        values = list(faucets.values())
        spread = max(values) - min(values)
        base_value = min((abs(v) for v in values if v), default=0) or 1
        findings.append({
            "field": field,
            "faucets": len(faucets),
            "spread": spread,
            "spread_pct": 100.0 * spread / base_value,
            "values": {ep: v for ep, v in sorted(faucets.items(), key=lambda kv: kv[1])},
        })

    if args.as_json:
        print(json.dumps({
            "endpoints_compared": len(SINGLE_SUBJECT) - len(unreachable),
            "unreachable": unreachable,
            "fields_seen": len(produced),
            "multi_faucet": len(multi),
            "disagreeing": len(disagreeing),
            "findings": findings,
        }, indent=2, sort_keys=True))
        return 1 if disagreeing else 0

    print(f"one-faucet live check -- {args.base} -- {args.ticker}")
    print(f"  endpoints compared : {len(SINGLE_SUBJECT) - len(unreachable)}")
    if unreachable:
        print(f"  unreachable        : {', '.join(unreachable)}")
    print(f"  excluded (reasoned): {len(EXCLUDED)}")
    print(f"  numeric fields     : {len(produced)}")
    print(f"  multi-faucet       : {len(multi)}"
          f"  ({100 * len(multi) // max(1, len(produced))}% -- every one is debt)")
    print(f"  DISAGREEING        : {len(disagreeing)}")

    for finding in findings:
        print(f"\n  FAIL  {finding['field']}   [{finding['faucets']} faucets]"
              f"  spread {finding['spread']:.6g} ({finding['spread_pct']:.3f}%)")
        for endpoint, value in finding["values"].items():
            print(f"          {value!s:<24} {endpoint}")

    if not disagreeing:
        print("\n  PASS -- every shared field agrees across every faucet.")
        return 0
    print(f"\n  {len(disagreeing)} field(s) disagree. Two screens can show "
          "contradictory numbers with nothing to detect it (RC-262).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
