"""Simple, self-contained market-data API routes with no cross-tier coupling
(RC-REHAB-1, Phase 3): canonical 1m bars and the banked-chain forces (OI delta / DEX / charm)
panel. Every shared dependency (get_db, is_trading_day_et, the live-1m-bar accumulator, the
forces cache dict, the charm-book-scope helper) has other callers or sits alongside
unrelated shared infrastructure in server.py and stays there, imported back lazily.
"""

from __future__ import annotations

import json
import time

from config import DEFAULT_TICKER
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from instrument_identity import ticker_storage_key

router = APIRouter()


@router.get("/api/bars1m")
def get_bars1m(ticker: str = Query(default=DEFAULT_TICKER),
               limit: int = Query(default=780, ge=1, le=3000)):
    """Canonical 1m bars, newest-last: [{t,o,h,l,c,v}] epoch-seconds bar starts."""
    from server import _candles_1m, get_db

    tk = ticker_storage_key(ticker or DEFAULT_TICKER)   # RC-126: SPX -> $SPX etc., ONE authority
    import sqlite3 as _sq
    try:
        db = get_db()
    except Exception:
        return JSONResponse({"ticker": tk, "bars": [], "error": "db unavailable"})
    con = _sq.connect(f"file:{db.db_path}?mode=ro", uri=True, timeout=10.0)
    try:
        rows = con.execute(
            "SELECT bar_start_ts_utc, open, high, low, close, volume FROM price_bars_1m "
            "WHERE ticker=? ORDER BY bar_start_ts_utc DESC LIMIT ?", (tk, int(limit)),
        ).fetchall()
    finally:
        con.close()
    bars = [{"t": r[0], "o": r[1], "h": r[2], "l": r[3], "c": r[4], "v": r[5]}
            for r in reversed(rows)]
    if not bars:
        # RC-484 (2026-08-25): a PREVIEWED (typed-in, not enrolled) ticker banks no
        # price_bars_1m — RC-69 made _bars_loop the only banked writer and it serves
        # enrolled tickers only — so its chart stayed empty all session (measured:
        # CRWV 2026-08-13, 127 snapshots, 0 bars). Fall through to the live
        # accumulator's COMPLETED bars, read-only and clearly tagged: display feed,
        # not a second banked producer (nothing is written).
        try:
            acc = _candles_1m.get_bars(tk)
        except Exception:
            acc = []
        bars = [{"t": float(b.ts), "o": float(b.open), "h": float(b.high),
                 "l": float(b.low), "c": float(b.close),
                 "v": (float(b.volume) if getattr(b, "volume", None) is not None else None)}
                for b in list(acc)[-int(limit):]]
        if bars:
            return JSONResponse({"ticker": tk, "bars": bars, "n": len(bars),
                                 "source": "live_accumulator_unbanked"})
    return JSONResponse({"ticker": tk, "bars": bars, "n": len(bars)})


@router.get("/api/forces")
def get_forces(ticker: str = Query(default=DEFAULT_TICKER)):
    """Forces rows from banked chains (RC-192/RC-199): per-strike OI delta FIRST, then
    bucketed by the NEWER capture's spot — bucketing each day by its own spot lets the moving
    boundary masquerade as OI change (measured inversion, OPEN_ITEMS DIR-01 method note).
    DEX is the newer capture's net_dex_dollars side sums. CHARM side sums (RC-199): operator
    2026-08-02 revoked the DIR-01(i) vote-lock — serve dealer-signed net_charm below/above
    spot from the newer banked chain via compute_charm_by_strike (same book as terrain walls).
    """
    import sqlite3 as _sq

    from math_exposure_core import compute_exposures_by_strike as _cebs
    from math_levels import compute_charm_by_strike as _ccs
    from server import _charm_book_scope, _FORCES_CACHE, get_db, is_trading_day_et

    tk = ticker_storage_key(ticker or DEFAULT_TICKER)
    now = time.time()
    hit = _FORCES_CACHE.get(tk)
    if hit and now - hit[0] < 300.0:
        return JSONResponse(hit[1])
    payload: dict = {"ticker": tk, "available": False,
                     "reason": "fewer than 2 banked wide captures for this ticker"}
    try:
        db = get_db()
        con = _sq.connect(f"file:{db.db_path}?mode=ro", uri=True, timeout=10.0)
        try:
            # RC-193: pull a wider candidate window and keep only trading ET dates —
            # ORDER BY et_date DESC LIMIT 2 silently preferred Sunday stock.
            cand = con.execute(
                "SELECT et_date, spot, chain_json FROM option_chain_morning_full "
                "WHERE ticker=? ORDER BY et_date DESC LIMIT 12", (tk,)).fetchall()
        finally:
            con.close()
        rows = [r for r in cand if r[0] and is_trading_day_et(str(r[0]))][:2]
        if len(rows) >= 2:
            (d1, s1, c1), (d0, s0, c0) = rows[0], rows[1]
            per1 = _cebs(json.loads(c1), spot=float(s1))[0]
            per0 = _cebs(json.loads(c0), spot=float(s0))[0]

            def _g(v: dict, k: str) -> float:
                x = v.get(k)
                return float(x) if x is not None else 0.0

            oi1 = {k: _g(v, "call_oi") + _g(v, "put_oi") for k, v in per1.items()}
            oi0 = {k: _g(v, "call_oi") + _g(v, "put_oi") for k, v in per0.items()}
            spot1 = float(s1)
            # RC-199: CHARM below/above from the NEWER banked wide chain (full book).
            # Dealer-signed net_charm = call_charm - put_charm per strike (RC-179).
            charm_below = charm_above = None
            charm_err = None
            try:
                chain1 = json.loads(c1)
                contracts = chain1 if isinstance(chain1, list) else (
                    (chain1.get("contracts") if isinstance(chain1, dict) else None) or [])
                per_ch = _ccs(contracts, spot1) if contracts else {}
                if not per_ch:
                    charm_err = "charm_by_strike empty on newer banked chain"
                else:
                    # RC-276: a strike with no net_charm is not a strike with zero charm.
                    # Summed as 0.0 it silently tilted the below/above pair the Exposure tab
                    # renders as dealer charm pressure.
                    from numeric_contract import float_finite_or_none as _fin_ch

                    def _ch(v: dict) -> float | None:
                        return _fin_ch(v.get("net_charm"))

                    charm_below = round(sum(
                        c for c in (_ch(v) for k, v in per_ch.items() if k < spot1)
                        if c is not None), 4)
                    charm_above = round(sum(
                        c for c in (_ch(v) for k, v in per_ch.items() if k > spot1)
                        if c is not None), 4)
            except Exception as _ce:
                charm_err = str(_ce)[:120]
            payload = {
                "ticker": tk, "available": True,
                "doi_below": round(sum(oi1[k] - oi0.get(k, 0.0) for k in oi1 if k < spot1)),
                "doi_above": round(sum(oi1[k] - oi0.get(k, 0.0) for k in oi1 if k > spot1)),
                "dex_below_dollars": round(sum(
                    _g(v, "net_dex_dollars") for k, v in per1.items() if k < spot1)),
                "dex_above_dollars": round(sum(
                    _g(v, "net_dex_dollars") for k, v in per1.items() if k > spot1)),
                "charm_below": charm_below,
                "charm_above": charm_above,
                # RC-288: DERIVED from the chain actually summed, not asserted. This was the
                # string literal "full_chain_banked", and static/exposure.html hardcodes the
                # same literal as its fallback — a label identical on both sides of the wire
                # can never disagree with itself, so it could not detect the one thing it
                # exists for. It matters because the repo computes charm two ways:
                # compute_net_charm on ONE selected expiry, compute_charm_by_strike on the
                # whole book. Counting the distinct expiries in `contracts` reports which
                # book these numbers came from and changes if the producer ever changes.
                "charm_book_scope": _charm_book_scope(contracts),
                "charm_error": charm_err,
                "newer_et_date": d1, "older_et_date": d0, "bucket_spot": spot1,
                "method": ("per-strike OI delta first, bucketed by the newer capture's spot; "
                           "DEX = net_dex_dollars side sums on the newer capture; "
                           "CHARM = dealer-signed net_charm side sums on the newer capture"),
            }
    except Exception as e:
        payload = {"ticker": tk, "available": False, "reason": f"forces read failed: {e}"}
    _FORCES_CACHE[tk] = (now, payload)
    return JSONResponse(payload)
