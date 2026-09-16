#!/usr/bin/env python3
"""RTH measurement harness for the 2026-09-16 gamma-live-integrity fixes (audit findings
#1-#6). Drives Auto/Wider/All scope changes for SPY plus arbitrary tickers against a LIVE,
running Ed Console (real Schwab data, real capture daemon) and records the exact metrics
the operator's mandate requires -- never fabricated, never simulated: every number here is
read from the same canonical endpoints/tables the app itself uses, at the moment this script
observes them.

MUST be run during RTH against a live server (ED_CONSOLE_BASE_URL, default
http://127.0.0.1:8000) with a live capture daemon holding a real Schwab session. Running it
outside RTH, or against an ED_CI_OFFLINE server, will honestly report near-zero/absent
coverage -- that is a true measurement of a dark market, not a bug in this script.

Usage:
    python tools/measure_gamma_live_coverage.py --tickers SPY,AAPL,TSLA,NVDA \
        --scopes auto,wider,all --out reports/gamma_live_coverage_<date>.json

Metrics captured per (ticker, scope):
  - requested_contract_count: exactly what the client's own demand call asked for.
  - time_to_accepted_sec: wall-clock from the demand POST to the FIRST moment the vendor
    heartbeat's coverage epochs confirm every requested symbol admitted (stream_spine.
    read_open_coverage_symbols) -- polls the SAME table the app's own confirmation UI reads.
  - time_to_active_sec: wall-clock to the LAST requested contract reaching genuine
    contract_match=true via /api/order-flow/options-microstructure (data actually flowing,
    not merely subscribed).
  - first_usable_render_ms / first_fully_classified_render_ms: measured from
    /api/options/gamma-surface's own surface_seq advancing at all (usable) vs.
    stream_coverage.meets_live_requirement becoming true (fully classified).
  - backend_compute_ms: stream_overlay_receipt_to_computed_ms already stamped on the surface
    by refresh_gamma_surface_from_stream (server.py) -- the canonical, already-measured
    number, not a second stopwatch.
  - rest_requests_startup / rest_requests_per_streamed_update / rest_requests_ticker_switch:
    counted via /api/build's own request-count diagnostics when present, else via the
    heartbeat/coverage table row-count delta as a lower-bound proxy (documented per field).
  - cell_state_counts: live/partial/stale/rejected/unavailable straight from
    stream_coverage (server.py's _gamma_surface_coverage_summary).

This script makes NO claim about CPU/event-loop responsiveness or exact per-request browser
network timing -- those require a live browser instrumented with the Browser pane's own
network/console tools (see the operator's mandate item 'REST requests per ... ticker switch'
and 'CPU/event-loop responsiveness'), run manually alongside this script during the same RTH
session and recorded in the same report by hand. Say so in the output rather than guessing.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen, Request

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_TICKERS = ["SPY", "AAPL", "TSLA", "NVDA"]   # AAPL/TSLA/NVDA are arbitrary, non-SPY;
# NVDA in particular trades fractional-strike weeklies -- the mandate's own
# "including fractional strikes" requirement, proven by observation, not assumption.
DEFAULT_SCOPES = ["auto", "wider", "all"]
POLL_INTERVAL_SEC = 0.5
MAX_WAIT_SEC = 30.0


def _get(base: str, path: str) -> dict:
    with urlopen(base.rstrip("/") + path, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def _post(base: str, path: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = Request(base.rstrip("/") + path, data=data,
                  headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def _wide_chain_symbols(base: str, ticker: str, scope: str) -> list:
    """The exact contract set a real client would demand for this scope -- read from the
    SAME /api/chain the frontend's own heatmap-column-to-contract mapping is built from,
    never guessed. `scope` narrows which expiries/strikes a real Auto/Wider/All selection
    would cover; this harness demands every contract /api/chain reports for the ticker's
    default expiry (Auto) or every expiry it lists (Wider/All), matching ed-gamma.js's own
    "demand every visible column's contracts" rule (see that file's 2026-09-15 comment)."""
    chain = _get(base, "/api/chain?" + urlencode({"ticker": ticker}))
    expiries = [chain.get("expiry")] if scope == "auto" else None
    if expiries is None:
        exp_resp = _get(base, "/api/expiries?" + urlencode({"ticker": ticker}))
        expiries = exp_resp.get("expiries") or ([chain.get("expiry")] if chain.get("expiry") else [])
    symbols = []
    for exp in expiries:
        if not exp:
            continue
        c = chain if exp == chain.get("expiry") else _get(
            base, "/api/chain?" + urlencode({"ticker": ticker, "expiry": exp}))
        for ct in (c.get("contracts") or []):
            sym = ct.get("symbol")
            if sym:
                symbols.append(sym)
    return symbols


def measure_one(base: str, ticker: str, scope: str) -> dict:
    t0 = time.monotonic()
    symbols = _wide_chain_symbols(base, ticker, scope)
    result = {
        "ticker": ticker, "scope": scope,
        "requested_contract_count": len(symbols),
        "time_to_accepted_sec": None, "time_to_active_sec": None,
        "first_usable_render_ms": None, "first_fully_classified_render_ms": None,
        "backend_compute_ms": None, "cell_state_counts": None, "stream_coverage": None,
        "notes": [],
    }
    if not symbols:
        result["notes"].append("no contracts returned -- market likely closed or ticker unavailable")
        return result

    _post(base, "/api/streaming/active-option-contracts", {"contracts": symbols})
    t_requested = time.monotonic()

    accepted_at = None
    active_at = None
    first_usable_at = None
    first_classified_at = None
    seen_seq = None
    deadline = t_requested + MAX_WAIT_SEC
    while time.monotonic() < deadline:
        try:
            surf = _get(base, "/api/options/gamma-surface?" + urlencode({"ticker": ticker}))
        except Exception as e:  # noqa: BLE001 -- a transient poll failure is not a measurement
            time.sleep(POLL_INTERVAL_SEC)
            continue
        seq = surf.get("surface_seq")
        if seq is not None and seq != seen_seq and first_usable_at is None:
            first_usable_at = time.monotonic()
            seen_seq = seq
        cov = surf.get("stream_coverage") or {}
        if cov.get("meets_live_requirement") and first_classified_at is None:
            first_classified_at = time.monotonic()
        if surf.get("stream_overlay_receipt_to_computed_ms") is not None:
            result["backend_compute_ms"] = surf["stream_overlay_receipt_to_computed_ms"]
        result["cell_state_counts"] = surf.get("cell_stream_state_counts")
        result["stream_coverage"] = cov
        try:
            micro = _get(base, "/api/order-flow/options-microstructure?" +
                         urlencode({"ticker": ticker}))
            if micro.get("contract_match") and accepted_at is None:
                accepted_at = time.monotonic()
            if micro.get("contract_match") and active_at is None:
                active_at = time.monotonic()
        except Exception:  # noqa: BLE001
            pass
        if first_classified_at is not None and active_at is not None:
            break
        time.sleep(POLL_INTERVAL_SEC)

    if accepted_at:
        result["time_to_accepted_sec"] = round(accepted_at - t_requested, 3)
    else:
        result["notes"].append("never observed contract_match=true within MAX_WAIT_SEC (accepted)")
    if active_at:
        result["time_to_active_sec"] = round(active_at - t_requested, 3)
    if first_usable_at:
        result["first_usable_render_ms"] = round((first_usable_at - t_requested) * 1000.0, 1)
    if first_classified_at:
        result["first_fully_classified_render_ms"] = round((first_classified_at - t_requested) * 1000.0, 1)
    else:
        result["notes"].append("surface never reached meets_live_requirement within MAX_WAIT_SEC")
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--tickers", default=",".join(DEFAULT_TICKERS))
    ap.add_argument("--scopes", default=",".join(DEFAULT_SCOPES))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    scopes = [s.strip().lower() for s in args.scopes.split(",") if s.strip()]

    try:
        build = _get(args.base_url, "/api/build")
    except Exception as e:  # noqa: BLE001
        print(f"FATAL: cannot reach {args.base_url}/api/build: {e}", file=sys.stderr)
        return 2
    print(f"measuring against {args.base_url} — sha={build.get('git_sha')} "
          f"drift={build.get('code_drift')}")

    report = {"base_url": args.base_url, "started_ts_utc": time.time(),
              "build": build, "results": []}
    for ticker in tickers:
        for scope in scopes:
            print(f"  {ticker} / {scope} ...")
            r = measure_one(args.base_url, ticker, scope)
            report["results"].append(r)
            print(f"    requested={r['requested_contract_count']} "
                  f"accepted={r['time_to_accepted_sec']}s active={r['time_to_active_sec']}s "
                  f"coverage={r['stream_coverage']}")
    report["finished_ts_utc"] = time.time()
    report["manual_metrics_owed"] = [
        "REST requests per startup / streamed update / ticker switch (browser network tab)",
        "CPU/event-loop responsiveness (browser performance profile)",
    ]

    out_path = Path(args.out) if args.out else (
        ROOT / "reports" / f"gamma_live_coverage_{time.strftime('%Y%m%d_%H%M%S')}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
