"""Options order-flow history API routes."""

from __future__ import annotations

import time

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.options.order_flow.history import hydrate_option_content
from app.options.order_flow.live_payload import options_live_payload

router = APIRouter()


@router.get("/api/options/history")
def options_history(
    contract: str = Query(...),
    minutes: float = Query(default=15.0),
):
    """Build the live payload from persisted capture rows without opening Schwab."""
    normalized_contract = (contract or "").strip()
    if not normalized_contract:
        return JSONResponse({"error": "contract is required"}, status_code=400)
    try:
        lookback = float(minutes)
    except (TypeError, ValueError):
        lookback = 15.0
    if lookback <= 0 or lookback > 24 * 60:
        lookback = 15.0

    content = hydrate_option_content(
        normalized_contract,
        since_ts=time.time() - lookback * 60.0,
    )
    payload = options_live_payload(normalized_contract, content=content)
    payload["contract"] = normalized_contract
    payload["history_minutes"] = lookback
    payload["history_n"] = len(content)
    return JSONResponse(payload)
