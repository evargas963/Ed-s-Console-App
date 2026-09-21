"""Prediction-accuracy reporting API route (RC-REHAB-1, Phase 3). Every shared dependency
(the accuracy cache dict, the model-version resolver, the trader-facing subset shaper,
get_db, CANONICAL_TIMEFRAME) has other callers and stays in server.py, imported back lazily.
"""

from __future__ import annotations

import time

from config import DEFAULT_TICKER
from fastapi import APIRouter, Query

router = APIRouter()


@router.get("/api/accuracy")
# SWITCH-LATENCY FIX: sync def → threadpool (DB write via _register, no await).
def get_accuracy(ticker: str = Query(default=DEFAULT_TICKER)):
    """Return prediction accuracy for a ticker.

    Returns cached results if available (updated every ~10 min),
    otherwise computes fresh. Also returns accuracy history for charting.
    """
    # RC-REHAB-1 (route-extraction audit fix): `get_db` is deliberately NOT in this
    # `from server import (...)` tuple. `get_db` is only bound in server's module
    # namespace when the `db` import succeeded at server.py's own top-level load
    # (_HAS_SIGNALS gates on exactly that). A blanket `from server import (..., get_db)`
    # eagerly resolves EVERY listed name at function-entry, so if `_HAS_SIGNALS` is
    # False, that import statement itself raises ImportError before the `if
    # _HAS_SIGNALS` conditional below ever runs -- making the conditional dead code for
    # this exact failure mode. `import server as _server` defers `get_db`'s resolution
    # to an attribute access at the point of use, after `_HAS_SIGNALS` is known.
    import server as _server
    from server import (
        ACCURACY_HISTORY_LIMIT,
        ACCURACY_INTERVAL,
        CANONICAL_TIMEFRAME,
        _HAS_SIGNALS,
        _accuracy_cache,
        _current_pred_model_version,
        _touch_tracked_ticker_view,
        _trader_accuracy_subset,
        log,
    )

    ticker = (ticker or DEFAULT_TICKER).upper().strip()
    # TICKER-PREVIEW-NO-ENROLL: accuracy is a VIEW — touch last-seen only.
    _touch_tracked_ticker_view(ticker)

    db = _server.get_db() if _HAS_SIGNALS else None
    if not db:
        return {"error": "Database not connected"}

    # Use cache if fresh enough
    _serving_version = _current_pred_model_version(ticker)
    cached = _accuracy_cache.get(ticker, {})
    if cached and time.time() - cached.get("ts", 0) < ACCURACY_INTERVAL:  # caps-ok: internal cache-freshness clock only, not a Schwab/market field; a missing "ts" epoch-0 defaults to maximally stale (forces recompute), never a fabricated fresh timestamp
        results = cached["results"]
        all_hours = cached.get("all_hours")
    else:
        try:
            # RTH-scoped is the trading-relevance primary; all-hours is audit
            # context (operator decision 2026-07-06). Empty RTH scope fails
            # closed (accuracy None) — never widened to all-hours silently.
            results = db.compute_accuracy(
                ticker, CANONICAL_TIMEFRAME, model_version=_serving_version,
                rth_only=True,
            )
            all_hours = db.compute_accuracy(
                ticker, CANONICAL_TIMEFRAME, model_version=_serving_version,
                rth_only=False,
            )
            _accuracy_cache[ticker] = {
                "ts": time.time(), "results": results, "all_hours": all_hours,
            }
        except Exception as e:
            return {"error": str(e)}

        # Pass 5a: persist accuracy snapshot per horizon when value
        # meaningfully changed vs last logged row (db.maybe_log_model_accuracy
        # handles the dedup epsilon). Throttled by the existing 10-min
        # ACCURACY_INTERVAL cache above — at most one INSERT per ticker per
        # horizon per ~10min.
        for _hz, _hz_res in (results or {}).items():
            if not isinstance(_hz_res, dict):
                continue
            try:
                _new_id = db.maybe_log_model_accuracy(
                    ticker=ticker,
                    timeframe=CANONICAL_TIMEFRAME,
                    model_version=_serving_version,
                    horizon=_hz,
                    total_predictions=int(_hz_res.get("total", 0) or 0),  # silent-zero-ok: a COUNT of rows returned — no rows is genuinely zero predictions, not an unmeasured quantity  # caps-ok: same reasoning as the silent-zero-ok marker above — a COUNT's honest zero, not a fabricated default for an unmeasured Schwab field
                    correct_direction=_hz_res.get("correct"),
                    accuracy_pct=_hz_res.get("accuracy"),
                )
                if _new_id is not None:
                    log.info(
                        "model_accuracy ticker=%s horizon=%s acc=%s%% n=%s",
                        ticker, _hz,
                        _hz_res.get("accuracy"),
                        _hz_res.get("total"),
                    )
            except Exception as _mae:
                log.debug("log_model_accuracy ticker=%s hz=%s failed: %s", ticker, _hz, _mae)

    # Fetch history via Pass 5a reader (get_model_accuracy_history).
    history: list[dict] = []
    try:
        from ml_horizon import PRIMARY_DECISION_HORIZONS
        for _hz in PRIMARY_DECISION_HORIZONS:
            rows = db.get_model_accuracy_history(
                ticker=ticker,
                timeframe=CANONICAL_TIMEFRAME,
                model_version=_serving_version,
                horizon=_hz,
                limit=int(ACCURACY_HISTORY_LIMIT),
            )
            history.extend(rows)
    except Exception:
        history = []

    return {
        "ticker": ticker,
        "model_version": _serving_version,
        # Trading-relevance primary: RTH-scoped, with per-horizon baseline +
        # edge fields so raw accuracy cannot read as edge.
        "accuracy_scope": "rth_0930_1600_et",
        "current": _trader_accuracy_subset(results),
        # Audit context only — measured over every session the logger ran.
        "all_hours": _trader_accuracy_subset(all_hours or {}),
        "history": history,
    }
