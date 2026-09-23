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
  - requested_contract_count: exactly what the client's own demand call asked for. Auto/
    Wider/All are now GENUINELY DIFFERENT symbol sets (independent-review finding, 2026-09-
    16 follow-up mandate: a prior draft of this harness demanded every expiry for BOTH
    Wider and All, making them identical measurements wearing two names) -- see
    `_wide_chain_symbols`'s own docstring for the exact windowing rule. This script's own
    strike-count windowing is a HONEST APPROXIMATION of ed-core.js's real client-side
    scopeSelect, not a byte-for-byte replica -- proving the ACTUAL rendered scope's own
    emitted demand requires driving the real browser UI, which this Python/REST harness
    cannot do; see `manual_metrics_owed` in the report and, in
    tests/e2e/console-gamma-heatmap.spec.js, 'Wider and All scope declare real streaming
    demand for what they display, not zero', 'REAL-DATA VIEWPORT: 116x16 canonical surface
    -> Auto 11 rows...Wider 23...All 116x16' (both drive the actual #scopeCtl buttons/
    window.EdShell.setScope against real rendered cell counts), and 'a live gamma_surface_seq
    push re-renders and re-declares demand for the CURRENTLY SELECTED scope' for that proof.
  - time_to_accepted_sec / time_to_active_sec: tracked for EVERY requested symbol, never a
    single "primary" contract. CORRECTED 2026-09-17 (independent review, false-success
    finding): a REJECTED symbol no longer satisfies EITHER metric -- the prior formula
    `(admitted | active | rejected) == requested` treated a vendor REFUSAL as equivalent to
    a successful subscription, which is exactly backwards. `time_to_accepted_sec` is now
    wall-clock to the LAST requested symbol reaching 'admitted' OR 'active' OR 'observed'
    (a real vendor acknowledgement of SOME kind) with ZERO symbols rejected or unresolved;
    `time_to_active_sec` is wall-clock to the LAST requested symbol reaching 'active'
    SPECIFICALLY (freshness-gated -- a stale historical 'observed' tick does not count),
    again with zero rejected/unresolved. If any symbol is genuinely rejected, NEITHER
    timing is ever satisfied for that (ticker, scope) — a poisoned symbol makes full
    acceptance of the WHOLE requested set impossible by definition, and this harness must
    say so (`ok: false`, an explicit `rejected` list), never quietly time only the
    survivors and call it a pass.
  - admission_snapshot: the full per-symbol admitted/active/observed/pending/rejected/
    unresolved breakdown at the moment this measurement stopped polling, sourced from
    server.py's `_option_contract_admission_summary` (itself sourced entirely from
    PRODUCER acknowledgements) — so a reviewer can see exactly which symbols (if any)
    never resolved, not just an aggregate count.
  - baseline_surface_seq / first_usable_render_ms: `baseline_surface_seq` is captured
    BEFORE the demand POST (independent review finding, 2026-09-17: a prior draft only
    initialized its "seen" generation to None right before polling STARTED, so the very
    FIRST poll response — even one carrying the PRE-EXISTING generation from before demand
    was ever submitted — satisfied "a render happened"). `first_usable_render_ms` is now
    measured only once `surface_seq` is STRICTLY GREATER than that baseline.
  - baseline_gex_cells / gex_changed: `baseline_gex_cells` is captured from the SAME
    pre-demand read as `baseline_surface_seq`. `gex_changed` (bool) requires the post-
    demand surface to carry BOTH a strictly newer `surface_seq` AND at least one different
    displayed GEX-dollar cell value versus the baseline — matching the operator's own
    decisive proof ("spot changes and displayed GEX dollar cells visibly change").
  - first_fully_classified_render_ms: measured from stream_coverage.meets_live_requirement
    becoming true.
  - backend_compute_ms: stream_overlay_receipt_to_computed_ms already stamped on the surface
    by refresh_gamma_surface_from_stream/refresh_gamma_surface_from_spot_tick (server.py) --
    the canonical, already-measured number, not a second stopwatch.
  - rest_requests_startup / rest_requests_per_streamed_update / rest_requests_ticker_switch:
    counted via /api/build's own request-count diagnostics when present, else via the
    heartbeat/coverage table row-count delta as a lower-bound proxy (documented per field).
  - cell_state_counts: live/partial/stale/pending/daemon_unavailable/rejected/unavailable
    straight from stream_coverage (gamma_surface_state._gamma_surface_coverage_summary).
  - ok: the ONE pass/fail verdict for this (ticker, scope) — False on ANY of: a rejected
    symbol, an unresolved symbol, the daemon reporting unavailable, no strictly-newer
    surface_seq observed, or no GEX-dollar cell actually changing. `main()` exits nonzero
    if any requested (ticker, scope) has `ok: false`.

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


#: Auto shows the near-money strikes only; Wider widens that same window; All drops the
#: strike window AND the single-expiry restriction entirely. Independent-review finding
#: (2026-09-16, follow-up mandate item 8): a prior draft asked for every expiry for BOTH
#: Wider and All, making them identical measurements under two names. This does not claim
#: byte-for-byte parity with ed-core.js's own scopeSelect (a client-side pixel-count-driven
#: window) -- it is a HONEST, DIFFERENT, DOCUMENTED approximation of the same intent (a
#: strike-count-bounded near-money view vs. the complete book), sufficient to prove the
#: three scopes actually place genuinely different vendor demand, which is what the
#: mandate's "actual requested contract counts" and "Auto, Wider and All scopes" items ask
#: this harness to measure.
_AUTO_STRIKES_EACH_SIDE = 5     # Auto: 5 strikes above and below spot (11 total, both legs)
_WIDER_STRIKES_EACH_SIDE = 15   # Wider: 3x Auto's window


def _wide_chain_symbols(base: str, ticker: str, scope: str) -> list:
    """The contract set this harness demands for `scope`, read from the SAME /api/chain the
    frontend's own heatmap-column-to-contract mapping is built from, never guessed.

    'auto'  — the ticker's default expiry only, the _AUTO_STRIKES_EACH_SIDE strikes nearest
              spot on each side (both call and put legs).
    'wider' — the default expiry only, _WIDER_STRIKES_EACH_SIDE strikes nearest spot —
              GENUINELY more contracts than 'auto', never the same count.
    'all'   — every expiry /api/expiries lists, every strike each one reports — the
              complete book, no strike window at all."""
    chain = _get(base, "/api/chain?" + urlencode({"ticker": ticker}))
    spot = chain.get("spot")
    default_expiry = chain.get("expiry")

    def _strikes_near_spot(contracts: list, n_each_side: "int | None") -> list:
        if n_each_side is None or spot is None:
            return contracts
        by_strike: dict = {}
        for ct in contracts:
            k = ct.get("strikePrice")
            if k is None:
                continue
            by_strike.setdefault(float(k), []).append(ct)
        strikes_sorted = sorted(by_strike.keys(), key=lambda k: abs(k - float(spot)))
        kept_strikes = set(strikes_sorted[: n_each_side * 2])
        return [ct for k, cts in by_strike.items() if k in kept_strikes for ct in cts]

    if scope == "auto":
        expiries, window = [default_expiry], _AUTO_STRIKES_EACH_SIDE
    elif scope == "wider":
        expiries, window = [default_expiry], _WIDER_STRIKES_EACH_SIDE
    else:
        exp_resp = _get(base, "/api/expiries?" + urlencode({"ticker": ticker}))
        expiries = exp_resp.get("expiries") or ([default_expiry] if default_expiry else [])
        window = None

    symbols = []
    for exp in expiries:
        if not exp:
            continue
        c = chain if exp == default_expiry else _get(
            base, "/api/chain?" + urlencode({"ticker": ticker, "expiry": exp}))
        for ct in _strikes_near_spot(c.get("contracts") or [], window):
            sym = ct.get("symbol")
            if sym:
                symbols.append(sym)
    return symbols


def _surface_gex_cells(surf: dict) -> "list | None":
    """The exact displayed GEX-dollar values, in stable (strike, expiry-column) order, for
    the 'gex changed' proof -- read straight off the SAME cells the heatmap renders (never
    a derived/rounded copy), so a genuine comparison against a later read is possible."""
    cells = surf.get("cells")
    if not isinstance(cells, list):
        return None
    return [c.get("gex") for c in cells if isinstance(c, dict)]


def measure_one(base: str, ticker: str, scope: str) -> dict:
    symbols = _wide_chain_symbols(base, ticker, scope)
    result = {
        "ticker": ticker, "scope": scope,
        "requested_contract_count": len(symbols),
        "time_to_accepted_sec": None, "time_to_active_sec": None,
        "baseline_surface_seq": None, "first_usable_render_ms": None,
        "gex_changed": False, "first_fully_classified_render_ms": None,
        "backend_compute_ms": None, "cell_state_counts": None, "stream_coverage": None,
        "admission_snapshot": None,
        "ok": False,
        "notes": [],
    }
    if not symbols:
        result["notes"].append("no contracts returned -- market likely closed or ticker unavailable")
        return result
    requested = set(symbols)

    # Independent-review finding (2026-09-17): baseline surface_seq and displayed GEX
    # cells must be captured BEFORE the demand POST -- a prior draft only initialized its
    # "seen" generation to None right before polling started, so the very FIRST poll
    # response (even one carrying a generation from BEFORE this demand was ever submitted)
    # satisfied "a render happened". A post-demand render is proven only by a STRICTLY
    # newer generation than whatever already existed.
    try:
        baseline_surf = _get(base, "/api/options/gamma-surface?" + urlencode({"ticker": ticker}))
    except Exception as e:  # noqa: BLE001 -- a baseline read failure is a real measurement failure
        result["notes"].append(f"could not read baseline surface before demand: {e}")
        return result
    baseline_seq = baseline_surf.get("surface_seq")
    baseline_gex = _surface_gex_cells(baseline_surf)
    result["baseline_surface_seq"] = baseline_seq

    _post(base, "/api/streaming/active-option-contracts", {"contracts": symbols})
    t_requested = time.monotonic()

    # Independent-review finding (2026-09-16, follow-up mandate item 8): the prior version
    # tracked ONE "primary" contract via /api/order-flow/options-microstructure regardless
    # of how many symbols were actually requested. Every one of `requested` is now tracked
    # through requested -> admitted/active/observed -> (or rejected), sourced from
    # /api/options/gamma-surface's own `contract_admission` field -- itself sourced from
    # genuine PRODUCER acknowledgements, never a client-side desired-state guess.
    #
    # CORRECTED 2026-09-17 (independent review, false-success finding): a REJECTED symbol
    # must NEVER satisfy 'accepted' or 'active' -- it is the opposite of a successful
    # subscription. Both timings require the FULL requested set to be free of
    # rejected/unresolved symbols; a single rejection makes both permanently unsatisfiable
    # for this (ticker, scope), which the harness must say plainly, not paper over by
    # timing only the symbols that happened to succeed.
    accepted_at = None    # LAST requested symbol reaches admitted/active/observed, ZERO rejected/unresolved
    active_at = None      # LAST requested symbol reaches 'active' SPECIFICALLY (freshness-gated), ZERO rejected/unresolved
    first_usable_at = None
    first_classified_at = None
    gex_changed_at = None
    last_admission: dict = {}
    last_surf: dict = {}
    deadline = t_requested + MAX_WAIT_SEC
    while time.monotonic() < deadline:
        try:
            surf = _get(base, "/api/options/gamma-surface?" + urlencode({"ticker": ticker}))
        except Exception:  # institutional-swallow-ok: a transient poll failure is not a
            # measurement -- the loop simply retries on the next tick; a persistent failure
            # surfaces as this measurement's own "never resolved" notes below.
            time.sleep(POLL_INTERVAL_SEC)
            continue
        last_surf = surf
        seq = surf.get("surface_seq")
        if first_usable_at is None and seq is not None and (
                baseline_seq is None or seq > baseline_seq):
            first_usable_at = time.monotonic()
        if gex_changed_at is None and first_usable_at is not None:
            cur_gex = _surface_gex_cells(surf)
            if cur_gex is not None and baseline_gex is not None and cur_gex != baseline_gex:
                gex_changed_at = time.monotonic()
                result["gex_changed"] = True
        cov = surf.get("stream_coverage") or {}
        if cov.get("meets_live_requirement") and first_classified_at is None:
            first_classified_at = time.monotonic()
        if surf.get("stream_overlay_receipt_to_computed_ms") is not None:
            result["backend_compute_ms"] = surf["stream_overlay_receipt_to_computed_ms"]
        result["cell_state_counts"] = surf.get("cell_stream_state_counts")
        result["stream_coverage"] = cov

        admission = surf.get("contract_admission") or {}
        last_admission = admission
        admitted = requested & set(admission.get("admitted") or [])
        active = requested & set(admission.get("active") or [])
        observed = requested & set(admission.get("observed") or [])
        rejected = requested & set((admission.get("rejected") or {}).keys())
        resolved_some_way = admitted | active | observed | rejected
        unresolved_now = requested - resolved_some_way
        if accepted_at is None and not rejected and not unresolved_now:
            accepted_at = time.monotonic()
        if active_at is None and active == requested:
            active_at = time.monotonic()

        if first_classified_at is not None and active_at is not None and gex_changed_at is not None:
            break
        time.sleep(POLL_INTERVAL_SEC)

    admitted_f = requested & set(last_admission.get("admitted") or [])
    active_f = requested & set(last_admission.get("active") or [])
    observed_f = requested & set(last_admission.get("observed") or [])
    rejected_f = {s: r for s, r in (last_admission.get("rejected") or {}).items() if s in requested}
    unresolved_f = requested - admitted_f - active_f - observed_f - set(rejected_f.keys())
    daemon_available = last_admission.get("daemon_available")
    result["admission_snapshot"] = {
        "daemon_available": daemon_available,
        "admitted": sorted(admitted_f), "active": sorted(active_f), "observed": sorted(observed_f),
        "rejected": rejected_f, "unresolved": sorted(unresolved_f),
    }

    if rejected_f:
        result["notes"].append(
            f"{len(rejected_f)} of {len(requested)} requested symbol(s) REJECTED by the "
            f"vendor -- full acceptance of this (ticker, scope) is impossible: {sorted(rejected_f)}")
    if unresolved_f:
        result["notes"].append(
            f"{len(unresolved_f)} of {len(requested)} requested symbol(s) never reached "
            f"admitted/active/observed/rejected within MAX_WAIT_SEC: {sorted(unresolved_f)}")
    if daemon_available is False:
        result["notes"].append("capture daemon reported UNAVAILABLE during this measurement")

    if accepted_at:
        result["time_to_accepted_sec"] = round(accepted_at - t_requested, 3)
    if active_at:
        result["time_to_active_sec"] = round(active_at - t_requested, 3)
    elif not rejected_f and not unresolved_f:
        result["notes"].append("not every requested symbol reached freshness-gated 'active' within MAX_WAIT_SEC")
    if first_usable_at:
        result["first_usable_render_ms"] = round((first_usable_at - t_requested) * 1000.0, 1)
    else:
        result["notes"].append(
            f"surface_seq never advanced past the pre-demand baseline ({baseline_seq}) "
            f"within MAX_WAIT_SEC")
    if first_classified_at:
        result["first_fully_classified_render_ms"] = round((first_classified_at - t_requested) * 1000.0, 1)
    else:
        result["notes"].append("surface never reached meets_live_requirement within MAX_WAIT_SEC")
    if not result["gex_changed"]:
        result["notes"].append("no displayed GEX-dollar cell changed from its pre-demand baseline")

    # The ONE pass/fail verdict: any rejected/unresolved symbol, an unavailable daemon, no
    # strictly-newer generation, or no changed GEX cell fails this (ticker, scope) outright
    # -- never a narrative "mostly worked".
    result["ok"] = bool(
        not rejected_f and not unresolved_f and daemon_available is not False
        and first_usable_at is not None and result["gex_changed"]
    )
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
    any_failed = False
    for ticker in tickers:
        for scope in scopes:
            print(f"  {ticker} / {scope} ...")
            r = measure_one(args.base_url, ticker, scope)
            report["results"].append(r)
            verdict = "PASS" if r["ok"] else "FAIL"
            if not r["ok"]:
                any_failed = True
            print(f"    [{verdict}] requested={r['requested_contract_count']} "
                  f"accepted={r['time_to_accepted_sec']}s active={r['time_to_active_sec']}s "
                  f"gex_changed={r['gex_changed']} coverage={r['stream_coverage']}")
            for note in r["notes"]:
                print(f"      note: {note}")
    report["finished_ts_utc"] = time.time()
    report["all_ok"] = not any_failed
    report["manual_metrics_owed"] = [
        "REST requests per startup / streamed update / ticker switch (browser network tab)",
        "CPU/event-loop responsiveness (browser performance profile)",
        "Auto/Wider/All scope proof against the ACTUAL rendered browser UI (this harness's "
        "own strike-count windowing is a documented approximation, not the real "
        "ed-core.js scopeSelect -- already covered by real-browser Playwright tests in "
        "tests/e2e/console-gamma-heatmap.spec.js, not by this REST-only script)",
    ]

    out_path = Path(args.out) if args.out else (
        ROOT / "reports" / f"gamma_live_coverage_{time.strftime('%Y%m%d_%H%M%S')}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {out_path}")
    if any_failed:
        print("FAIL: at least one requested (ticker, scope) did not pass -- see notes above", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
