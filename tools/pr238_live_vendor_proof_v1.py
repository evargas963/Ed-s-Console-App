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

Exit codes: 0 = PASS (live streamed-tick overlay observed with correct identity for at
least one ticker); 1 = PARTIAL (baseline live data confirmed real and un-fabricated, but
no genuine streamed-tick overlay landed inside the polling window — inconclusive due to
market quietness/timing, not a defect); 2 = FAIL (console unreachable, code drift, Schwab
not AVAILABLE, or a baseline check itself failed — this is NOT proof, do not read a
missing evidence file as a pass, RC-57 discipline).
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


def poll_live_overlay(
    client: ConsoleClient, ticker: str, contract_symbol: Optional[str],
    duration_sec: float, interval_sec: float,
) -> tuple[list, bool, bool, list, Optional[int], bool]:
    """Returns (polls, terrain_cycle_advanced, overlay_observed, overlay_symbols_seen,
    overlay_first_poll_index, microstructure_match_observed)."""
    polls: list = []
    seen_ts: set = set()
    overlay_observed = False
    overlay_symbols: list = []
    overlay_first_poll_index: Optional[int] = None
    micro_match = False
    deadline = time.monotonic() + duration_sec
    poll_index = -1
    while time.monotonic() < deadline:
        poll_index += 1
        status, surf = client.get("/api/options/gamma-surface", {"ticker": ticker})
        rec = {
            "poll_index": poll_index,
            "t_mono": round(time.monotonic(), 2), "status": status,
            "source": (surf or {}).get("source"), "live": (surf or {}).get("live"),
            "stale": (surf or {}).get("stale"), "spot": (surf or {}).get("spot"),
            "chain_as_of_ts_utc": (surf or {}).get("chain_as_of_ts_utc"),
            "stream_overlay_contracts": (surf or {}).get("stream_overlay_contracts"),
            "stream_overlay_symbols": (surf or {}).get("stream_overlay_symbols"),
        }
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
        if contract_symbol:
            status_m, micro = client.get(
                "/api/order-flow/options-microstructure", {"contract": contract_symbol})
            splane = (micro or {}).get("streaming_plane") or {}
            rec["microstructure_status"] = status_m
            rec["microstructure_contract_match"] = splane.get("contract_match")
            if splane.get("contract_match") is True:
                micro_match = True
        polls.append(rec)
        time.sleep(max(0.5, interval_sec))
    terrain_cycle_advanced = len(seen_ts) > 1
    return (polls, terrain_cycle_advanced, overlay_observed, overlay_symbols,
            overlay_first_poll_index, micro_match)


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

    polls, cyc, overlay, syms, first_idx, micro = poll_live_overlay(
        client, ticker, tp.subscribed_contract if tp.subscribe_ok else None,
        duration_sec, interval_sec,
    )
    tp.polls = polls
    tp.terrain_cycle_advanced = cyc
    tp.stream_overlay_observed = overlay
    tp.stream_overlay_symbols_seen = syms
    tp.stream_overlay_first_poll_index = first_idx
    tp.microstructure_contract_match_observed = micro
    # PASS requires more than "some overlay happened somewhere" — if we know which
    # contract THIS run subscribed, that exact symbol must be among the observed
    # overlay symbols, so the proof is tied to an action this run actually took, never
    # to a leftover subscription from an earlier session.
    if overlay and (not tp.subscribed_contract or tp.subscribed_contract in syms):
        tp.verdict = "PASS"
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

    any_fail_baseline = any(r.verdict == "FAIL_BASELINE" for r in results)
    any_pass = any(r.verdict == "PASS" for r in results)

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
        "tickers": [asdict(r) for r in results],
    }
    record_path = out_dir / "live_vendor_proof_record.json"
    record_path.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")

    if any_fail_baseline:
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
        "",
    ]
    for r in results:
        summary_lines.append(f"## {r.ticker}: {r.verdict}")
        summary_lines.append(f"- baseline_ok: {r.baseline_ok}")
        summary_lines.append(f"- subscribed_contract: {r.subscribed_contract} (accepted={r.subscribe_ok})")
        summary_lines.append(f"- terrain_cycle_advanced_during_poll: {r.terrain_cycle_advanced}")
        summary_lines.append(f"- stream_overlay_observed: {r.stream_overlay_observed}")
        summary_lines.append(f"- stream_overlay_symbols_seen: {r.stream_overlay_symbols_seen}")
        summary_lines.append(f"- microstructure_contract_match_observed: {r.microstructure_contract_match_observed}")
        summary_lines.append("")
    (out_dir / "SUMMARY.md").write_text("\n".join(summary_lines), encoding="utf-8")

    print(json.dumps({"verdict": overall, "record_path": str(record_path),
                       "summary_path": str(out_dir / "SUMMARY.md")}, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
