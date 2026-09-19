"""Desk (research/candidates/book) API routes.

RC-REHAB-1 (Phase 3): first extraction slice out of server.py's monolithic route table.
These six routes were chosen first because they are the file's cleanest boundary --
confirmed (by direct read of every handler body) to touch none of server.py's shared
mutable state (`_state_cache`, `_terrain_cache`, `_analytics_inflight`, the candle
accumulators, the executor pools): every handler is a thin adapter over `desk_store`,
shaping its return value into the response. The only two things they still need FROM
server.py -- `resolve_spot` and `APP_DIR` -- are imported lazily inside the function
bodies that need them (matching the pre-existing local-import convention already used
here for `desk_store`/`db.DB_PATH`), not at module load time, so this module can be
imported BY server.py (`app.include_router(...)`) without a circular import back to it.
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Query

from config import DEFAULT_TICKER
from instrument_identity import ticker_storage_key

router = APIRouter()


@router.get("/api/desk/radar")
def get_desk_radar(as_of: float = Query(default=0.0), limit: int = Query(default=60)):
    """Candidate structure as it stood at `as_of` (epoch seconds; 0 = now).

    The whole point of the parameter is that moving it BACKWARD must remove rows. Filtering
    happens on knowledge time inside `desk_store.radar_rows`, never on event time — see the
    module docstring for the six-day FINRA lag that makes the distinction load-bearing.
    """
    import desk_store
    from db import DB_PATH as _desk_db

    at = float(as_of) if as_of and as_of > 0 else time.time()
    try:
        payload = desk_store.radar_rows(_desk_db, at, limit=max(1, min(int(limit), 500)))
    except Exception as e:  # absence reaches the surface as absence, never as zeros
        return {"as_of_utc": at, "rows": [], "n_total": 0, "error": f"{type(e).__name__}: {e}"}
    payload["server_now_utc"] = time.time()
    payload["is_replay"] = bool(as_of and as_of > 0)
    return payload


@router.get("/api/desk/dossier")
def get_desk_dossier(ticker: str = Query(default=DEFAULT_TICKER),
                     as_of: float = Query(default=0.0)):
    """One name's measured structure, as it stood at `as_of`."""
    import desk_store
    from db import DB_PATH as _desk_db

    at = float(as_of) if as_of and as_of > 0 else time.time()
    tk = ticker_storage_key(ticker or DEFAULT_TICKER)
    try:
        payload = desk_store.dossier(_desk_db, tk, at)
    except Exception as e:
        return {"subject": tk, "as_of_utc": at, "error": f"{type(e).__name__}: {e}",
                "missing": ["request failed"]}
    payload["server_now_utc"] = time.time()
    payload["is_replay"] = bool(as_of and as_of > 0)
    return payload


@router.get("/api/desk/evidence")
def get_desk_evidence(as_of: float = Query(default=0.0)):
    """The study scoreboard, read from reports/ rather than retyped.

    RC-172: honours the replay clock. A scoreboard generated after the instant being replayed is
    refused with its reason — on a tab whose premise is judging a screen by what was knowable,
    the surface that adjudicates claims cannot be the one reading the future.
    """
    import desk_store
    from server import APP_DIR

    at = float(as_of) if as_of and as_of > 0 else time.time()
    try:
        return desk_store.evidence_rows(APP_DIR, at)
    except Exception as e:
        return {"rows": [], "empty_reason": f"{type(e).__name__}: {e}"}


@router.get("/api/desk/structure")
def get_desk_structure(
    ticker: str = Query(default=DEFAULT_TICKER),
    horizon_sessions: int = Query(default=5),
    long_strike: float = Query(default=0.0),
    short_strike: float = Query(default=0.0),
    long_price: float = Query(default=0.0),
    short_price: float = Query(default=0.0),
    contracts: int = Query(default=1),
    as_of: float = Query(default=0.0),
):
    """Deterministic payoff plus the PHYSICAL terminal distribution.

    The risk-neutral half is refused, not approximated — see `desk_store` for the reason, which
    is stated once so every surface refuses in the same words.
    """
    import desk_store
    from db import DB_PATH as _desk_db
    from server import resolve_spot

    at = float(as_of) if as_of and as_of > 0 else time.time()
    tk = ticker_storage_key(ticker or DEFAULT_TICKER)
    out: dict = {"subject": tk, "as_of_utc": at}
    try:
        # Live LAST_PRICE only when this is a current request. A historical as_of
        # keeps the as-of bar close and must not receive today's live print.
        live_spot = None
        if not (as_of and as_of > 0):
            live_spot, _, _ = resolve_spot(tk)
        out["distribution"] = desk_store.terminal_distribution(
            _desk_db, tk, at, horizon_sessions=max(1, min(int(horizon_sessions), 60)),
            spot=live_spot)
    except Exception as e:
        out["distribution"] = {"available": False, "reason": f"{type(e).__name__}: {e}"}
    if long_strike > 0 and short_strike > 0:
        try:
            payoff = desk_store.vertical_spread(
                long_strike, short_strike, long_price, short_price,
                contracts=max(1, int(contracts)))
            out["payoff"] = payoff
            out["pop"] = desk_store.probability_of_profit(
                out["distribution"], payoff["breakeven"])
        except desk_store.DeskFactError as e:
            out["payoff_error"] = str(e)
    out["server_now_utc"] = time.time()
    return out


@router.get("/api/desk/brief")
def get_desk_brief(as_of: float = Query(default=0.0)):
    """The newest research brief we held at `as_of`, blocks aged against that instant."""
    import desk_store
    from db import DB_PATH as _desk_db

    at = float(as_of) if as_of and as_of > 0 else time.time()
    try:
        brief = desk_store.latest_brief(_desk_db, at)
    except Exception as e:
        return {"brief": None, "empty_reason": f"{type(e).__name__}: {e}"}
    if brief is None:
        return {"brief": None, "as_of_utc": at, "empty_reason": (
            "no research brief has been ingested — the Brief is a publish target and nothing "
            "has published to it yet")}
    return {"brief": brief, "as_of_utc": at, "empty_reason": None}


@router.post("/api/desk/materialize")
def post_desk_materialize():
    """Rebuild the fact store from tables this repo already fills. Idempotent.

    RC-172: this was a GET. A GET that rewrites tens of thousands of rows against a 25 GB
    database is fired by anything that speculatively fetches a URL — a link prefetch, a crawler,
    a browser preconnect, an operator refreshing a saved tab — and this database already has an
    open root cause for write contention (RC-166). POST is the fix: the method now matches what
    the call actually does.
    """
    import desk_store
    from db import DB_PATH as _desk_db

    t0 = time.time()
    try:
        res = desk_store.materialize_all(_desk_db)
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    return {"ok": True, "elapsed_sec": round(time.time() - t0, 2), "counts": res}
