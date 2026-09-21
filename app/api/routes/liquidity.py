"""Liquidity/value-playbook and canonical price-levels API routes (RC-REHAB-1, Phase 3).
Every private helper used only by these routes (_build_raw_levels_used,
_liquidity_live_1m_overlay_bars, _liquidity_fusion_from_cache, _liquidity_zone_tradeable_fields)
has at least one other real caller in server.py's Phase 2A canonical-levels machinery (verified
before assuming a blanket "private, could move" reading) and stays there, imported back lazily,
along with every other shared dependency (resolve_spot, canonical_price_level_snapshot, get_client,
now_et, _touch_tracked_ticker_view, _state_cache).
"""

from __future__ import annotations

from config import DEFAULT_TICKER
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from instrument_identity import ticker_storage_key

router = APIRouter()


@router.get("/api/levels")
# Phase 2A (operator 2026-08-08): /api/levels is the canonical SERVING CONTRACT for the
# one materialized PriceLevelSnapshot — it serializes, it does not compute. Every other
# surface (liquidity-snapshot, market_context, /api/state, ML features, persistence,
# chart) carries the values out of the same snapshot object and generation.
def get_levels(ticker: str = Query(default=DEFAULT_TICKER)):
    """Single levels contract (schema v1): id/price/family/evidence_tier/provenance/staleness."""
    import time as _time

    from liquidity_value_engine import carry_snapshot_levels
    from server import canonical_price_level_snapshot, resolve_spot

    tk = ticker_storage_key(ticker or DEFAULT_TICKER)
    served_ts = _time.time()
    spot, spot_source, spot_ts = resolve_spot(tk)
    snap = canonical_price_level_snapshot(tk)
    # Register this surface against the runtime carrier contract: if any other carrier
    # already shipped a different value/generation/provenance for this generation, the
    # disagreement raises here instead of reaching two screens (RC-262 pattern).
    carry_snapshot_levels(snap, "api.levels")

    levels: list[dict] = []
    for lid, value in snap.levels.items():
        row = value.to_contract_dict()
        as_of = value.as_of_ts_utc
        row["staleness"] = {
            "as_of_ts_utc": as_of,
            "age_sec": None if as_of is None else round(served_ts - as_of, 1),
            "stale_after_sec": None,
            "stale": False,
            "reason": f"carried from canonical snapshot generation {snap.generation}",
        }
        levels.append(row)

    families_absent = list(snap.families_absent)
    for fam, why in (
        ("gamma", "Phase 2A slice excludes gamma — served by /api/terrain until migration"),
        ("expected_move", "Phase 2A slice excludes EM — served by /api/state until migration"),
    ):
        families_absent.append({"family": fam, "reason": why})

    return JSONResponse({
        "ticker": tk,
        "schema_version": 1,
        "served_ts_utc": served_ts,
        "spot": spot,
        "spot_source": spot_source,
        "spot_as_of_ts_utc": spot_ts,
        "generation": snap.generation,
        "snapshot_as_of_ts_utc": snap.as_of_ts_utc,
        "bar_source": snap.bar_source,
        "levels": levels,
        # The VWAP curve and its σ bands, CARRIED. chart.html and exposure.html each
        # used to accumulate their own from /api/bars1m — two more VWAPs for one
        # session, drawn beside a level neither of them agreed with.
        # [epoch_sec, vwap, +1σ, -1σ, +2σ, -2σ]
        "vwap_series": [list(row) for row in snap.vwap_series],
        "families_absent": families_absent,
        "degraded": list(snap.degraded),
    })


@router.get("/api/liquidity-snapshot")
# SWITCH-LATENCY FIX: sync def → threadpool. This fires on every ticker switch (client
# setTimeout pollLiquiditySnapshot) and every 60s; it does a blocking Schwab bar fetch with
# no await, so as async it stalled the event loop on each switch.
def get_liquidity_snapshot(
    ticker: str = Query(default=DEFAULT_TICKER),
    date: str | None = Query(default=None, description="Session date YYYY-MM-DD (default: today ET)"),
    snapshot: str = Query(
        default="premarket",
        description="live | premarket | opening | midday | afternoon. live = rolling cutoff (now ET) + optional options fusion",
    ),
    expiry: str | None = Query(default=None, description="Expiry YYYY-MM-DD for fusion with cached /api/state walls"),
    fusion: bool = Query(default=True, description="When snapshot=live, merge options walls from state cache (needs expiry)"),
):
    """Return liquidity & value playbook snapshot (zones, summary, raw_levels) for ticker/session.
    Uses PlaybookConfig(clustering_mode='percent'). ``live`` uses min(now,RTH close) cutoff; checkpoints unchanged."""
    from server import (
        _build_raw_levels_used,
        _liquidity_fusion_from_cache,
        _liquidity_live_1m_overlay_bars,
        _liquidity_zone_tradeable_fields,
        _touch_tracked_ticker_view,
        canonical_price_level_snapshot,
        get_client,
        now_et,
        resolve_spot,
    )

    try:
        from polling_adapter import fetch_bars_via_schwab_for_session
        from liquidity_value_engine import build_live_snapshot, generate_liquidity_value_snapshot
        from liquidity_models import SnapshotType, PlaybookConfig

        session_date = date or now_et().strftime("%Y-%m-%d")
        ticker_upper = ticker.upper().strip()
        # TICKER-PREVIEW-NO-ENROLL: liquidity snapshot is a VIEW — touch last-seen only.
        _touch_tracked_ticker_view(ticker_upper)
        client = get_client()
        from datetime import date as date_type

        session_date_obj = date_type.fromisoformat(session_date)
        bars = fetch_bars_via_schwab_for_session(
            client, ticker_upper, session_date_obj, include_extended_hours=True
        )
        if not bars:
            return JSONResponse(
                {"error": f"No bar data for {ticker_upper} on {session_date}"},
                status_code=404,
            )
        config = PlaybookConfig(clustering_mode="percent", max_zone_width=2.0)
        snap_raw = snapshot.lower().strip()
        fusion_status = "n/a"
        spot_for_zones: float | None = None
        extra: list[tuple[float, str]] = []
        bar_merge_note = "schwab"

        if snap_raw == "live":
            today_ld = now_et().date()
            if session_date_obj == today_ld:
                from liquidity_value_engine import merge_schwab_bars_with_live_overlay

                _ov = _liquidity_live_1m_overlay_bars(ticker_upper)
                if _ov:
                    bars = merge_schwab_bars_with_live_overlay(bars, _ov)
                    bar_merge_note = "schwab+live_1m_overlay"

        if snap_raw == "live":
            extra = []
            if fusion and expiry:
                extra, fusion_status = _liquidity_fusion_from_cache(ticker_upper, expiry)
            elif fusion and not expiry:
                fusion_status = "no_expiry"
            else:
                fusion_status = "disabled"
            # RC spot-360-audit (2026-09-14, live RTH reproduction): spot_for_zones used to come
            # from _state_cache (the /api/state cache -- last-write-wins, NO freshness gate) via
            # _liquidity_fusion_from_cache / _liquidity_spot_from_cache_any_expiry: a THIRD spot
            # producer next to resolve_spot()/live_market_plane. Reproduced live: this route
            # served 759.725 off a cache entry 1061s (17.7 min) old while the header read 760.13
            # at the same instant. resolve_spot() is THE spot authority for every other consumer
            # in this file (RC-14); zone scoring must read the same one, not a stale side-cache
            # keyed off whichever (ticker, expiry) /api/state happened to be called for last.
            spot_for_zones, _, _ = resolve_spot(ticker_upper)
            _extra_for_build = list(extra) if fusion else []
            if spot_for_zones is not None and fusion:
                _extra_for_build.append((spot_for_zones, "SPOT_LIVE"))
            # Phase 2A: this endpoint CARRIES the canonical snapshot; it does not compute
            # the Phase 2A families. MEASURED before this change, same instant, same
            # ticker: /api/levels overnight 773.3975/773.3975 vs this endpoint
            # 773.40/772.55 — one concept, two bar inputs, two answers on two screens.
            _canon = None
            if session_date_obj == now_et().date():
                from liquidity_value_engine import carry_snapshot_levels
                _canon = canonical_price_level_snapshot(ticker_upper)
                carry_snapshot_levels(_canon, "api.liquidity_snapshot")
            out = build_live_snapshot(
                ticker_upper,
                bars,
                session_date_obj,
                config,
                extra_levels=_extra_for_build if fusion else None,
                spot=spot_for_zones,
                canonical=_canon,
            )
            # MEASURED 2026-09-11: this used to reassign spot_for_zones itself to the VWAP
            # value and report it as spot_used_for_scoring below -- but build_live_snapshot
            # was ALREADY called with spot=None on this path (the reassignment happens after
            # the call), so that field claimed a spot was used for scoring when neither a real
            # spot NOR this VWAP number actually was. A VWAP price is a different financial
            # quantity than spot; reporting it under a field named "spot" is exactly the
            # fabricated-default this codebase's own law forbids ("no fabricated defaults, no
            # silent fallbacks"). Absence now stays absent under that name; the VWAP estimate,
            # when available, is reported under its own honestly-named field instead.
            spot_estimate_vwap_fallback = None
            if spot_for_zones is None:
                _rv = (out.raw_levels or {}).get("vwap")
                if _rv is not None:
                    try:
                        spot_estimate_vwap_fallback = float(_rv)
                    except (TypeError, ValueError):
                        spot_estimate_vwap_fallback = None
        else:
            out = generate_liquidity_value_snapshot(
                ticker=ticker_upper,
                bars_dataframe=bars,
                session_date=session_date,
                snapshot_type=SnapshotType(snap_raw),
                config=config,
            )
        snapshot_val = out.snapshot_type.value
        zones_payload = []
        for z in out.zones:
            w = z.zone_high - z.zone_low
            merged = len(z.source_tags)
            zp = {
                "zone_type": z.zone_type.value,
                "zone_class": z.zone_class,
                "zone_low": z.zone_low,
                "zone_high": z.zone_high,
                "zone_mid": z.zone_mid,
                "zone_width": round(w, 4),
                "source_levels": z.source_levels,
                "source_tags": z.source_tags,
                "confluence_score": z.confluence_score,
                "merged_levels_count": merged,
                "interpretation_notes": z.interpretation_notes or "",
                "first_snapshot": snapshot_val,
                "last_snapshot": snapshot_val,
                "persistence": 1,
            }
            if snap_raw == "live":
                _liquidity_zone_tradeable_fields(zp, spot_for_zones)
            zones_payload.append(zp)
        if snap_raw == "live":
            zones_payload.sort(
                key=lambda x: (
                    x["distance_to_spot"] is None,
                    x["distance_to_spot"] if x["distance_to_spot"] is not None else 1e9,
                    -x.get("tradeable_score", 0),  # caps-ok: sort-key fallback only; _liquidity_zone_tradeable_fields unconditionally sets tradeable_score on every zp under the same `snap_raw == "live"` gate this sort itself runs under, so the default is an unreachable defensive fallback, not a real substitution
                )
            )
        result = {
            "ticker": out.ticker,
            "symbol": ticker_upper,
            "session_date": out.session_date,
            "snapshot_type": snapshot_val,
            "zones": zones_payload,
            "summary": None,
            "raw_levels": out.raw_levels,
            "raw_levels_used": _build_raw_levels_used(out.raw_levels, snapshot_val),
        }
        if snap_raw == "live":
            result["fusion"] = fusion_status
            result["bar_merge"] = bar_merge_note
            result["as_of_cutoff_et"] = (out.raw_levels or {}).get("cutoff_et")
            result["expiry_used_for_fusion"] = expiry.strip() if expiry else None
            result["spot_used_for_scoring"] = spot_for_zones
            # Honest, separately-named -- see the comment above the assignment: this is VWAP,
            # a different financial quantity than spot, not a value spot_used_for_scoring may
            # silently stand in for.
            result["spot_estimate_vwap_fallback"] = spot_estimate_vwap_fallback
            # Phase 2A carriage stamp: which snapshot generation these level values ARE.
            # Two carriers that agree on the number but not on the generation are still
            # two answers — the generation travels so the skew is visible, never silent.
            result["level_generation"] = _canon.generation if _canon is not None else None
            result["level_semantic_scope"] = (out.raw_levels or {}).get("semantic_scope")
            result["level_snapshot_as_of_ts_utc"] = (
                _canon.as_of_ts_utc if _canon is not None else None)
            result["level_bar_source"] = _canon.bar_source if _canon is not None else None
        if out.summary:
            result["summary"] = {
                "value_state": out.summary.value_state,
                "vwap_relation": out.summary.vwap_relation,
                "auction_interpretation": out.summary.auction_interpretation,
                "notes": out.summary.notes,
            }
        return result
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except HTTPException as e:
        # MEASURED 2026-09-11: get_client() raises HTTPException(503, ...) when Schwab auth is
        # genuinely unavailable -- a real, distinct, already-correct classification (missing/
        # invalid credentials is not "the server is broken"). The blanket `except Exception`
        # below caught it too, along with everything else, and re-issued it as a bare 500 with
        # only the message text -- discarding the status code FastAPI's own exception handling
        # would otherwise have propagated correctly. Preserve it instead of replacing it.
        return JSONResponse({"error": e.detail}, status_code=e.status_code)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/liquidity-playbook-state")
# SWITCH-LATENCY FIX: sync def → threadpool (blocking Schwab bar fetch, no await).
def get_liquidity_playbook_state(
    ticker: str = Query(default=DEFAULT_TICKER),
    date: str | None = Query(default=None, description="Session date YYYY-MM-DD (default: today ET)"),
):
    """Return full PlaybookState with all four snapshots (premarket, opening, midday, afternoon).
    Each snapshot uses only data through its cutoff time (no lookahead)."""
    from server import _touch_tracked_ticker_view, get_client, now_et

    try:
        from polling_adapter import fetch_bars_via_schwab_for_session
        from liquidity_value_engine import generate_playbook_state, playbook_state_to_dict
        from liquidity_models import PlaybookConfig

        session_date = date or now_et().strftime("%Y-%m-%d")
        ticker_upper = ticker.upper().strip()
        # TICKER-PREVIEW-NO-ENROLL: playbook-state is a VIEW — touch last-seen only.
        _touch_tracked_ticker_view(ticker_upper)
        client = get_client()
        from datetime import date as date_type
        session_date_obj = date_type.fromisoformat(session_date)
        bars = fetch_bars_via_schwab_for_session(
            client, ticker_upper, session_date_obj, include_extended_hours=True
        )
        if not bars:
            return JSONResponse(
                {"error": f"No bar data for {ticker_upper} on {session_date}"},
                status_code=404,
            )
        state = generate_playbook_state(
            ticker=ticker_upper,
            bars_dataframe=bars,
            session_date=session_date,
            config=PlaybookConfig(clustering_mode="percent", max_zone_width=2.0),
        )
        return playbook_state_to_dict(state)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
