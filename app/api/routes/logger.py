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
        get_db,
        log,
    )

    with _logger_lock:
        tickers = list(_logger_tickers)
        stats   = dict(_logger_stats)
        running = _logger_running

    db_rows: dict[str, dict] = {}
    if _HAS_SIGNALS:
        try:
            for row in get_db().logging_universe_list_rows():
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
            orphan_tickers = get_db().logging_universe_snapshot_ticker_orphans()
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
        get_db,
    )

    if not _HAS_SIGNALS:
        raise HTTPException(status_code=503, detail="database logging not available")
    try:
        db = get_db()
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
    from server import _HAS_SIGNALS, get_db

    if not _HAS_SIGNALS:
        raise HTTPException(status_code=503, detail="database logging not available")
    c = (category or "").strip().lower()
    if c not in ("core", "pinned", "user_persisted"):
        raise HTTPException(status_code=400, detail="category must be core, pinned, or user_persisted")
    try:
        rows = [
            r
            for r in get_db().logging_universe_list_rows_audit()
            if (r.get("category") or "").lower() == c
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return JSONResponse({"category": c, "rows": rows, "count": len(rows)})


@router.post("/api/logger/pin")
def logger_pin(ticker: str = Query(..., description="Symbol to pin (non-core only)")):
    from server import (
        _HAS_SIGNALS,
        _hydrate_logger_tickers_from_db,
        _logger_lock,
        _logger_tickers,
        CORE_TICKERS,
        MAX_PINNED_LOGGING_TICKERS,
        get_db,
    )

    if not _HAS_SIGNALS:
        raise HTTPException(status_code=503, detail="database logging not available")
    t = ticker_storage_key(ticker)  # RC-345/F25: canonical pin identity (matches enrollment + dedup)
    if not t or len(t) > 10:
        raise HTTPException(status_code=400, detail="invalid ticker")
    if t in CORE_TICKERS:
        raise HTTPException(status_code=400, detail="core symbols are already protected; pin not applicable")
    db = get_db()
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
        all_t = list(_logger_tickers)
    return JSONResponse({"ok": True, "ticker": t, "all_tickers": all_t})


@router.post("/api/logger/unpin")
def logger_unpin(ticker: str = Query(...)):
    from server import (
        _hydrate_logger_tickers_from_db,
        _logger_lock,
        _logger_tickers,
        get_db,
    )

    t = ticker.upper().strip()
    db = get_db()
    ok = db.logging_universe_unpin_to_user_persisted(t, time.time())
    if not ok:
        raise HTTPException(status_code=400, detail="symbol is not pinned")
    _hydrate_logger_tickers_from_db()
    with _logger_lock:
        all_t = list(_logger_tickers)
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
    from server import (
        _HAS_SIGNALS,
        _logger_lock,
        _logger_tickers,
        _market_context_panel_auto_candidates,
        CORE_TICKERS,
        get_db,
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
            db_removed = get_db().logging_universe_remove_non_core(ticker)
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
