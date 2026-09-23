"""Option chain / expiries API routes (RC-REHAB-1, Phase 3): the expiry-list lookup and the
COMPLETE (strike_range=ALL) contract-selection chain surface. Every shared dependency
(the state cache, the gated chain-fetch faucet, the stream-overlay faucet, the persisted
complete-chain-capture read/write pair, the completeness-basis constant -- also used
elsewhere in server.py -- and _touch_tracked_ticker_view) has other callers and stays in
server.py, imported back lazily.
"""

from __future__ import annotations

import time
from datetime import date

from config import DEFAULT_TICKER
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/api/expiries")
# SWITCH-LATENCY FIX: sync def → threadpool (DB write + Schwab expiry fetch, no await).
def get_expiries(ticker: str = Query(default=DEFAULT_TICKER)):
    from server import _fetch_expiries_light, _state_cache, _touch_tracked_ticker_view

    ticker = ticker.upper().strip()
    # TICKER-PREVIEW-NO-ENROLL: listing expiries is a VIEW — touch last-seen only.
    _touch_tracked_ticker_view(ticker)
    # Use any cached (ticker, expiry) entry — expiries list is same for all
    # CAPS audit fix (2026-09-20): the full ms_dict assembly unconditionally sets
    # ms_dict["expiries"] (server.py), so this key is only ever absent on a minimal
    # PENDING shell (a cold-cache placeholder written before the real computation
    # lands) or another malformed entry — defaulting to [] would silently report
    # "confirmed zero expiries" for a ticker that is actually still computing.
    # Require the real key to fall through to the live low-latency fetch instead.
    cached = next(
        (v for (t, e), v in _state_cache.items()
         if t == ticker and v.get("ms_dict") and "expiries" in v["ms_dict"]),
        None
    )
    if cached:
        return JSONResponse({"expiries": cached["ms_dict"]["expiries"]})
    try:
        return JSONResponse({"expiries": _fetch_expiries_light(ticker)})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/chain")
def get_chain(ticker: str = Query(default=DEFAULT_TICKER),
              expiry: str | None = Query(default=None)):
    """CONTRACT-SELECTION surface: the COMPLETE real vendor contract set for one ticker and
    one expiry — every strike Schwab actually lists, not a bounded analytical window — so a
    UI can let an operator pick one option contract and pass its `symbol` straight to POST
    /api/streaming/active-option-contract or GET /api/order-flow/options-microstructure —
    the same "chain response's own symbol field, never constructed" rule those two routes
    already document.

    COMPLETE, separate from the bounded analytical chain views: fetches LIVE, scoped to
    exactly one expiry, through _gated_safe_get_chain — the SAME single, rate-limited,
    coalesced chain-fetch faucet every other chain read in this file already uses (RC-59/
    RC-127/Cursor-audit F2's chain_width_single_faucet invariant) — using
    `strike_range="ALL"` (see COMPLETENESS_BASIS_STRIKE_RANGE_ALL's comment in calibration/complete_chain_capture.py for
    the measured proof this is genuinely complete, not merely wide), never a bare
    strike_count bound, and never a second per-contract parsing path (reuses
    flatten_chain_contracts/resolve_spot verbatim, same as every other chain consumer).
    Every native Schwab field is served AS-IS — nothing here rounds, filters, or
    reconstructs a strike from assumed spacing; fractional strikes (.50/.25/...) survive
    exactly as the vendor sent them.

    `expiry` optional: defaults to the ticker's nearest listed expiry (the SAME
    _fetch_expiries_light faucet /api/expiries uses). `scope.kind` states EXACTLY what was
    served, THREE tiers, honestly distinguished — a caller must never mistake a narrower
    tier for the complete live one:
      1. 'complete_single_expiry' — a live strike_range=ALL fetch succeeded AND the
         vendor's own returned_expiries matched the requested expiry EXACTLY (never
         claimed on a mismatch — see the expiry_scope_mismatch tier below). Also PERSISTS
         this proven-complete capture (calibration/complete_chain_capture.py) — a fully
         independent table from the bounded analytical snapshots, so completeness has a
         durable record, not just a live-request-shaped promise.
      2. 'expiry_scope_mismatch' — the vendor's response did not exactly match the
         requested expiry (e.g. returned a different or additional expiry). The contracts
         actually returned are still served (never silently dropped — real data), but
         completeness for the REQUESTED expiry is explicitly NOT claimed.
      3. 'persisted_complete_capture_fallback' — no live fetch this request (error/
         timeout/mismatch), but a PRIOR complete_single_expiry capture exists for this
         exact ticker+expiry; served with its captured_age_sec so staleness is visible.
      4. 'stored_analytical_snapshot_fallback' — last resort: the bounded, gamma/terrain-
         tuned snapshot this endpoint originally served, explicitly labeled as NOT proven
         complete. status='no_chain' if even this has nothing."""
    # RC-REHAB-1 (route-extraction audit fix): `get_db` deliberately excluded from this
    # `from server import (...)` tuple -- see logger.py's identical fix comment for why
    # a blanket import eagerly resolving `get_db` raises ImportError before either
    # try/except below (persist-capture, persisted-capture read) ever gets a chance to
    # run, turning both into dead code for that failure mode. `import server as
    # _server` defers resolution to each call site, already inside its own try/except.
    import server as _server
    from terrain_refresh import _gamma_surface_contracts_with_stream_overlay
    from calibration.complete_chain_capture import latest_complete_chain_capture, persist_complete_chain_capture
    from calibration.complete_chain_capture import COMPLETENESS_BASIS_STRIKE_RANGE_ALL
    from server import (
        _fetch_expiries_light,
        _gated_safe_get_chain,
        _latest_chain_and_spot,
        _touch_tracked_ticker_view,
        flatten_chain_contracts,
        get_client,
        log,
        resolve_spot,
    )

    t = ticker.upper().strip()
    # TICKER-PREVIEW-NO-ENROLL: listing a chain is a VIEW — touch last-seen only.
    _touch_tracked_ticker_view(t)

    resolved_expiry = (expiry or "").strip()[:10] or None
    if resolved_expiry is None:
        try:
            exps = _fetch_expiries_light(t)
            resolved_expiry = exps[0] if exps else None
        except Exception as e:
            log.debug("chain: expiry resolution failed for %s: %s", t, e)

    if resolved_expiry is not None:
        try:
            d = date.fromisoformat(resolved_expiry)
            client = get_client()
            c_resp, _gate_wait, _fetch_sec = _gated_safe_get_chain(
                client, t, strike_range="ALL", from_date=d, to_date=d, priority=False)
            if c_resp is not None and c_resp.status_code == 200:
                # This fetch's OWN as-of instant -- captured the moment the vendor's response
                # is in hand, before any overlay -- is the correct `newer_than_ts` baseline.
                _rest_fetch_ts = time.time()
                c_json = c_resp.json()
                spot, _spot_source, _spot_as_of = resolve_spot(t, chain_json=c_json)
                contracts = flatten_chain_contracts(c_json)
                # SCOPE CHECK, not defensive-only: never trust the request alone to
                # guarantee the response's own expirationDate matches what was actually
                # asked for — a mismatch here is the difference between claiming and
                # proving completeness for the REQUESTED expiry.
                returned_exps = sorted({
                    str(c.get("expirationDate") or "")[:10]
                    for c in contracts if isinstance(c, dict) and c.get("expirationDate")
                })
                # Independent-review finding (2026-09-13), REPRODUCED: this route always
                # returned the vendor REST chain's own `totalVolume`/greeks verbatim, even
                # though a real streamed tick for the SAME contract can already be sitting in
                # app.options.order_flow.state, correctly advanced (proven by a controlled
                # SQLite-replay+OrderFlowState reproduction) -- it simply never reached here.
                # `_gamma_surface_contracts_with_stream_overlay` is the SAME faucet
                # refresh_gamma_surface_from_stream already uses to freshen the terrain/
                # gamma-surface path (ONE overlay mechanism, not a second one for Chain).
                #
                # A FOURTH independent review (2026-09-13), REPRODUCED: the first fix passed
                # `newer_than_ts=None` here, reasoning "this fetch has no PRIOR REST-baseline
                # timestamp to compare against" -- false. This fetch IS itself a REST baseline
                # with its own as-of instant (`_rest_fetch_ts` above); passing None disabled
                # the entire ordering guard `overlay_streamed_contract_fields` exists to
                # enforce, leaving only the absolute `max_staleness_sec` bound -- which cannot
                # tell "newer than this REST read" from "merely recent". Controlled
                # reproduction: a streamed TOTAL_VOLUME=111 observed BEFORE this REST fetch
                # (which itself returned totalVolume=333) still overlaid onto the response,
                # replacing the newer REST value with the older streamed one, because nothing
                # compared the streamed observation's timestamp against this fetch's own.
                # Fixed by passing this fetch's own instant as `newer_than_ts`, the same
                # precedence rule every other overlay call site in this file already applies.
                #
                # The OVERLAID result is for the RESPONSE only -- `persist_complete_chain_capture`
                # below stores the PRE-overlay `contracts`, so the durable "complete REST
                # capture" record (tier 1's own contract: a proven, complete, live REST read)
                # is never silently blended with streamed fields it cannot itself timestamp.
                response_contracts, overlay_n, _ = _gamma_surface_contracts_with_stream_overlay(
                    t, contracts, newer_than_ts=_rest_fetch_ts)
                if returned_exps == [resolved_expiry]:
                    try:
                        persist_complete_chain_capture(
                            _server.get_db().db_path, ticker=t, expiry=resolved_expiry,
                            contracts=contracts, spot=spot,
                            completeness_basis=COMPLETENESS_BASIS_STRIKE_RANGE_ALL)
                    except Exception as e:
                        log.warning("chain: complete-capture persist failed for %s %s: %s",
                                   t, resolved_expiry, e)
                    return JSONResponse({
                        "ticker": t, "spot": spot, "expiry": resolved_expiry,
                        "contracts": response_contracts, "status": "ok" if response_contracts else "no_chain",
                        "stream_overlay_contracts": overlay_n,
                        "scope": {"kind": "complete_single_expiry",
                                 "requested_expiry": resolved_expiry,
                                 "returned_expiries": returned_exps,
                                 "completeness_basis": COMPLETENESS_BASIS_STRIKE_RANGE_ALL},
                    })
                log.warning("chain: expiry scope mismatch for %s — requested %s, vendor "
                           "returned %s; NOT claiming completeness", t, resolved_expiry,
                           returned_exps)
                if response_contracts:
                    return JSONResponse({
                        "ticker": t, "spot": spot, "expiry": resolved_expiry,
                        "contracts": response_contracts, "status": "ok",
                        "stream_overlay_contracts": overlay_n,
                        "scope": {"kind": "expiry_scope_mismatch",
                                 "requested_expiry": resolved_expiry,
                                 "returned_expiries": returned_exps,
                                 "note": "vendor response did not match the requested "
                                         "expiry exactly — served as-is for "
                                         "transparency, NOT proven complete for the "
                                         "requested expiry"},
                    })
                # No contracts at all for the mismatch case — fall through to the
                # persisted/stored tiers below rather than returning an empty response.
            else:
                log.warning("chain: live fetch non-200 for %s expiry %s, falling back",
                           t, resolved_expiry)
        except Exception as e:
            log.warning("chain: live fetch failed for %s expiry %s (%s), falling back",
                       t, resolved_expiry, e)

        try:
            cap = latest_complete_chain_capture(_server.get_db().db_path, t, resolved_expiry)
        except Exception as e:
            cap = None
            log.debug("chain: persisted-capture read failed for %s %s: %s",
                     t, resolved_expiry, e)
        if cap:
            # Same overlay faucet as the live tiers above, bounded here by the capture's
            # OWN as-of (a streamed field only overlays a banked capture when it is
            # genuinely newer than that specific capture, not merely "recent").
            cap_contracts, cap_overlay_n, _ = _gamma_surface_contracts_with_stream_overlay(
                t, cap["contracts"], newer_than_ts=cap["ts_utc"])
            return JSONResponse({
                "ticker": t, "spot": cap["spot"], "expiry": resolved_expiry,
                "contracts": cap_contracts, "status": "ok",
                "stream_overlay_contracts": cap_overlay_n,
                "scope": {"kind": "persisted_complete_capture_fallback",
                         "requested_expiry": resolved_expiry,
                         "completeness_basis": cap["completeness_basis"],
                         "captured_ts": cap["ts_utc"],
                         "captured_age_sec": round(time.time() - cap["ts_utc"], 1),
                         "note": "a prior COMPLETE capture — not fetched live this "
                                 "request, staleness stated above"},
            })

    contracts, spot, stored_ts = _latest_chain_and_spot(t)
    if not contracts:
        return JSONResponse({"ticker": t, "spot": spot, "expiry": None, "contracts": [],
                            "status": "no_chain",
                            "scope": {"kind": "stored_analytical_snapshot_fallback"}})
    stored_expiry = None
    for ct in contracts:
        if isinstance(ct, dict) and ct.get("expirationDate"):
            stored_expiry = str(ct["expirationDate"])[:10]
            break
    # A FOURTH independent review (2026-09-13), REPRODUCED: same newer_than_ts=None ordering
    # bug as the live-fetch tier above, here against a STORED snapshot's own row ts_utc
    # (now returned by _latest_chain_and_spot) instead of a live fetch's instant.
    contracts, overlay_n, _ = _gamma_surface_contracts_with_stream_overlay(
        t, contracts, newer_than_ts=stored_ts)
    return JSONResponse({
        "ticker": t, "spot": spot, "expiry": stored_expiry, "contracts": contracts,
        "stream_overlay_contracts": overlay_n,
        "status": "ok",
        "scope": {"kind": "stored_analytical_snapshot_fallback",
                 "note": "bounded analytical snapshot, NOT proven complete — live "
                         "complete-chain fetch and any persisted capture were both "
                         "unavailable this request"},
    })
