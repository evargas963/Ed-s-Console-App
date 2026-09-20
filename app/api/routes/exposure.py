"""/api/exposure/* API routes: intraday flow frames, per-strike call/put book split, and
multi-day history (RC-REHAB-1, Phase 3). Each route's own 5/10-minute cache dict
(_EXPOSURE_FLOW_CACHE / _EXPOSURE_BOOK_CACHE / _EXPOSURE_HISTORY_CACHE) is private to that
one route (no other server.py code touches it) but stays in server.py alongside every other
shared dependency here, per the established pattern, and is imported back lazily.
"""

from __future__ import annotations

import json
import time

from config import DEFAULT_TICKER
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from instrument_identity import ticker_storage_key

router = APIRouter()


@router.get("/api/exposure/flow")
def get_exposure_flow(ticker: str = Query(default=DEFAULT_TICKER)):
    """RC-208: serve option_chain_accrual frames for the latest banked session so the
    Exposure tab paints per-minute Pika/Barney structure, the intraday King path, and
    volume-delta bubbles at the minute they happened. per_strike_json served verbatim
    ([[strike, gex_dollars, session_volume], ...]; MEASURED: SPY 07-31 = 133 frames, ET
    minutes 556-975), spot-windowed ±5%. 5-min cache like /api/forces."""
    import sqlite3 as _sq

    # RC-REHAB-1 (route-extraction audit fix): `get_db` excluded from the eager
    # `from server import (...)` tuple -- see logger.py's identical fix comment. The
    # blanket import sits BEFORE the try/except below, so it would raise ImportError
    # (when `_HAS_SIGNALS` is False) before that try/except -- this route's own
    # designed fallback for a DB failure -- ever runs. `import server as _server`
    # defers resolution to the point of use, already inside the try.
    import server as _server
    from server import _EXPOSURE_FLOW_CACHE

    tk = ticker_storage_key(ticker or DEFAULT_TICKER)
    now = time.time()
    hit = _EXPOSURE_FLOW_CACHE.get(tk)
    if hit and now - hit[0] < 300.0:
        return JSONResponse(hit[1])
    payload: dict = {"ticker": tk, "available": False,
                     "reason": "no banked accrual frames for this ticker"}
    try:
        db = _server.get_db()
        frames: list[dict] = []
        latest = None
        con = _sq.connect(f"file:{db.db_path}?mode=ro", uri=True, timeout=10.0)
        try:
            latest = con.execute(
                "SELECT MAX(et_date) FROM option_chain_accrual WHERE ticker=?", (tk,),
            ).fetchone()
            if latest and latest[0]:
                for ts, m, spot, psj in con.execute(
                        "SELECT ts_utc, et_minute, spot, per_strike_json "
                        "FROM option_chain_accrual WHERE ticker=? AND et_date=? "
                        "ORDER BY ts_utc", (tk, latest[0])):
                    try:
                        rows2 = json.loads(psj)
                    except (ValueError, TypeError):
                        continue
                    sp = float(spot) if spot is not None else None
                    if sp:
                        rows2 = [r for r in rows2 if abs(float(r[0]) - sp) <= sp * 0.05]
                    frames.append({"t": int(float(ts) // 60) * 60, "m": int(m),
                                   "spot": sp, "rows": rows2})
        finally:
            con.close()
        if frames:
            payload = {"ticker": tk, "available": True, "et_date": latest[0],
                       "n_frames": len(frames), "frames": frames,
                       "method": ("option_chain_accrual per_strike_json verbatim "
                                  "[[strike, gex_dollars, session_volume]...], "
                                  "spot-windowed ±5%, latest banked session")}
    except Exception as e:
        payload = {"ticker": tk, "available": False, "reason": f"flow read failed: {e}"}
    _EXPOSURE_FLOW_CACHE[tk] = (now, payload)
    return JSONResponse(payload)


@router.get("/api/exposure/book")
def get_exposure_book(ticker: str = Query(default=DEFAULT_TICKER)):
    """RC-209: per-strike call/put GEX split + net DEX + volumes from the NEWEST banked wide
    chain — turns the Exposure tab's Split·DEX pill live. Vendor convention researched this
    turn (FlashAlpha): green = call side, red = put side. 5-min cache."""
    import sqlite3 as _sq

    from math_exposure_core import compute_exposures_by_strike as _cebs
    # RC-REHAB-1 (route-extraction audit fix): `get_db` excluded from the eager
    # `from server import (...)` tuple -- see get_exposure_flow's identical fix
    # comment above for why the blanket import defeats this route's own try/except
    # DB-failure fallback below.
    import server as _server
    from server import _EXPOSURE_BOOK_CACHE, is_trading_day_et

    tk = ticker_storage_key(ticker or DEFAULT_TICKER)
    now = time.time()
    hit = _EXPOSURE_BOOK_CACHE.get(tk)
    if hit and now - hit[0] < 300.0:
        return JSONResponse(hit[1])
    payload: dict = {"ticker": tk, "available": False, "reason": "no banked wide chain"}
    try:
        db = _server.get_db()
        con = _sq.connect(f"file:{db.db_path}?mode=ro", uri=True, timeout=10.0)
        try:
            cand = con.execute(
                "SELECT et_date, spot, chain_json FROM option_chain_morning_full "
                "WHERE ticker=? ORDER BY et_date DESC LIMIT 12", (tk,)).fetchall()
        finally:
            con.close()
        rows_t = [r for r in cand if r[0] and is_trading_day_et(str(r[0]))][:1]
        if rows_t:
            d1, s1, c1 = rows_t[0]
            spot1 = float(s1)
            per, _diag = _cebs(json.loads(c1), spot=spot1)

            def _f(v: dict, k: str) -> float:
                x = v.get(k)
                return float(x) if x is not None else 0.0

            out_rows = [
                [k, round(_f(v, "call_gex_1pct")), round(_f(v, "put_gex_1pct")),
                 round(_f(v, "net_dex_dollars")),
                 round(_f(v, "call_volume")), round(_f(v, "put_volume"))]
                for k, v in sorted(per.items())
                if abs(float(k) - spot1) <= spot1 * 0.05
            ]
            payload = {"ticker": tk, "available": True, "et_date": d1, "spot": spot1,
                       "rows": out_rows,
                       "method": ("newest banked wide chain -> compute_exposures_by_strike; "
                                  "[strike, call_gex_1pct, put_gex_1pct, net_dex_dollars, "
                                  "call_volume, put_volume], ±5% spot window")}
    except Exception as e:
        payload = {"ticker": tk, "available": False, "reason": f"book read failed: {e}"}
    _EXPOSURE_BOOK_CACHE[tk] = (now, payload)
    return JSONResponse(payload)


@router.get("/api/exposure/history")
def get_exposure_history(ticker: str = Query(default=DEFAULT_TICKER)):
    """RC-209 (operator: multi-day scroll-back goes live): per-day per-strike net GEX$ for
    EVERY banked session, so scrolled-back days paint THEIR OWN structure under their own
    candles. ±5% of each day's spot; 10-min cache (the bank changes nightly)."""
    import sqlite3 as _sq

    from math_exposure_core import compute_exposures_by_strike as _cebs
    # RC-REHAB-1 (route-extraction audit fix): `get_db` excluded from the eager
    # `from server import (...)` tuple -- see get_exposure_flow's identical fix
    # comment above for why the blanket import defeats this route's own try/except
    # DB-failure fallback below.
    import server as _server
    from server import _EXPOSURE_HISTORY_CACHE, is_trading_day_et

    tk = ticker_storage_key(ticker or DEFAULT_TICKER)
    now = time.time()
    hit = _EXPOSURE_HISTORY_CACHE.get(tk)
    if hit and now - hit[0] < 600.0:
        return JSONResponse(hit[1])
    payload: dict = {"ticker": tk, "available": False, "reason": "no banked sessions"}
    try:
        db = _server.get_db()
        con = _sq.connect(f"file:{db.db_path}?mode=ro", uri=True, timeout=10.0)
        try:
            cand = con.execute(
                "SELECT et_date, spot, chain_json FROM option_chain_morning_full "
                "WHERE ticker=? ORDER BY et_date", (tk,)).fetchall()
        finally:
            con.close()
        days = []
        for d0, s0, c0 in cand:
            if not d0 or not is_trading_day_et(str(d0)):
                continue
            sp = float(s0)
            per, _diag = _cebs(json.loads(c0), spot=sp)
            rws = []
            for k, v in sorted(per.items()):
                if abs(float(k) - sp) > sp * 0.05:
                    continue
                x = v.get("net_gex_1pct")
                rws.append([k, round(float(x) if x is not None else 0.0)])
            if rws:
                days.append({"date": d0, "spot": sp, "rows": rws})
        if days:
            payload = {"ticker": tk, "available": True, "n_days": len(days), "days": days,
                       "method": ("every banked session -> compute_exposures_by_strike "
                                  "net_gex_1pct per strike, ±5% of that day's spot")}
    except Exception as e:
        payload = {"ticker": tk, "available": False, "reason": f"history read failed: {e}"}
    _EXPOSURE_HISTORY_CACHE[tk] = (now, payload)
    return JSONResponse(payload)
