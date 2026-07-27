"""Measure the REAL Schwab strikeCount ceiling and the chain's TRUE depth (RC-60).

WHY: TERRAIN_STRIKE_COUNT_MAX is 100 because Schwab returned HTTP 502 at strikeCount=200 on
2026-07-20 and 100 was observed working the same session. Nothing between 100 and 200 was ever
tried, so the ceiling is an ASSUMPTION, not a measurement — and $SPX needs ~180 strikes to cover
the +/-5% span, so it is currently truncated and self-reports LOW_CONFIDENCE_NARROW_CHAIN. If the
real ceiling is 150 or 180, SPX becomes trustworthy for free.

Separately: `required_strike_count` computes what we NEED; it never asks what Schwab HAS. This
probe reports both, so the gap between requirement, request, and delivered depth is visible
instead of assumed.

Read-only: issues option-chain GETs and writes nothing. Requires live Schwab credentials, so it
runs on the operator's host.

Usage:  python tools/probe_chain_depth_v1.py [TICKER ...]      (default: SPY $SPX QQQ IWM)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

#: Ascending ladder. Starts BELOW the old assumed ceiling because MEASURED 2026-07-26 $SPX
#: returned HTTP 502 at 100 — a ticker can fail outright, so the ladder must find its floor too,
#: not just probe upward from an assumption. Climbing stops at the first refusal.
LADDER = (20, 40, 60, 80, 100, 120, 150, 180, 200, 250)
DEFAULT_TICKERS = ("SPY", "$SPX", "QQQ", "IWM")


def probe_one(client, ticker: str, count: int) -> dict:
    """One chain request at `count`. Returns status + DELIVERED depth (never raises)."""
    from schwab_client import safe_get_chain
    out: dict = {"strike_count_requested": count}
    try:
        resp = safe_get_chain(client, ticker, strike_count=count)
    except Exception as e:                      # vendor/transport failure IS the measurement
        out["status"] = f"exception:{type(e).__name__}"
        out["error"] = str(e)[:200]
        return out
    status = getattr(resp, "status_code", None)
    out["status"] = status
    if resp is None or status != 200:
        return out
    try:
        payload = resp.json()
    except Exception as e:
        out["status"] = f"badjson:{type(e).__name__}"
        out["error"] = str(e)[:200]
        return out
    strikes: set[float] = set()
    expiries: set[str] = set()
    n = 0
    for side in ("callExpDateMap", "putExpDateMap"):
        for exp_key, strike_map in (payload.get(side) or {}).items():
            expiries.add(str(exp_key))
            for sk, entries in (strike_map or {}).items():
                try:
                    strikes.add(float(sk))
                except (TypeError, ValueError):
                    continue
                n += len(entries or [])
    spot = payload.get("underlyingPrice")
    out.update({
        "contracts": n,
        "distinct_strikes": len(strikes),
        "distinct_expiries": len(expiries),
        "underlying_price": spot,
    })
    if strikes and spot:
        lo, hi = min(strikes), max(strikes)
        out["strike_low"] = lo
        out["strike_high"] = hi
        # The number that matters: does the DELIVERED chain actually span +/-5% of spot?
        out["span_below_pct"] = round((float(spot) - lo) / float(spot) * 100.0, 2)
        out["span_above_pct"] = round((hi - float(spot)) / float(spot) * 100.0, 2)
    return out


def probe_ticker(client, ticker: str) -> dict:
    """Climb the ladder until the vendor refuses; report the highest width that WORKED."""
    rows = []
    for count in LADDER:
        r = probe_one(client, ticker, count)
        rows.append(r)
        print(f"  {ticker:6s} strikeCount={count:4d} -> status={r.get('status')} "
              f"strikes={r.get('distinct_strikes')} span=-{r.get('span_below_pct')}%/"
              f"+{r.get('span_above_pct')}%", flush=True)
        if r.get("status") != 200:
            break                                # ceiling found; no point climbing further
    ok = [r for r in rows if r.get("status") == 200]
    best = ok[-1] if ok else None
    out: dict = {
        "ticker": ticker,
        "ladder": rows,
        "max_working_strike_count": best.get("strike_count_requested") if best else None,
    }
    if best:
        # Does the widest DELIVERED chain actually cover the +/-5% span the flip requires?
        out["delivered_span_pct"] = {"below": best.get("span_below_pct"),
                                     "above": best.get("span_above_pct")}
        out["covers_5pct_span"] = bool(
            (best.get("span_below_pct") or 0) >= 5.0 and (best.get("span_above_pct") or 0) >= 5.0
        )
    return out


def build_client():
    """Build a Schwab client WITHOUT importing server.py.

    `get_client` lives in server.py (server.py:274), and importing server drags in the whole
    app (schema init, thread pools, lifespan wiring) for a read-only probe. server.get_client
    is itself a thin cache over schwab_client.build_client_from_token, so the probe calls that
    same authority directly with the same config source.
    """
    from config import build_config
    from schwab_client import build_client_from_token

    cfg = build_config(_ROOT)          # same APP_DIR the server passes (server.py:223)
    state = build_client_from_token(
        api_key=cfg.api_key,
        app_secret=cfg.app_secret,
        token_path=cfg.token_path,
    )
    if not state.ok or state.client is None:
        raise SystemExit(f"[ABORT] Schwab auth failed: {state.message}")
    return state.client


def main(tickers: list[str]) -> int:
    client = build_client()
    print(f"Probing Schwab strikeCount ladder {LADDER} — read-only, writes nothing.\n", flush=True)
    results = [probe_ticker(client, t) for t in tickers]
    print("\n=== SUMMARY: max working strikeCount per ticker ===")
    for r in results:
        print(f"  {r['ticker']:6s} max_working={r['max_working_strike_count']} "
              f"delivered_span={r.get('delivered_span_pct')}")
    print("\nRaw:")
    print(json.dumps(results, indent=2, default=str))
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sys.exit(main(args or list(DEFAULT_TICKERS)))
