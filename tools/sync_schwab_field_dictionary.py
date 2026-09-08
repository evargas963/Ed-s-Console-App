"""RC-380 — union-merge a live Schwab capture into the committed field dictionary.

WHY THIS EXISTS. `schwab_field_dictionary_builder.main()` rebuilds the dictionary with
`open(dict_file, "w")` from whatever the newest capture happened to contain. Measured
2026-08-15 against live Schwab: `movers` returns `{"screeners": []}` outside trading
hours and `market_hours` omits its `sessionHours` block when `isOpen` is false. A
refresh taken in that state does not record "unchanged" — it DELETES every catalog row
those endpoints contributed. So the artifact that is supposed to be the authority on
"what fields does the vendor give us" could only be refreshed by risking its own truth,
and it therefore sat three months stale while Schwab added `breakEven`, `ssid`,
`hasBinaryOptions` and `ethOptionEligible`.

THE RULE THIS ENCODES. A vendor-surface catalog is a UNION OVER TIME, never a snapshot.
An observation can add a field or update `last_seen`; it can never remove one. Absence
in a capture is unobservability, not deletion — the two are indistinguishable from a
single poll, so the safe direction is the only defensible one. A field Schwab genuinely
retires is then visible as a stale `last_seen`, which is a fact someone can act on,
rather than a silent disappearance nobody sees.

Partial captures are recorded AS partial: the sync state carries per-endpoint observed
counts, so a later reader can tell "movers contributed nothing today" from "movers was
never polled". Both are honest; neither is a deletion.

Usage:
    python tools/sync_schwab_field_dictionary.py --poll          # live Schwab, then merge
    python tools/sync_schwab_field_dictionary.py --capture f.json  # merge a saved capture
    python tools/sync_schwab_field_dictionary.py --poll --dry-run  # report, write nothing
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

DICTIONARY_PATH = REPO / "schwab_field_inventory" / "schwab_field_dictionary.csv"
SYNC_STATE_PATH = REPO / "reports" / "artifacts" / "schwab_field_sync_state.json"

#: Original six columns stay first and unchanged so existing DictReader consumers
#: (tools/build_feature_assignment_matrix_v2.py and the gates reading it) are untouched.
BASE_COLUMNS = [
    "canonical_field", "source_endpoints", "example_raw_field",
    "category", "likely_use", "priority",
]
HISTORY_COLUMNS = ["first_seen", "last_seen"]
COLUMNS = BASE_COLUMNS + HISTORY_COLUMNS

#: Every market-data endpoint the dictionary catalogs. Named explicitly rather than
#: discovered, so a capture that silently loses an endpoint is visible as a zero count.
ENDPOINTS = ("quotes", "chains", "pricehistory", "market_hours", "instruments", "movers")


def load_dictionary(path: Path = DICTIONARY_PATH) -> dict[str, dict[str, str]]:
    """Committed dictionary as {canonical_field: row}. Missing file is an empty catalog."""
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8", errors="replace", newline="") as fh:
        return {r["canonical_field"]: dict(r) for r in csv.DictReader(fh)}


def capture_live(strike_count: int = 6) -> dict[str, Any]:
    """Poll every market-data endpoint. An endpoint that fails is OMITTED, never faked.

    Omission matters: a missing key means "not observed", which the merge treats as
    no information. Writing an empty payload instead would claim the endpoint returned
    nothing, which is a different and unproven statement.
    """
    from config import build_config
    from schwab_client import build_client_from_token

    cfg = build_config(REPO)
    state = build_client_from_token(
        api_key=cfg.api_key, app_secret=cfg.app_secret, token_path=cfg.token_path,
    )
    if not state.ok:
        raise RuntimeError(f"Schwab client unavailable: {state.message}")
    c = state.client
    calls = {
        "quotes": lambda: c.get_quotes(["SPY", "QQQ", "IWM"]),
        "chains": lambda: c.get_option_chain("SPY", strike_count=strike_count),
        "pricehistory": lambda: c.get_price_history_every_minute("SPY"),
        "market_hours": lambda: c.get_market_hours(
            [c.MarketHours.Market.EQUITY, c.MarketHours.Market.OPTION]),
        # FUNDAMENTAL, not SYMBOL_SEARCH: measured 2026-08-15, SYMBOL_SEARCH returns 7
        # fields where FUNDAMENTAL returns the 63 the dictionary was built from. The
        # projection is part of the observation contract, not an incidental argument.
        "instruments": lambda: c.get_instruments(["SPY"], c.Instrument.Projection.FUNDAMENTAL),
        "movers": lambda: c.get_movers(c.Movers.Index.SPX),
    }
    out: dict[str, Any] = {}
    for name, fn in calls.items():
        try:
            resp = fn()
        except Exception as exc:  # noqa: BLE001 - any transport failure is "not observed"
            print(f"  {name:14s} NOT OBSERVED ({type(exc).__name__}: {str(exc)[:60]})")
            continue
        if getattr(resp, "status_code", None) != 200:
            print(f"  {name:14s} NOT OBSERVED (HTTP {getattr(resp, 'status_code', '?')})")
            continue
        out[name] = resp.json()
        print(f"  {name:14s} observed ({len(resp.text):,} bytes)")
    return out


def fields_from_capture(capture: dict[str, Any]) -> dict[str, set[str]]:
    """{endpoint: {canonical_field}} using the repo's own flatten + normalize."""
    from schwab_field_dictionary_builder import normalize_path
    from schwab_full_field_inventory import flatten_json

    out: dict[str, set[str]] = {}
    for endpoint, payload in capture.items():
        flat = flatten_json(payload)
        raw_keys = flat.keys() if isinstance(flat, dict) else flat
        seen = set()
        for raw in raw_keys:
            canonical = normalize_path(str(raw), endpoint)
            if canonical:
                seen.add(canonical)
        out[endpoint] = seen
    return out


def merge(
    existing: dict[str, dict[str, str]],
    observed: dict[str, set[str]],
    *,
    today: str,
) -> tuple[dict[str, dict[str, str]], list[str], list[str]]:
    """Union-merge. Returns (merged, added, refreshed) and NEVER drops an existing key."""
    merged = {k: dict(v) for k, v in existing.items()}
    added: list[str] = []
    refreshed: list[str] = []
    for endpoint, fields in observed.items():
        for field in sorted(fields):
            row = merged.get(field)
            if row is None:
                merged[field] = {
                    "canonical_field": field,
                    "source_endpoints": endpoint,
                    "example_raw_field": field.split(".", 1)[-1],
                    "category": "unclassified",
                    "likely_use": "unreviewed",
                    "priority": "unreviewed",
                    "first_seen": today,
                    "last_seen": today,
                }
                added.append(field)
                continue
            eps = {e for e in (row.get("source_endpoints") or "").replace("|", ";").split(";") if e}
            eps.add(endpoint)
            row["source_endpoints"] = ";".join(sorted(eps))
            row["last_seen"] = today
            row.setdefault("first_seen", "")
            refreshed.append(field)
    # Rows never observed in this capture keep their history untouched — unobserved is
    # not absent, and this is the single line that makes a partial capture safe.
    for field, row in merged.items():
        row.setdefault("first_seen", "")
        row.setdefault("last_seen", "")
    return merged, added, refreshed


def write_dictionary(merged: dict[str, dict[str, str]], path: Path = DICTIONARY_PATH) -> None:
    """Write the union. LF pinned TWICE, deliberately.

    `newline=""` on the handle stops Python translating, and `lineterminator="\\n"` stops
    csv from emitting its own CRLF — csv.writer defaults to \\r\\n independently of how the
    file was opened, so passing newline="\\n" alone silently produced CRLF and would have
    reflowed all 2,393 rows on the first sync (RC-372 class, caught by this module's test).
    """
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for field in sorted(merged):
            writer.writerow({c: merged[field].get(c, "") for c in COLUMNS})


def write_sync_state(observed: dict[str, set[str]], added: list[str], path: Path = SYNC_STATE_PATH) -> dict:
    """Record WHAT was observed, per endpoint, so a partial sync is legible as partial."""
    state = {
        "synced_at_utc": datetime.now(timezone.utc).isoformat(),
        "endpoints_observed": {ep: len(observed.get(ep, ())) for ep in ENDPOINTS},
        "endpoints_not_observed": [ep for ep in ENDPOINTS if ep not in observed],
        "fields_added": sorted(added),
        "note": (
            "endpoints_not_observed and a zero count are NOT deletions — the union merge "
            "never removes a catalogued field. An endpoint returning an empty collection "
            "(movers outside trading hours) contributes zero observed fields."
        ),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8", newline="\n")
    return state


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Union-merge a Schwab capture into the field dictionary")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--poll", action="store_true", help="poll live Schwab")
    src.add_argument("--capture", type=Path, help="merge a saved capture JSON")
    ap.add_argument("--dry-run", action="store_true", help="report only; write nothing")
    ap.add_argument("--strike-count", type=int, default=6)
    args = ap.parse_args(argv)

    print("Capturing Schwab surface:")
    capture = (
        capture_live(strike_count=args.strike_count) if args.poll
        else json.loads(args.capture.read_text(encoding="utf-8"))
    )
    if not capture:
        print("NO ENDPOINT OBSERVED — refusing to write a sync state that claims a sync happened.")
        return 1

    existing = load_dictionary()
    observed = fields_from_capture(capture)
    today = datetime.now(timezone.utc).date().isoformat()
    merged, added, refreshed = merge(existing, observed, today=today)

    print(f"\nexisting catalogue : {len(existing)}")
    print(f"observed this run  : {sum(len(v) for v in observed.values())} "
          f"across {len(observed)} endpoint(s)")
    print(f"NEW fields         : {len(added)}")
    for f in added:
        print(f"    + {f}")
    print(f"refreshed last_seen: {len(set(refreshed))}")
    print(f"merged catalogue   : {len(merged)}  (never shrinks: {len(merged) >= len(existing)})")

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return 0
    write_dictionary(merged)
    state = write_sync_state(observed, added)
    print(f"\nwrote {DICTIONARY_PATH.relative_to(REPO).as_posix()}")
    print(f"wrote {SYNC_STATE_PATH.relative_to(REPO).as_posix()}  "
          f"(not observed: {state['endpoints_not_observed'] or 'none'})")
    # The JSON is a SEPARATE artifact and its loader short-circuits: it returns the
    # on-disk registry whenever schwab_field_count >= 2300, so a CSV-only sync leaves the
    # ML feature universe on the old field set while the CSV looks refreshed. Measured
    # 2026-08-15: CSV 2411 / JSON 2393 until this second command ran.
    # Module form, not the script path — `python tools/build_feature_assignment_matrix_v2.py`
    # dies with ModuleNotFoundError: governed_stack_contract (repo root not on sys.path).
    print("\nREMINDER: the JSON registry does NOT auto-update. Run:")
    print("  python -m tools.build_feature_assignment_matrix_v2 --build-schwab-ablation-universe")
    return 0


if __name__ == "__main__":
    sys.exit(main())
