"""Manual prediction-direction override API routes (RC-REHAB-1, Phase 3). The override dict
(_pred_overrides) is also read by a getter used elsewhere in server.py's decision pipeline
and stays there, imported back lazily.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

router = APIRouter()


@router.post("/api/prediction/override")
# SWITCH-LATENCY FIX: sync def → threadpool (DB write via _register, no await).
def prediction_override(ticker: str = Query(...), direction: str = Query(...), source: str = Query("user")):
    """Set manual override for prediction direction. direction: up|flat|down. source: user|manual."""
    from server import _pred_overrides, _touch_tracked_ticker_view

    ticker = ticker.upper().strip()
    # TICKER-PREVIEW-NO-ENROLL (Decision 3): setting a prediction override acts on an existing
    # tracked symbol; it must not silently enroll a new one into the training roster.
    _touch_tracked_ticker_view(ticker)
    d = (direction or "").strip().lower()
    if d not in ("up", "flat", "down"):
        raise HTTPException(status_code=400, detail="direction must be up, flat, or down")
    src = (source or "user").lower()
    _pred_overrides[ticker] = {"direction": d, "source": src}
    return JSONResponse({"ok": True, "ticker": ticker, "direction": d, "source": src})


@router.post("/api/prediction/override/clear")
# SWITCH-LATENCY FIX: sync def → threadpool (DB write via _register, no await).
def prediction_override_clear(ticker: str = Query(...)):
    """Clear prediction override for ticker."""
    from server import _pred_overrides, _touch_tracked_ticker_view

    ticker = ticker.upper().strip()
    # TICKER-PREVIEW-NO-ENROLL (Decision 3): clearing an override must not enroll.
    _touch_tracked_ticker_view(ticker)
    if ticker in _pred_overrides:
        del _pred_overrides[ticker]
        return JSONResponse({"ok": True, "ticker": ticker, "cleared": True})
    return JSONResponse({"ok": True, "ticker": ticker, "cleared": False})
