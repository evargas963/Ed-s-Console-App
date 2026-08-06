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


def numeric_leaves(obj: Any, out: dict[str, Any] | None = None,
                   depth: int = 0) -> dict[str, Any]:
    """Scalar numeric leaves keyed by bare field name.

    Lists are NOT descended into. A list element is one row among many and
    comparing row zero of two different collections is not a faucet comparison.
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
    return out


def fetch(base: str, endpoint: str, ticker: str) -> dict[str, Any] | None:
    url = f"{base}{endpoint}?ticker={ticker}"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SEC) as response:
            return json.loads(response.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None


def census(base: str, ticker: str) -> tuple[dict[str, dict[str, Any]], list[str]]:
    produced: dict[str, dict[str, Any]] = defaultdict(dict)
    unreachable: list[str] = []
    for endpoint in SINGLE_SUBJECT:
        payload = fetch(base, endpoint, ticker)
        if payload is None:
            unreachable.append(endpoint)
            continue
        for name, value in numeric_leaves(payload).items():
            if name in META or name.startswith("_") or is_volatile(name):
                continue
            produced[name][endpoint] = value
    return produced, unreachable


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--ticker", default=DEFAULT_TICKER)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    if fetch(args.base, "/api/spot", args.ticker) is None:
        sys.stderr.write(
            f"one-faucet: server unreachable at {args.base}. This check needs a "
            "running server -- it verifies behaviour, not source text.\n")
        return 2

    produced, unreachable = census(args.base, args.ticker)
    multi = {f: m for f, m in produced.items() if len(m) > 1}
    disagreeing = {f: m for f, m in multi.items() if len(set(m.values())) > 1}

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
