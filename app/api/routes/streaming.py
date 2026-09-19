"""Streaming-subscription API routes: active ticker / active option contract(s) (RC-REHAB-1,
Phase 3). Each handler offloads its blocking streaming-plane call to server.py's shared fast-
quote thread pool, which has other callers and stays there, imported back lazily.
"""

from __future__ import annotations

import asyncio

from config import DEFAULT_TICKER
from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

router = APIRouter()


@router.post("/api/streaming/active-option-contract")
async def post_streaming_active_option_contract(payload: dict = Body(default={})):
    """Subscribe LEVELONE_OPTIONS+OPTIONS_BOOK to one option contract (dynamic; replaces
    prior subscription). Mirrors /api/streaming/active-ticker exactly, for the SEPARATE
    option-contract slot (an equity ticker and an option contract on that same underlying
    can be watched at once — see app/options/order_flow/streaming.py's module docstring)."""
    from server import _get_fast_quote_executor

    c = str(payload.get("contract") or "").strip()
    if not c:
        return JSONResponse({"ok": False, "error": "contract is required"}, status_code=400)

    # PR214 premerge gap 2: take the command's generation HERE, at admission, before the
    # body is offloaded to the executor. Ordering must reflect the order the operator's
    # commands ARRIVED, not the order their thread-pool bodies happen to finish -- an
    # A admitted first but delayed must not overwrite a B admitted later that already
    # wrote. The browser token cannot cover this: it only suppresses a stale RESPONSE.
    from app.options.order_flow.streaming import (
        StaleOptionCommandError,
        begin_option_contract_command,
    )
    generation = begin_option_contract_command()

    def _apply():
        from app.options.order_flow.streaming import (
            set_active_option_contract,
            get_option_contract_streaming_diagnostics,
        )

        ok = set_active_option_contract(c, command_generation=generation)
        # PR214 merge blocker 1A: bind the acknowledgement's health to the contract
        # THIS request asked for, so a client that validates the ack cannot be handed
        # a healthy-looking plane belonging to a different contract.
        diag = get_option_contract_streaming_diagnostics(for_contract=c)
        return {"ok": ok, "contract": c, "command_generation": generation, **diag}
    try:
        out = await asyncio.get_event_loop().run_in_executor(_get_fast_quote_executor(), _apply)
    except StaleOptionCommandError as e:
        # A superseded command is NOT the current authority. 409 Conflict, ok:false --
        # the client must not treat this as a successful subscription of `c`.
        return JSONResponse({"ok": False, "error": str(e), "contract": c,
                             "superseded": True, "command_generation": generation},
                            status_code=409)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e), "contract": c}, status_code=500)
    return JSONResponse(out)


@router.post("/api/streaming/active-option-contracts")
async def post_streaming_active_option_contracts(payload: dict = Body(default={})):
    """Subscribe LEVELONE_OPTIONS+OPTIONS_BOOK to a SET of ADDITIONAL option contracts,
    beside the one primary contract /api/streaming/active-option-contract manages (RC-UI-3,
    2026-09-12 multi-contract coverage). Mirrors that endpoint's generation-guarded write
    exactly, on its own independent generation counter -- see
    app.options.order_flow.streaming.set_active_option_contracts."""
    from server import _get_fast_quote_executor

    raw = payload.get("contracts")
    contracts = [str(s).strip() for s in raw] if isinstance(raw, list) else []
    contracts = [c for c in contracts if c]

    from app.options.order_flow.streaming import (
        StaleOptionCommandError,
        begin_option_contracts_command,
    )
    generation = begin_option_contracts_command()

    def _apply():
        from app.options.order_flow.streaming import set_active_option_contracts
        ok = set_active_option_contracts(contracts, command_generation=generation)
        return {"ok": ok, "contracts": contracts, "command_generation": generation}
    try:
        out = await asyncio.get_event_loop().run_in_executor(_get_fast_quote_executor(), _apply)
    except StaleOptionCommandError as e:
        return JSONResponse({"ok": False, "error": str(e), "contracts": contracts,
                             "superseded": True, "command_generation": generation},
                            status_code=409)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e), "contracts": contracts}, status_code=500)
    return JSONResponse(out)


@router.post("/api/streaming/active-ticker")
async def post_streaming_active_ticker(payload: dict = Body(default={})):
    """Subscribe Schwab L1+book to the active UI ticker (dynamic; replaces prior subscription)."""
    from server import _get_fast_quote_executor, _lmp

    t = (payload.get("ticker") or DEFAULT_TICKER)
    t = str(t).upper().strip()
    # SWITCH-LATENCY FIX (critical): set_streaming_active_ticker blocks on fut.result(timeout=30)
    # while it does 6 websocket re-subscribe round-trips, and this endpoint fires on EVERY ticker
    # switch. Running it on the async event loop froze the entire UI (all SSE/requests) for up to
    # 30s per switch. Offload the whole blocking block to the thread pool; the loop stays free.
    def _apply():
        from app.options.order_flow.streaming import set_streaming_active_ticker, get_streaming_diagnostics, get_plane_authority_for_ticker

        ok = set_streaming_active_ticker(t)
        _lmp.reset_sse_push_cursor(t)
        diag = get_streaming_diagnostics()
        return {"ok": ok, "ticker": t, **diag, "plane_quote_authority": get_plane_authority_for_ticker(t)}
    try:
        out = await asyncio.get_event_loop().run_in_executor(_get_fast_quote_executor(), _apply)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e), "ticker": t}, status_code=500)
    return JSONResponse(out)
