"""Simple, self-contained market-data API routes with no cross-tier coupling
(RC-REHAB-1, Phase 3): canonical 1m bars, the banked-chain forces (OI delta / DEX / charm)
panel, the fast spot-poll cache, and the batched watchlist-quotes endpoint. Every shared
dependency (get_db, is_trading_day_et, the live-1m-bar accumulator, the forces/spot-poll
cache dicts, the live-market-plane singleton) has other callers or sits alongside unrelated
shared infrastructure in server.py and stays there, imported back lazily.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time

from config import DEFAULT_TICKER
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from instrument_identity import ticker_storage_key

router = APIRouter()


@router.get("/api/bars1m")
def get_bars1m(ticker: str = Query(default=DEFAULT_TICKER),
               limit: int = Query(default=780, ge=1, le=3000)):
    """Canonical 1m bars, newest-last: [{t,o,h,l,c,v}] epoch-seconds bar starts."""
    # RC-REHAB-1 (route-extraction audit fix): `get_db` excluded from the eager
    # `from server import (...)` tuple -- see logger.py's identical fix comment. The
    # blanket import happens BEFORE the try/except below, so it would raise
    # ImportError (when `_HAS_SIGNALS` is False) before that try/except -- this
    # route's own designed "db unavailable" fallback -- ever runs. `import server as
    # _server` defers resolution to the point of use, already inside the try.
    import server as _server
    from server import _candles_1m

    tk = ticker_storage_key(ticker or DEFAULT_TICKER)   # RC-126: SPX -> $SPX etc., ONE authority
    import sqlite3 as _sq
    try:
        db = _server.get_db()
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
    # RC-REHAB-1 (route-extraction audit fix): `get_db` excluded from the eager
    # `from server import (...)` tuple -- see get_bars1m's identical fix comment
    # above for why the blanket import defeats this route's own try/except
    # DB-failure fallback below.
    import server as _server
    from server import _charm_book_scope, _FORCES_CACHE, is_trading_day_et

    tk = ticker_storage_key(ticker or DEFAULT_TICKER)
    now = time.time()
    hit = _FORCES_CACHE.get(tk)
    if hit and now - hit[0] < 300.0:
        return JSONResponse(hit[1])
    payload: dict = {"ticker": tk, "available": False,
                     "reason": "fewer than 2 banked wide captures for this ticker"}
    try:
        db = _server.get_db()
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


@router.get("/api/spot")
def get_spot(ticker: str = Query(default=DEFAULT_TICKER)):
    """Featherweight live spot for fast UI polling. The ONE price authority
    (resolve_spot, RC-14) behind a 1.25s per-ticker cache — no chain, no model
    stack, budget-bounded regardless of poll rate or viewer count.

    Concurrent cache misses single-flight: one Schwab quote; waiters join and
    reuse the TTL-fresh cached payload. Waiters never each call resolve_spot —
    on timeout they re-contend for leadership or serve the last cache entry
    (stale beats a quote stampede).
    """
    from server import (
        SPOT_POLL_TTL_SEC,
        _spot_poll_cache,
        _spot_poll_inflight,
        _spot_poll_lock,
        current_spot_state,
        resolve_spot,
    )

    tk = ticker_storage_key(ticker or DEFAULT_TICKER)   # RC-126: SPX -> $SPX etc., ONE authority
    deadline = time.time() + 10.0
    while True:
        now = time.time()
        with _spot_poll_lock:
            hit = _spot_poll_cache.get(tk)
            if hit and (now - hit[0]) < SPOT_POLL_TTL_SEC:
                return JSONResponse(hit[1])
            leader = tk not in _spot_poll_inflight
            if leader:
                _spot_poll_inflight[tk] = threading.Event()
            done = _spot_poll_inflight[tk]
        if not leader:
            remaining = deadline - time.time()
            if remaining <= 0:
                with _spot_poll_lock:
                    hit = _spot_poll_cache.get(tk)
                if hit:
                    return JSONResponse(hit[1])  # stale > stampede
                return JSONResponse(
                    {"ticker": tk, "spot": None, "spot_source": None,
                     "spot_as_of_ts_utc": None, "error": "spot_resolve_timeout"},
                    status_code=504,
                )
            done.wait(timeout=remaining)
            continue
        try:
            spot, source, ts = resolve_spot(tk)
            payload = {"ticker": tk, "spot": spot, "spot_source": source,
                       "spot_state": current_spot_state(source, tk),
                       "spot_as_of_ts_utc": ts}
            with _spot_poll_lock:
                _spot_poll_cache[tk] = (time.time(), payload)
            return JSONResponse(payload)
        finally:
            with _spot_poll_lock:
                _spot_poll_inflight.pop(tk, None)
            done.set()


#: No Schwab-documented batch-quote symbol ceiling exists anywhere in this repo (checked:
#: schwab_client.py, schwab_field_dictionary*, tools/sync_schwab_field_dictionary.py).
@router.get("/api/watchlist-quotes")
async def api_watchlist_quotes(tickers: str = Query(default="")):
    """
    ONE batched Schwab quote read (client.get_quotes) for every row of a client-held
    watchlist — not N sequential single-symbol polls, and not a second quote authority:
    parsing (_parse_quote_node_session_fields) and chg_pct precedence (resolve_chg_pct)
    are the exact same functions /api/fast-quote and /api/live/state use.

    No numeric ticker-count cap: no Schwab-documented batch-size ceiling exists anywhere in
    this repo to justify one (checked: schwab_client.py, schwab_field_dictionary*,
    tools/sync_schwab_field_dictionary.py), and a real operator watchlist is nowhere near
    any plausible vendor/transport limit — an invented number would be a product-shaped
    guess dressed as a constraint (caught in review). A genuinely oversized request fails
    honestly through the real failure paths below (ASGI/reverse-proxy URL-length rejection
    before this handler even runs, or a real vendor HTTP error reported as such) instead of
    a silently-guessed threshold.

    Returns {"ok": bool, "error": str|None, "quotes": {SYMBOL: {spot, spot_disp, chg_pct,
    exchange_quote_ts}}}. A symbol simply absent from `quotes` genuinely has no usable quote
    right now (never fabricated) — that is a DIFFERENT fact from ok:false, which means the
    WHOLE batch call failed (auth/vendor/transport) before any symbol could be evaluated.
    Collapsing both into the same bare {} (this route's pre-review shape) made a live
    console with zero current coverage indistinguishable from an offline one; the caller
    could not tell "no data for these symbols right now" from "the vendor call never ran".
    """
    from server import (
        SPOT_SOURCE_PLANE,
        SPOT_SOURCE_QUOTE,
        _get_quote_hot_executor,
        _lmp,
        _parse_quote_node_session_fields,
        _schwab_auth_http_unavailable,
        get_client,
        log,
    )

    raw = [t.strip().upper() for t in (tickers or "").split(",") if t.strip()]
    seen: list[str] = []
    for t in raw:
        if t not in seen:
            seen.append(t)
    if not seen:
        return JSONResponse({"ok": True, "error": None, "quotes": {}})

    def _build() -> dict:
        from market_context import resolve_chg_pct

        # Operator-reproduced defect (2026-09-14, spot 360 audit): this route called
        # schwab_client.safe_get_quotes directly — a RAW vendor call outside
        # _memoized_quote_response AND outside live_market_plane, the two places every other
        # spot consumer in this file converges through. The docstring's claim ("not a second
        # quote authority: parsing... are the exact same functions") was true for the PARSER,
        # not for the QUOTE ITSELF — the watchlist's SPY row and the Gamma Chart's SPY spot
        # could come from two genuinely different Schwab round-trips seconds apart. Every
        # ticker with a FRESH plane row now reuses it (zero extra vendor calls, and
        # guaranteed identical to what every other screen shows); only tickers the plane
        # cannot currently answer get a real vendor fetch, and that fetch is recorded back
        # into the plane so the next reader of that ticker — watchlist or otherwise — sees
        # the SAME value this one just fetched.
        out: dict = {}
        need_fetch: list[str] = []
        for t in seen:
            row = _lmp.get_quote(t)
            if row and _lmp.quote_is_fresh(row) and _lmp.plane_spot_is_last_price(row):
                out[t] = {
                    "spot": row["spot"],
                    "spot_disp": row.get("spot_disp") or f"{row['spot']:.2f}",
                    "spot_state": "live",
                    "spot_source": SPOT_SOURCE_PLANE,
                    "chg_pct": resolve_chg_pct(t, row.get("chg_pct")),
                    "exchange_quote_ts": row.get("exchange_quote_ts"),
                }
            else:
                need_fetch.append(t)
        if not need_fetch:
            return {"ok": True, "error": None, "quotes": out}

        try:
            client = get_client()
        except HTTPException as he:
            reason = "token_invalid" if _schwab_auth_http_unavailable(he) else "auth_unavailable"
            log.warning("watchlist_quotes auth unavailable tickers=%s reason=%s", need_fetch, reason)
            # Tickers the plane already answered are still real and still served — only the
            # ones that needed a vendor call are missing, exactly like the batch-partial
            # contract this route's own docstring already promises for a per-symbol miss.
            return {"ok": bool(out), "error": None if out else reason, "quotes": out}
        from schwab_client import safe_get_quotes

        try:
            resp = safe_get_quotes(client, need_fetch)
        except Exception as e:
            log.warning("watchlist_quotes batch fetch failed tickers=%s: %s", need_fetch, e)
            return {"ok": bool(out), "error": None if out else "vendor_call_failed", "quotes": out}
        if resp is None or getattr(resp, "status_code", None) != 200:
            status = getattr(resp, "status_code", None)
            log.warning("watchlist_quotes batch fetch non-200 tickers=%s status=%s", need_fetch, status)
            return {"ok": bool(out), "error": None if out else f"vendor_http_{status}", "quotes": out}
        try:
            q_json = resp.json()
        except Exception as e:
            log.warning("watchlist_quotes batch response unparseable tickers=%s: %s", need_fetch, e)
            return {"ok": bool(out), "error": None if out else "malformed_vendor_response", "quotes": out}
        server_received_ts = time.time()
        for t in need_fetch:
            node = q_json.get(t) or q_json.get(t.upper()) or {}
            if not node:
                continue
            pq = _parse_quote_node_session_fields(node)
            spot = pq.get("spot")
            if pq.get("spot_source") != "lastPrice" or spot is None:
                continue
            chg_pct = resolve_chg_pct(t, pq.get("chg_pct"))
            out[t] = {
                "spot": spot,
                "spot_disp": f"{spot:.2f}",
                "spot_state": "live",
                "spot_source": SPOT_SOURCE_QUOTE,
                "chg_pct": chg_pct,
                "exchange_quote_ts": pq.get("quote_ts"),
            }
            # Record into the plane so this fetch becomes the ONE answer every other
            # consumer (resolve_spot, the header, Tier C, L1) sees too, not a value only
            # this route ever knew about.
            _lmp.record_quote(t, {
                "ticker": t, "spot": float(spot), "spot_disp": f"{spot:.2f}",
                "chg_pct": chg_pct, "exchange_quote_ts": pq.get("quote_ts"),
                "quote_time_source": "schwab_rest_quote" if pq.get("quote_ts") is not None else "unavailable",
                "server_received_ts": server_received_ts,
                "quote_ingestion": "rest_watchlist_batch",
                "fast_generation_id": _lmp.next_fast_generation(t),
                "quote_source_detail": {
                    "spot": "LAST_PRICE",
                    "carried_forward": False,
                },
            })
        return {"ok": True, "error": None, "quotes": out}

    loop = asyncio.get_event_loop()
    payload = await loop.run_in_executor(_get_quote_hot_executor(), _build)
    return JSONResponse(payload)
