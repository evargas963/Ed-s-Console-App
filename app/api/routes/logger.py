"""Background logger / watchlist management API routes (RC-REHAB-1, Phase 3)."""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from instrument_identity import ticker_storage_key

router = APIRouter()


@router.get("/api/logger/status")
def logger_status():
    """Return background logger status — which tickers are being logged and their stats."""
    # RC-REHAB-1 (route-extraction audit fix): `get_db` is deliberately NOT in this
    # `from server import (...)` tuple. `get_db` is only bound in server's module
    # namespace when the `db` import succeeded at server.py's own top-level load
    # (_HAS_SIGNALS gates on exactly that). A blanket `from server import (..., get_db)`
    # eagerly resolves EVERY listed name at function-entry, so if `_HAS_SIGNALS` is
    # False, that import statement itself raises ImportError before the `if
    # _HAS_SIGNALS:` guards below ever run -- making those guards dead code for this
    # exact failure mode. `import server as _server` defers `get_db`'s resolution to an
    # attribute access inside the already-`if _HAS_SIGNALS:`-guarded block, where it is
    # only ever touched once we know it exists.
    import server as _server
    from server import (
        _HAS_SIGNALS,
        _is_loggable_session,
        _logger_lock,
        _logger_stats,
        _logger_tickers,
        _logger_running,
        _user_persisted_enrollment_policy,
        CORE_TICKERS,
        LOG_INTERVAL,
        LOGGER_BUFFER_MINS,
        MAX_PINNED_LOGGING_TICKERS,
        MAX_USER_PERSISTED_LOGGING_TICKERS,
        PRE_MARKET_MINS,
        RTH_ONLY,
        STAGGER_SECS,
        log,
    )

    with _logger_lock:
        tickers = list(_logger_tickers)
        stats   = dict(_logger_stats)
        running = _logger_running

    db_rows: dict[str, dict] = {}
    if _HAS_SIGNALS:
        try:
            for row in _server.get_db().logging_universe_list_rows():
                db_rows[ticker_storage_key(row.get("ticker"))] = row  # RC-345/F25: canonical join key
        except Exception as e:
            log.debug("logger_status DB join: %s", e)

    now = time.time()
    result = []
    for t in tickers:
        s = stats.get(t, {})
        last_logged = s.get("last_logged")
        dbr = db_rows.get(t, {})
        enroll = dbr.get("enrollment_source") or ("core_bootstrap" if t in CORE_TICKERS else None)
        result.append({
            "ticker":       t,
            "core":         t in CORE_TICKERS,
            "category":     dbr.get("category") or ("core" if t in CORE_TICKERS else "unknown"),
            "enrollment_source": enroll,
            "enrolled_ts_utc": dbr.get("enrolled_ts_utc"),
            "last_seen_ts_utc": dbr.get("last_seen_ts_utc"),
            "last_background_log_ts_utc": dbr.get("last_background_log_ts_utc"),
            "count":        s.get("count", 0),
            "last_logged":  last_logged,
            "secs_ago":     round(now - last_logged, 0) if last_logged else None,
            "last_error":   s.get("last_error"),
            "source":       s.get("source", "—"),
            "eligible_background_log": _is_loggable_session(),
        })

    orphan_tickers: list[str] = []
    if _HAS_SIGNALS:
        try:
            orphan_tickers = _server.get_db().logging_universe_snapshot_ticker_orphans()
        except Exception as e:
            log.debug("logger_status orphan scan: %s", e)

    return JSONResponse({
        "running":       running,
        "interval_secs": LOG_INTERVAL,
        "stagger_secs":  STAGGER_SECS,
        "rth_only":      RTH_ONLY,
        "session_gate":  {
            "premarket_start_et_minute": PRE_MARKET_MINS,
            "buffer_end_et_minute": LOGGER_BUFFER_MINS,
            "loggable_now": _is_loggable_session(),
        },
        "max_user_persisted_symbols": MAX_USER_PERSISTED_LOGGING_TICKERS,
        "user_persisted_enrollment_policy": _user_persisted_enrollment_policy(),
        "max_pinned_symbols": MAX_PINNED_LOGGING_TICKERS,
        "core_tickers":  CORE_TICKERS,
        "tickers":       result,
        "snapshot_tickers_orphaned_from_logging_universe": orphan_tickers,
        "snapshot_orphan_count": len(orphan_tickers),
    })


@router.get("/api/logger/universe")
def logger_universe():
    """Issue 22 hardened — auditable logging_universe with eviction_status per row."""
    # RC-REHAB-1 (route-extraction audit fix): `get_db` excluded from the eager
    # `from server import (...)` tuple -- see logger_status's identical fix comment
    # above for why. Resolved via `_server.get_db()` only after the `_HAS_SIGNALS`
    # guard below has already passed.
    import server as _server
    from server import (
        _HAS_SIGNALS,
        _is_loggable_session,
        _logger_lock,
        _logger_tickers,
        _user_persisted_enrollment_policy,
        CORE_TICKERS,
        LOGGER_BUFFER_MINS,
        MAX_PINNED_LOGGING_TICKERS,
        MAX_USER_PERSISTED_LOGGING_TICKERS,
        PRE_MARKET_MINS,
        RTH_ONLY,
    )

    if not _HAS_SIGNALS:
        raise HTTPException(status_code=503, detail="database logging not available")
    try:
        db = _server.get_db()
        rows = db.logging_universe_list_rows_audit()
        protected = db.logging_universe_protected_tickers()
        candidates = db.logging_universe_eviction_candidates_fifo()
        evictions = db.logging_universe_recent_evictions(limit=30)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    with _logger_lock:
        in_memory = list(_logger_tickers)
    return JSONResponse(
        {
            "schema": "logging_universe_audit_v2",
            "rth_only": RTH_ONLY,
            "session_gate_loggable_now": _is_loggable_session(),
            "premarket_start_et_minute": PRE_MARKET_MINS,
            "buffer_end_et_minute": LOGGER_BUFFER_MINS,
            "max_user_persisted_symbols": MAX_USER_PERSISTED_LOGGING_TICKERS,
            "user_persisted_enrollment_policy": _user_persisted_enrollment_policy(),
            "max_pinned_symbols": MAX_PINNED_LOGGING_TICKERS,
            "core_tickers": CORE_TICKERS,
            "symbols_in_memory_logger_cycle": in_memory,
            "protected_symbols": protected,
            "eviction_candidates_fifo_user_persisted": candidates,
            "recent_evictions": evictions,
            "logging_universe_rows": rows,
        }
    )


@router.get("/api/logger/universe/by-category")
def logger_universe_by_category(
    category: str = Query(..., description="core | pinned | user_persisted"),
):
    # RC-REHAB-1 (route-extraction audit fix): `get_db` excluded from the eager
    # `from server import (...)` statement -- see logger_status's fix comment above.
    import server as _server
    from server import _HAS_SIGNALS

    if not _HAS_SIGNALS:
        raise HTTPException(status_code=503, detail="database logging not available")
    c = (category or "").strip().lower()
    if c not in ("core", "pinned", "user_persisted"):
        raise HTTPException(status_code=400, detail="category must be core, pinned, or user_persisted")
    try:
        rows = [
            r
            for r in _server.get_db().logging_universe_list_rows_audit()
            if (r.get("category") or "").lower() == c
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return JSONResponse({"category": c, "rows": rows, "count": len(rows)})


@router.post("/api/logger/pin")
def logger_pin(ticker: str = Query(..., description="Symbol to pin (non-core only)")):
    # RC-REHAB-1 (route-extraction audit fix): `import server as _server` gives two
    # independent fixes. (1) `get_db` is excluded from the eager `from server import
    # (...)` tuple below -- it is only bound in server's module namespace when the
    # signals/db import succeeded at server.py's own top-level load, and a blanket
    # import eagerly resolving it would raise ImportError before the `_HAS_SIGNALS`
    # guard ever runs, making that guard dead code. `_server.get_db()` defers
    # resolution to after the guard passes. (2) the post-hydrate read below resolves
    # the module's CURRENT global rather than a stale name bound at function entry --
    # _hydrate_logger_tickers_from_db() reassigns `_logger_tickers` to a new list
    # object rather than mutating it in place, so `from server import _logger_tickers`
    # would keep pointing at the pre-hydrate list, silently omitting the ticker just
    # pinned from this call's own response.
    import server as _server
    from server import (
        _HAS_SIGNALS,
        _hydrate_logger_tickers_from_db,
        _logger_lock,
        CORE_TICKERS,
        MAX_PINNED_LOGGING_TICKERS,
    )

    if not _HAS_SIGNALS:
        raise HTTPException(status_code=503, detail="database logging not available")
    t = ticker_storage_key(ticker)  # RC-345/F25: canonical pin identity (matches enrollment + dedup)
    if not t or len(t) > 10:
        raise HTTPException(status_code=400, detail="invalid ticker")
    if t in CORE_TICKERS:
        raise HTTPException(status_code=400, detail="core symbols are already protected; pin not applicable")
    db = _server.get_db()
    is_already_pinned = any(
        ticker_storage_key(r.get("ticker")) == t and r.get("category") == "pinned"  # RC-345/F25: canonical pin-dedup
        for r in db.logging_universe_list_rows()
    )
    if (
        not is_already_pinned
        and db.logging_universe_pinned_count() >= MAX_PINNED_LOGGING_TICKERS
    ):
        raise HTTPException(
            status_code=409,
            detail=f"max pinned symbols ({MAX_PINNED_LOGGING_TICKERS}) reached — unpin one first",
        )
    now = time.time()
    db.logging_universe_upsert_pinned(t, "api_logger_pin", now)
    _hydrate_logger_tickers_from_db()
    with _logger_lock:
        all_t = list(_server._logger_tickers)
    return JSONResponse({"ok": True, "ticker": t, "all_tickers": all_t})


@router.post("/api/logger/unpin")
def logger_unpin(ticker: str = Query(...)):
    # RC-REHAB-1 (route-extraction audit fix): three defects from the original
    # mechanical move, all real. (1) `_HAS_SIGNALS` was dropped entirely -- every
    # sibling route gates on it before calling get_db(). (2) even adding that guard
    # back is not enough on its own: `get_db` must also be excluded from the eager
    # `from server import (...)` tuple, since it is only bound in server's module
    # namespace when the signals/db import succeeded, and a blanket import eagerly
    # resolving it raises ImportError before any guard ever runs -- this is why every
    # OTHER logger route in this file needed the identical fix even though most of
    # them already had the guard text present. (3) the same stale-list bug as
    # logger_pin: `import server as _server` replaces `from server import
    # _logger_tickers` so the post-hydrate read resolves the reassigned module global
    # instead of the list object captured at function entry.
    import server as _server
    from server import (
        _HAS_SIGNALS,
        _hydrate_logger_tickers_from_db,
        _logger_lock,
    )

    if not _HAS_SIGNALS:
        raise HTTPException(status_code=503, detail="database logging not available")
    t = ticker.upper().strip()
    db = _server.get_db()
    ok = db.logging_universe_unpin_to_user_persisted(t, time.time())
    if not ok:
        raise HTTPException(status_code=400, detail="symbol is not pinned")
    _hydrate_logger_tickers_from_db()
    with _logger_lock:
        all_t = list(_server._logger_tickers)
    return JSONResponse({"ok": True, "ticker": t, "all_tickers": all_t})


@router.post("/api/logger/add")
# SWITCH-LATENCY FIX: sync def → threadpool (DB write via _register, no await).
def logger_add(ticker: str = Query(..., description="Ticker to add to background logger")):
    """Manually add a ticker to the background logger."""
    from server import _logger_lock, _logger_tickers, _register_tracked_ticker

    ticker = ticker.upper().strip()
    if not ticker or len(ticker) > 10:
        raise HTTPException(status_code=400, detail="Invalid ticker")
    added = _register_tracked_ticker(ticker, enrollment_source="api_logger_add")
    with _logger_lock:
        tickers = list(_logger_tickers)
    return JSONResponse({"added": added, "ticker": ticker, "all_tickers": tickers})


@router.post("/api/logger/remove")
def logger_remove(ticker: str = Query(..., description="Ticker to remove from logger")):
    """Remove a non-core ticker from the background logger and durable logging_universe."""
    # RC-REHAB-1 (route-extraction audit fix): `get_db` excluded from the eager
    # `from server import (...)` tuple -- see logger_status's fix comment above. It is
    # only ever touched inside the `if _HAS_SIGNALS:` block below.
    import server as _server
    from server import (
        _HAS_SIGNALS,
        _logger_lock,
        _logger_tickers,
        _market_context_panel_auto_candidates,
        CORE_TICKERS,
        log,
    )

    ticker = ticker.upper().strip()
    if ticker in CORE_TICKERS:
        raise HTTPException(status_code=400, detail=f"{ticker} is a core ticker and cannot be removed")
    panel_auto = frozenset(_market_context_panel_auto_candidates())
    if ticker in panel_auto:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{ticker} is auto-enrolled from the market cross-panel (see market_context.py) "
                "and cannot be removed via /api/logger/remove"
            ),
        )
    db_removed = False
    if _HAS_SIGNALS:
        try:
            db_removed = _server.get_db().logging_universe_remove_non_core(ticker)
        except Exception as e:
            log.warning("logging_universe_remove_non_core: %s", e)
    with _logger_lock:
        if ticker in _logger_tickers:
            _logger_tickers.remove(ticker)
            removed = True
        else:
            removed = False
        tickers = list(_logger_tickers)
    return JSONResponse(
        {
            "removed": removed,
            "db_removed": db_removed,
            "ticker": ticker,
            "all_tickers": tickers,
        }
    )
