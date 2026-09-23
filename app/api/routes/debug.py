"""Non-production debug/diagnostic API routes (R-011) (RC-REHAB-1, Phase 3). debug_prediction
is the ONE route in this codebase that calls _fetch_state directly and synchronously, by
design (an operator debug tool that wants the real, uncached number) -- see
docs/ANALYTICS_STATE_TIER_BOUNDARIES_V1.md. Every shared dependency (the chain-fetch helpers,
_fetch_state itself, get_db, CANONICAL_TIMEFRAME) has other callers and stays in server.py,
imported back lazily.
"""

from __future__ import annotations

import os

from config import DEFAULT_TICKER
from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/api/debug/charm")
# SWITCH-LATENCY FIX: sync def → threadpool (blocking chain fetch, no await).
def debug_charm(ticker: str = DEFAULT_TICKER):
    """Diagnose why charm is not computing."""
    # RC-REHAB-1 (thirty-eighth slice): pure helpers come from their own modules, not
    # through server.py; only server-owned runtime names are imported from server.
    from chain_width import _chain_to_date_for, resolve_chain_strike_count
    from math_exposure import MISSING_GREEK_SENTINEL, gamma_is_plausible
    from schwab_client import safe_get_chain
    from instrument_identity import ticker_storage_key
    from server import (
        _default_expiry,
        _expiries_from_contracts,
        _touch_tracked_ticker_view,
        flatten_chain_contracts,
        get_client,
        resolve_spot,
    )

    try:
        ticker = ticker_storage_key(ticker or DEFAULT_TICKER)   # Cursor-audit F1: bare "SPX" -> "$SPX"
        # TICKER-PREVIEW-NO-ENROLL: charm diagnostic is a VIEW — touch last-seen only.
        _touch_tracked_ticker_view(ticker)
        from math_exposure import compute_net_charm

        cl       = get_client()
        # RC-59: charm IS level math — the debug view must see the same width the product
        # computes on, or it debugs a different chain than the one that produced the number.
        # Cursor-audit A1: and the same index DATE bound — without to_date this fetched the full
        # multi-year $SPX book (no cap) and 502'd on the budget, unlike the product's bounded path.
        c_resp   = safe_get_chain(cl, ticker, strike_count=resolve_chain_strike_count(ticker),
                                  to_date=_chain_to_date_for(ticker, None))
        if c_resp is None or c_resp.status_code != 200:
            return {"error": f"Chain fetch failed: status={getattr(c_resp, 'status_code', 'None')}"}  # caps-ok: diagnostic ERROR-MESSAGE text only (the string embedded in a failure report), not a market value; c_resp is already known falsy/non-200 here so no real status_code is being hidden
        chain_json = c_resp.json()
        contracts = flatten_chain_contracts(chain_json)
        raw_cts = contracts

        # Sample first contract raw fields
        first_raw = raw_cts[0] if raw_cts else {}  # caps-ok: diagnostic sampling placeholder (used only to list .keys() for display below); an empty contract list has no sample to show, not a fabricated contract
        raw_keys  = list(first_raw.keys())

        # Check expiration fields
        sample_exp  = [ct.get("expirationDate") for ct in contracts[:5]]
        sample_dte  = [ct.get("daysToExpiration") for ct in contracts[:5]]

        # Schwab uses -999.0 as a "missing greek" sentinel. The has_* counters
        # below reflect contracts with USABLE greeks/IV (sentinel-aware: not
        # None, not -999.0, finite) so this debug surface honestly diagnoses
        # why charm is or isn't computing.
        usable_gamma = 0
        usable_delta = 0
        usable_theta = 0
        usable_vega = 0
        usable_iv = 0
        sentinel_gamma = 0
        has_oi = 0
        from numeric_contract import float_finite_or_none as _fin
        for ct in contracts:
            # single source: canonical finite reader for every greek. Raw float() admitted
            # NaN (the counts were already NaN-safe via inline isfinite gates, now folded
            # into the reader); MISSING_GREEK_SENTINEL is finite, survives the read, and is
            # excluded explicitly — behaviour-identical, one fewer finite-check faucet.
            _g = _fin(ct.get("gamma"))
            _d = _fin(ct.get("delta"))
            if gamma_is_plausible(_g, _d):
                usable_gamma += 1
            if ct.get("gamma") == MISSING_GREEK_SENTINEL:
                sentinel_gamma += 1
            if _d is not None and _d != MISSING_GREEK_SENTINEL:
                usable_delta += 1
            _t = _fin(ct.get("theta"))
            if _t is not None and _t != MISSING_GREEK_SENTINEL:
                usable_theta += 1
            _v = _fin(ct.get("vega"))
            if _v is not None and _v != MISSING_GREEK_SENTINEL:
                usable_vega += 1
            _iv = _fin(ct.get("volatility"))
            if _iv is not None and _iv > 0 and _iv != MISSING_GREEK_SENTINEL:
                usable_iv += 1
            if ct.get("openInterest"):
                has_oi += 1

        # What expiries exist?
        expiries     = _expiries_from_contracts(contracts)
        selected_exp = _default_expiry(expiries, ticker)

        # Try charm with all contracts, no filter
        # ONE spot faucet: LAST_PRICE only via resolve_spot. Chain underlyingPrice is
        # never current live spot. If LAST_PRICE is missing this diagnostic fails closed.
        spot, spot_source, spot_ts = resolve_spot(ticker, chain_json=chain_json)
        if spot is None or spot <= 0:
            return {"error": f"no spot available (resolve_spot) for {ticker}"}
        charm_all = compute_net_charm(contracts, spot, selected_exp or "")

        return {
            "spot": spot,
            "spot_source": spot_source,
            "spot_as_of_ts_utc": spot_ts,
            "total_contracts": len(contracts),
            "has_gamma": usable_gamma,
            "has_delta": usable_delta,
            "has_theta": usable_theta,
            "has_vega": usable_vega,
            "has_iv": usable_iv,
            "gamma_sentinel_count": sentinel_gamma,
            "has_oi": has_oi,
            "raw_keys_sample": raw_keys[:20],
            "sample_expirationDate": sample_exp,
            "sample_daysToExpiration": sample_dte,
            "expiries_found": expiries[:10],
            "selected_exp": selected_exp,
            "charm_result": charm_all,
        }
    except Exception as e:
        import traceback
        return {"error": str(e), "trace": traceback.format_exc()}


@router.get("/api/debug/prediction")
# SWITCH-LATENCY FIX: sync def → threadpool (blocking full _fetch_state, no await).
def debug_prediction(ticker: str = DEFAULT_TICKER):
    """Show exactly what the prediction engine is querying — non-production debug surface (R-011)."""
    # RC-REHAB-1 (route-extraction audit fix): `get_db` excluded from the eager
    # `from server import (...)` statement -- see logger.py's identical fix comment.
    # A blanket import resolving `get_db` eagerly would raise ImportError before the
    # `if _HAS_SIGNALS:` guard below ever runs. `import server as _server` defers
    # resolution to after that guard has already passed.
    import server as _server
    from timeframe_config import CANONICAL_TIMEFRAME
    from server import _HAS_SIGNALS, _fetch_state

    if os.environ.get("ED_ALLOW_DEBUG_ENDPOINTS", "").strip().lower() not in ("1", "true", "yes"):  # caps-ok: env-var config read is the endpoint's own feature-flag gate itself, not a Schwab/market field default
        raise HTTPException(status_code=404, detail="debug endpoints disabled")
    try:
        state = _fetch_state(ticker, expiry=None, update_source="debug_endpoint")
        # Operator-facing DIAGNOSTIC DISPLAY fields only, gated behind
        # ED_ALLOW_DEBUG_ENDPOINTS above and never consumed by a decision path — "?"
        # means "field absent from this state" for human inspection, not a claim that
        # the underlying market/model value equals zero, flat, or unknown.
        zone = state.get("zone", "?")  # caps-ok: gated debug display field, see comment above
        vwap_side = state.get("vwap_side", "?")  # caps-ok: gated debug display field, see comment above
        bias = state.get("bias_signal", "?")  # caps-ok: gated debug display field, see comment above
        pin = state.get("pin_strength", "?")  # caps-ok: gated debug display field, see comment above
        nd = state.get("net_delta", "?")  # caps-ok: gated debug display field, see comment above
        ng = state.get("net_gamma", "?")  # caps-ok: gated debug display field, see comment above
        gex_mag = state.get("gex_magnitude", "?")  # caps-ok: gated debug display field, see comment above
        dex_mag = state.get("dex_magnitude", "?")  # caps-ok: gated debug display field, see comment above
        samples = state.get("samples_used", "?")  # caps-ok: gated debug display field, see comment above
        model_note = state.get("model_note", "?")  # caps-ok: gated debug display field, see comment above
        session_bkt = state.get("session_bucket", "?")  # caps-ok: gated debug display field, see comment above
        vix_bkt = state.get("vix_bucket", "?")  # caps-ok: gated debug display field, see comment above

        # Count snapshots per zone in DB
        zone_counts = {}
        if _HAS_SIGNALS:
            db = _server.get_db()
            if db:
                zone_counts = db.get_zone_distribution(ticker, CANONICAL_TIMEFRAME)

        return {
            "current_query": {
                "zone": zone,
                "vwap_side": vwap_side,
                "session_bucket": session_bkt,
                "vix_bucket": vix_bkt,
                "bias_signal": bias,
                "pin_strength": pin,
                "net_delta": nd,
                "net_gamma": ng,
                "gex_magnitude": gex_mag,
                "dex_magnitude": dex_mag,
            },
            "prediction_result": {
                "samples_used": samples,
                "model_note": model_note,
            },
            "db_zone_distribution": zone_counts,
        }
    except Exception as e:
        import traceback
        return {"error": str(e), "trace": traceback.format_exc()}
