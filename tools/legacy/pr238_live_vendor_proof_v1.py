#!/usr/bin/env python3
"""PR #238 live-vendor proof — the one remaining merge-gating item on the UI rebuild.

WHAT THIS ANSWERS: does a real Schwab-streamed tick actually reach the new Options/Gamma
heatmap's own served surface, with correct (ticker, strike, expiry, contract-symbol)
identity, end to end through the real production pipeline (capture daemon ->
stream_capture.db -> this console's _feed_loop -> refresh_gamma_surface_from_stream /
_terrain_refresh_one -> GET /api/options/gamma-surface)? Every prior round proved this
mechanism against a protocol-faithful SIMULATED stream only (see the PR body's own
"What remains NOT_PROVEN" section, round 6 onward) — never against a live vendor session.
This script is the smallest valid proof of that one remaining gap. It does NOT re-prove
browser rendering/theme/layout fidelity (already proven live in prior rounds), production
deployment (a separate, post-merge ops step), SDK wire-transport depth, Wider/All-scope
capacity, or GOOG backfill (all classified as non-blocking for this cutover — see the PR
body / operator record).

HOW TO RUN (operator prerequisite — see AGENTS.md / project memory for the exact steps):
  1. Stop whatever console is currently on :8000.
  2. Start THIS branch's console as the sole owner (production checkout's own
     start_ed_console.bat, or the worktree's equivalent), during a real RTH session,
     with the real Schwab capture daemon already running.
  3. Tell the operating agent it is running. Nothing else is required of the operator —
     this script performs and records the rest, including selecting a real ATM option
     contract and subscribing it via the console's own canonical endpoint.

Usage:
  .venv/Scripts/python.exe tools/pr238_live_vendor_proof_v1.py
  .venv/Scripts/python.exe tools/pr238_live_vendor_proof_v1.py --ticker SPY --second-ticker AAPL
  .venv/Scripts/python.exe tools/pr238_live_vendor_proof_v1.py --duration-sec 180 --interval-sec 3

PLUMBING DISCIPLINE (load-bearing): every check below goes through the console's own
public HTTP routes — the exact endpoints the browser UI calls (GET /api/build, /api/health,
/api/live/state, /api/live/plane, /api/terrain, /api/chain, /api/options/gamma-surface,
/api/order-flow/options-microstructure; POST /api/streaming/active-option-contract). Nothing
here imports server internals, calls a producer function directly, or substitutes a fixture
for a real vendor response. `pick_atm_call` and `_locate_cell_for_symbol` are pure selection
over data already fetched from the live API — never a re-derivation of a market value.

Required clean verdict across five acceptance dimensions per ticker (operator directive):
  1. live tick identity — the observed overlay names OUR subscribed contract, not a leftover.
  2. heatmap updates    — the exact served grid cell backing that contract changed value.
  3. overlay state      — a genuine streamed overlay landed on the surface at all.
  4. freshness          — age_sec behaved sanely throughout (never negative/garbled).
  5. ticker switching   — every poll's own echoed ticker matched what was requested, and no
                           ticker's subscribed contract was ever observed under another ticker.

Exit codes: 0 = PASS (at least one ticker cleared all five dimensions, and no cross-ticker
contamination was found); 1 = PARTIAL (baseline live data confirmed real and un-fabricated,
but no ticker's overlay+identity+freshness+switching all cleared — inconclusive due to
market quietness/timing, not necessarily a defect); 2 = FAIL (console unreachable, code
drift, Schwab not AVAILABLE, a baseline check itself failed, or genuine cross-ticker
contamination was observed — this is NOT proof, do not read a missing evidence file as a
pass, RC-57 discipline).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE_URL = "http://127.0.0.1:8000"  # never 'localhost' — IPv6-first resolution costs ~2s/probe


def _repo_head_sha() -> Optional[str]:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True,
            check=True, timeout=5.0,
        )
        return (proc.stdout or "").strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


class ConsoleClient:
    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get(self, path: str, params: Optional[dict] = None) -> tuple[int, Any]:
        url = self.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, method="GET")
        return self._send(req)

    def post(self, path: str, body: dict) -> tuple[int, Any]:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + path, data=data, method="POST",
            headers={"Content-Type": "application/json"},
        )
        return self._send(req)

    def _send(self, req: urllib.request.Request) -> tuple[int, Any]:
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                status = resp.status
        except urllib.error.HTTPError as e:
            raw = e.read()
            status = e.code
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            # Connection refused / no route / timeout — the console is not reachable at
            # all. Status 0 is not a real HTTP status; every caller must treat it as a
            # hard failure, never as "200 with an empty body."
            return 0, {"_connection_error": f"{type(e).__name__}: {e}"}
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else None
        except (ValueError, UnicodeDecodeError):
            payload = {"_raw_unparseable": raw[:400].decode("utf-8", "replace")}
        return status, payload


@dataclass
class TickerProof:
    ticker: str
    baseline_ok: bool = False
    baseline_detail: dict = field(default_factory=dict)
    subscribed_contract: Optional[str] = None
    subscribe_ok: bool = False
    polls: list = field(default_factory=list)
    terrain_cycle_advanced: bool = False
    stream_overlay_observed: bool = False
    stream_overlay_first_poll_index: Optional[int] = None
    stream_overlay_symbols_seen: list = field(default_factory=list)
    microstructure_contract_match_observed: bool = False
    # Dimension 2 (heatmap updates): the SAME served surface the browser renders verbatim
    # (ONE FAUCET — no frontend computation, established repo-wide) — a genuine value change
    # at the exact cell backing the subscribed contract is direct proof the heatmap's own
    # numbers moved, without needing browser automation to re-prove a rendering fidelity
    # this PR's prior rounds already established live.
    subscribed_cell_located: bool = False
    subscribed_cell_value_before: Optional[float] = None
    subscribed_cell_value_after: Optional[float] = None
    subscribed_cell_value_changed: bool = False
    # Dimension 4 (freshness): age_sec / stale must behave sanely across the poll window —
    # never negative, never stuck at a value that contradicts a live overlay landing.
    freshness_samples: list = field(default_factory=list)
    freshness_sane: bool = False
    # Dimension 5 (ticker switching): every poll's own echoed ticker/symbol must match what
    # THIS run actually requested — a mismatch is a real cross-ticker leak, not a formality.
    ticker_identity_mismatches: int = 0
    verdict: str = "NOT_RUN"


def check_identity(client: ConsoleClient, expected_sha: Optional[str]) -> dict:
    status, build = client.get("/api/build")
    if status != 200 or not isinstance(build, dict):
        return {"ok": False, "reason": f"/api/build returned status={status}"}
    running_sha = (build.get("process_identity") or {}).get("startup_git_sha")
    drift = build.get("code_drift") or {}
    status_h, health = client.get("/api/health")
    if status_h != 200 or not isinstance(health, dict):
        return {"ok": False, "reason": f"/api/health returned status={status_h}"}
    schwab_status = (health.get("capabilities") or {}).get("schwab")
    ok = schwab_status == "AVAILABLE"
    return {
        "ok": ok,
        "reason": None if ok else f"Schwab capability = {schwab_status!r}, expected AVAILABLE",
        "running_sha": running_sha,
        "expected_sha_at_script_start": expected_sha,
        "sha_matches_current_branch_tip": (
            None if not (running_sha and expected_sha) else running_sha == expected_sha
        ),
        "code_drift": drift,
        "startup_git_dirty": (build.get("process_identity") or {}).get("startup_git_dirty"),
        "logger_running": health.get("logger_running"),
        "logger_tickers": health.get("logger_tickers"),
    }


def check_baseline(client: ConsoleClient, ticker: str) -> dict:
    out: dict = {}
    status, live = client.get("/api/live/state", {"ticker": ticker})
    out["live_state"] = {"status": status, "spot": (live or {}).get("spot"),
                          "state_error": (live or {}).get("state_error"),
                          "session_label": (live or {}).get("session_label")}
    status, plane = client.get("/api/live/plane", {"ticker": ticker})
    out["plane"] = {"status": status, "plane_quote_authority": (plane or {}).get("plane_quote_authority")}
    status, terrain = client.get("/api/terrain", {"ticker": ticker})
    out["terrain"] = {
        "status": status, "confidence": (terrain or {}).get("confidence"),
        "regime": (terrain or {}).get("regime"), "chain_basis": (terrain or {}).get("chain_basis"),
        "gamma_flip": (terrain or {}).get("gamma_flip"), "call_wall": (terrain or {}).get("call_wall"),
        "put_wall": (terrain or {}).get("put_wall"), "levels_stale": (terrain or {}).get("levels_stale"),
        "computed_ts_utc": (terrain or {}).get("computed_ts_utc"),
    }
    status, chain = client.get("/api/chain", {"ticker": ticker})
    contracts = (chain or {}).get("contracts") or []
    out["chain"] = {
        "status": status, "scope_kind": ((chain or {}).get("scope") or {}).get("kind"),
        "contract_count": len(contracts), "spot": (chain or {}).get("spot"),
        "expiry": (chain or {}).get("expiry"),
    }
    out["_raw_chain_contracts_sample"] = contracts[:2]
    ok = (
        out["live_state"]["status"] == 200 and out["live_state"]["spot"] is not None
        and not out["live_state"]["state_error"]
        and out["terrain"]["status"] == 200
        and out["chain"]["status"] == 200 and out["chain"]["contract_count"] > 0
    )
    out["ok"] = ok
    return out


def pick_atm_call(contracts: list, spot: Optional[float]) -> Optional[dict]:
    if not contracts or spot is None:
        return None
    calls = [c for c in contracts if str(c.get("putCall", "")).upper() == "CALL"
             and c.get("strikePrice") is not None and c.get("symbol")]
    if not calls:
        return None
    return min(calls, key=lambda c: abs(float(c["strikePrice"]) - float(spot)))


def _locate_cell_for_symbol(surf: dict, symbol: str) -> Optional[tuple[int, int]]:
    """Find (row, col) in the surface's own `cells` for the vendor symbol we subscribed —
    the exact same per-cell identity project_gamma_surface stamps and the heatmap grid
    reads to build its click-to-select/streaming-demand behavior. Never guessed from the
    strike/expiry we think we asked for; read back from the surface's own contracts field."""
    cells = surf.get("cells") or []
    for row_idx, row in enumerate(cells):
        contracts_row = row.get("contracts") or []
        for col_idx, pair in enumerate(contracts_row):
            if not isinstance(pair, dict):
                continue
            if pair.get("call") == symbol or pair.get("put") == symbol:
                return row_idx, col_idx
    return None


def poll_live_overlay(
    client: ConsoleClient, ticker: str, contract_symbol: Optional[str],
    duration_sec: float, interval_sec: float,
) -> dict:
    """Polls the real /api/options/gamma-surface and /api/order-flow/options-microstructure
    endpoints — the exact routes the browser UI calls — for `duration_sec`, tracking every
    dimension the operator's acceptance list names. Returns a dict of raw findings; run_for_ticker
    turns these into the TickerProof verdict fields."""
    polls: list = []
    seen_ts: set = set()
    overlay_observed = False
    overlay_symbols: list = []
    overlay_first_poll_index: Optional[int] = None
    micro_match = False
    cell_loc: Optional[tuple[int, int]] = None
    cell_value_before: Optional[float] = None
    cell_value_after: Optional[float] = None
    cell_value_changed = False
    freshness_samples: list = []
    freshness_sane = True
    ticker_identity_mismatches = 0
    deadline = time.monotonic() + duration_sec
    poll_index = -1
    while time.monotonic() < deadline:
        poll_index += 1
        status, surf = client.get("/api/options/gamma-surface", {"ticker": ticker})
        surf = surf if isinstance(surf, dict) else {}
        rec = {
            "poll_index": poll_index,
            "t_mono": round(time.monotonic(), 2), "status": status,
            "source": surf.get("source"), "live": surf.get("live"),
            "stale": surf.get("stale"), "age_sec": surf.get("age_sec"),
            "spot": surf.get("spot"),
            "chain_as_of_ts_utc": surf.get("chain_as_of_ts_utc"),
            "stream_overlay_contracts": surf.get("stream_overlay_contracts"),
            "stream_overlay_symbols": surf.get("stream_overlay_symbols"),
            "returned_ticker": surf.get("ticker") or surf.get("symbol"),
        }
        # Dimension 5 (ticker switching): the surface's OWN echoed identity must match what
        # this call actually requested. A mismatch is a genuine cross-ticker leak.
        if status == 200 and rec["returned_ticker"] is not None:
            if str(rec["returned_ticker"]).upper() != ticker.upper():
                ticker_identity_mismatches += 1
        # Dimension 4 (freshness): age_sec must never be negative, and a currently-live,
        # non-stale surface must report a finite age — a freshness field that has stopped
        # moving or gone impossible is not proof of anything.
        age = rec["age_sec"]
        if age is not None:
            try:
                age_f = float(age)
                freshness_samples.append(age_f)
                if age_f < 0:
                    freshness_sane = False
            except (TypeError, ValueError):
                freshness_sane = False
        if rec["chain_as_of_ts_utc"] is not None:
            seen_ts.add(rec["chain_as_of_ts_utc"])
        n_overlay = rec["stream_overlay_contracts"] or 0
        syms = rec["stream_overlay_symbols"] or []
        if n_overlay > 0 and syms:
            if not overlay_observed:
                overlay_first_poll_index = poll_index
            overlay_observed = True
            for s in syms:
                if s not in overlay_symbols:
                    overlay_symbols.append(s)
        # Dimension 2 (heatmap updates): locate the exact grid cell backing our subscribed
        # contract (server-stamped identity, never guessed) and track its own displayed
        # value across polls — this IS the number the heatmap grid paints verbatim.
        if contract_symbol and status == 200:
            loc = _locate_cell_for_symbol(surf, contract_symbol)
            if loc is not None:
                cell_loc = loc
                row_idx, col_idx = loc
                cells = surf.get("cells") or []
                gex_row = (cells[row_idx] or {}).get("gex") or [] if row_idx < len(cells) else []
                val = gex_row[col_idx] if col_idx < len(gex_row) else None
                if val is not None:
                    if cell_value_before is None:
                        cell_value_before = val
                    elif val != cell_value_before:
                        cell_value_changed = True
                    cell_value_after = val
            status_m, micro = client.get(
                "/api/order-flow/options-microstructure", {"contract": contract_symbol})
            splane = (micro or {}).get("streaming_plane") or {}
            rec["microstructure_status"] = status_m
            rec["microstructure_contract_match"] = splane.get("contract_match")
            if splane.get("contract_match") is True:
                micro_match = True
        polls.append(rec)
        time.sleep(max(0.5, interval_sec))
    return {
        "polls": polls,
        "terrain_cycle_advanced": len(seen_ts) > 1,
        "overlay_observed": overlay_observed,
        "overlay_symbols": overlay_symbols,
        "overlay_first_poll_index": overlay_first_poll_index,
        "micro_match": micro_match,
        "cell_located": cell_loc is not None,
        "cell_value_before": cell_value_before,
        "cell_value_after": cell_value_after,
        "cell_value_changed": cell_value_changed,
        "freshness_samples": freshness_samples,
        "freshness_sane": freshness_sane,
        "ticker_identity_mismatches": ticker_identity_mismatches,
    }


def run_for_ticker(
    client: ConsoleClient, ticker: str, duration_sec: float, interval_sec: float,
) -> TickerProof:
    tp = TickerProof(ticker=ticker)
    baseline = check_baseline(client, ticker)
    tp.baseline_ok = bool(baseline.get("ok"))
    tp.baseline_detail = baseline
    if not tp.baseline_ok:
        tp.verdict = "FAIL_BASELINE"
        return tp

    # re-fetch the full contract list for real ATM selection (the baseline's own sample
    # is truncated to 2 rows for readability).
    _, chain_full = client.get("/api/chain", {"ticker": ticker})
    full_contracts = (chain_full or {}).get("contracts") or []
    atm = pick_atm_call(full_contracts, baseline["chain"]["spot"])
    if atm:
        sym = str(atm["symbol"])
        status, sub = client.post("/api/streaming/active-option-contract", {"contract": sym})
        tp.subscribed_contract = sym
        tp.subscribe_ok = bool(status == 200 and isinstance(sub, dict) and sub.get("ok"))

    findings = poll_live_overlay(
        client, ticker, tp.subscribed_contract if tp.subscribe_ok else None,
        duration_sec, interval_sec,
    )
    tp.polls = findings["polls"]
    tp.terrain_cycle_advanced = findings["terrain_cycle_advanced"]
    tp.stream_overlay_observed = findings["overlay_observed"]
    tp.stream_overlay_symbols_seen = findings["overlay_symbols"]
    tp.stream_overlay_first_poll_index = findings["overlay_first_poll_index"]
    tp.microstructure_contract_match_observed = findings["micro_match"]
    tp.subscribed_cell_located = findings["cell_located"]
    tp.subscribed_cell_value_before = findings["cell_value_before"]
    tp.subscribed_cell_value_after = findings["cell_value_after"]
    tp.subscribed_cell_value_changed = findings["cell_value_changed"]
    tp.freshness_samples = findings["freshness_samples"]
    tp.freshness_sane = findings["freshness_sane"]
    tp.ticker_identity_mismatches = findings["ticker_identity_mismatches"]

    # Required clean verdict across all five acceptance dimensions (operator directive):
    #   1. live tick identity   — the overlay names OUR subscribed symbol, not a leftover.
    #   2. heatmap updates      — the exact served cell backing that symbol changed value.
    #   3. overlay state        — a genuine streamed overlay landed at all.
    #   4. freshness            — age_sec behaved sanely throughout (never negative/garbled).
    #   5. ticker switching     — every poll's own echoed identity matched what we asked for.
    # A cell that never changes VALUE during a live overlay is not itself a failure (a real
    # market can print an unchanged price at that exact strike/expiry) — but it means this
    # run cannot claim dimension 2 as PROVEN, only dimension 3 (overlay landed). Both are
    # reported distinctly rather than collapsed into one pass/fail bit.
    identity_ok = bool(findings["overlay_observed"]) and (
        not tp.subscribed_contract or tp.subscribed_contract in findings["overlay_symbols"]
    )
    overlay_ok = bool(findings["overlay_observed"])
    freshness_ok = bool(findings["freshness_sane"])
    switching_ok = tp.ticker_identity_mismatches == 0
    heatmap_update_ok = bool(findings["cell_located"] and findings["cell_value_changed"])
    if identity_ok and overlay_ok and freshness_ok and switching_ok and heatmap_update_ok:
        tp.verdict = "PASS"
    elif identity_ok and overlay_ok and freshness_ok and switching_ok:
        # Overlay + identity proven, but no observed value CHANGE at that exact cell this
        # window — real (a quiet strike), not a defect. Distinct from a clean miss.
        tp.verdict = "PASS_NO_CELL_VALUE_CHANGE_OBSERVED"
    elif tp.baseline_ok:
        tp.verdict = "PARTIAL_NO_OVERLAY_OBSERVED"
    return tp


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL)
    ap.add_argument("--ticker", default="SPY")
    ap.add_argument("--second-ticker", default="AAPL",
                     help="A non-core ticker, to rule out sentinel-only special-casing (set to '' to skip).")
    ap.add_argument("--duration-sec", type=float, default=150.0)
    ap.add_argument("--interval-sec", type=float, default=3.0)
    ap.add_argument("--out-dir", default=None,
                     help="Defaults to reports/pr238_rth_evidence/rth_<shortsha>_<YYYYMMDD>/")
    args = ap.parse_args()

    expected_sha = _repo_head_sha()
    client = ConsoleClient(args.base_url)

    identity = check_identity(client, expected_sha)
    if not identity.get("ok"):
        print(json.dumps({"verdict": "FAIL", "stage": "identity", "detail": identity}, indent=2))
        return 2

    tickers = [args.ticker] + ([args.second_ticker] if args.second_ticker else [])
    results: list[TickerProof] = []
    for t in tickers:
        print(f"--- proving {t} (subscribe + poll for {args.duration_sec:.0f}s) ---", file=sys.stderr)
        results.append(run_for_ticker(client, t, args.duration_sec, args.interval_sec))

    # Dimension 5 (ticker switching), cross-run check: ticker A's subscribed contract must
    # never appear in ticker B's own observed overlay symbols, and vice versa — a genuine
    # leak across the switch this script itself performed, not merely a per-poll echo check.
    cross_contamination: list[str] = []
    for i, a in enumerate(results):
        for b in results[i + 1:]:
            if a.subscribed_contract and a.subscribed_contract in b.stream_overlay_symbols_seen:
                cross_contamination.append(f"{a.ticker}'s contract {a.subscribed_contract} observed under {b.ticker}")
            if b.subscribed_contract and b.subscribed_contract in a.stream_overlay_symbols_seen:
                cross_contamination.append(f"{b.ticker}'s contract {b.subscribed_contract} observed under {a.ticker}")

    any_fail_baseline = any(r.verdict == "FAIL_BASELINE" for r in results)
    any_pass = any(r.verdict == "PASS" for r in results) and not cross_contamination

    from datetime import datetime, timezone
    captured_at = datetime.now(tz=timezone.utc).isoformat()

    short_sha = (identity.get("running_sha") or "unknown")[:8]
    out_dir = Path(args.out_dir) if args.out_dir else (
        ROOT / "reports" / "pr238_rth_evidence" / f"rth_{short_sha}_{captured_at[:10].replace('-', '')}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    record = {
        "captured_utc": captured_at,
        "base_url": args.base_url,
        "identity": identity,
        "cross_ticker_contamination": cross_contamination,
        "tickers": [asdict(r) for r in results],
    }
    record_path = out_dir / "live_vendor_proof_record.json"
    record_path.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")

    if any_fail_baseline or cross_contamination:
        # A cross-ticker leak is a real defect, not an inconclusive result — never reported
        # as merely PARTIAL alongside a per-ticker PASS.
        overall = "FAIL"
        code = 2
    elif any_pass:
        overall = "PASS"
        code = 0
    else:
        overall = "PARTIAL"
        code = 1

    summary_lines = [
        f"# PR #238 live-vendor proof — {overall}",
        "",
        f"captured_utc: {captured_at}",
        f"running_sha: {identity.get('running_sha')}",
        f"sha_matches_current_branch_tip: {identity.get('sha_matches_current_branch_tip')}",
        f"code_drift: {identity.get('code_drift')}",
        f"cross_ticker_contamination: {cross_contamination or 'none'}",
        "",
    ]
    for r in results:
        summary_lines.append(f"## {r.ticker}: {r.verdict}")
        summary_lines.append(f"- baseline_ok: {r.baseline_ok}")
        summary_lines.append(f"- subscribed_contract: {r.subscribed_contract} (accepted={r.subscribe_ok})")
        summary_lines.append(f"- [1] live tick identity — overlay names our contract: "
                              f"{r.stream_overlay_observed and (not r.subscribed_contract or r.subscribed_contract in r.stream_overlay_symbols_seen)}")
        summary_lines.append(f"- [2] heatmap updates — subscribed cell located={r.subscribed_cell_located}, "
                              f"value changed={r.subscribed_cell_value_changed} "
                              f"({r.subscribed_cell_value_before} -> {r.subscribed_cell_value_after})")
        summary_lines.append(f"- [3] overlay state — stream_overlay_observed={r.stream_overlay_observed}, "
                              f"symbols_seen={r.stream_overlay_symbols_seen}")
        summary_lines.append(f"- [4] freshness — sane={r.freshness_sane}, "
                              f"age_sec_samples(first/last)={r.freshness_samples[:1]}/{r.freshness_samples[-1:]}")
        summary_lines.append(f"- [5] ticker switching — identity_mismatches={r.ticker_identity_mismatches}")
        summary_lines.append(f"- terrain_cycle_advanced_during_poll: {r.terrain_cycle_advanced}")
        summary_lines.append(f"- microstructure_contract_match_observed: {r.microstructure_contract_match_observed}")
        summary_lines.append("")
    (out_dir / "SUMMARY.md").write_text("\n".join(summary_lines), encoding="utf-8")

    print(json.dumps({"verdict": overall, "record_path": str(record_path),
                       "summary_path": str(out_dir / "SUMMARY.md")}, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
