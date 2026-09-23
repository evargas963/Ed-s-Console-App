"""Options per-strike exposure and tape API routes (RC-REHAB-1, Phase 3)."""

from __future__ import annotations

import logging
import time
from typing import Optional

from config import DEFAULT_TICKER
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from instrument_identity import ticker_storage_key
from json_blob_codec import decode_json_blob   # RC-REHAB-3: transparent gzip on JSON blob columns
from time_et import now_et

router = APIRouter()
log = logging.getLogger("ed_server")


@router.get("/api/options/vanna-by-strike")
def get_vanna_by_strike(ticker: str = Query(default=DEFAULT_TICKER)):
    """Per-strike dealer VANNA exposure (operator field-inventory audit, 2026-09-13): the
    SAME canonical faucet (math_exposure_core.compute_exposures_by_strike) the Gamma/DEX
    heatmaps already use, aggregated across every expiry in the live wide chain (Vanna has
    no per-expiry SURFACE yet — see the Multi-Map subview's own note — so this is the
    aggregate-by-strike tier the Key Levels 'AGG $ ONLY' badge already discloses, not a
    narrower or different computation). net_vanna = call_vanna - put_vanna, the SAME
    +call/-put dealer-book convention net_gex_1pct and net_charm_daily already use (RC-211's
    exact BS-vanna faucet, math_levels.bs_vanna, independently FD-verified)."""
    from math_exposure_core import compute_exposures_by_strike as _cebs
    from numeric_contract import float_finite_or_none as _fin
    from terrain_reprice import _live_terrain_contracts_and_spot
    from server import _touch_tracked_ticker_view

    tk = ticker_storage_key(ticker or DEFAULT_TICKER)
    _touch_tracked_ticker_view(tk)
    contracts, spot = _live_terrain_contracts_and_spot(tk)
    if not contracts:
        return JSONResponse({"ticker": tk, "available": False,
                             "reason": "no live wide chain cached yet for this ticker"})
    exposures, _diag = _cebs(contracts, spot=spot, require_oi=True)
    rows = []
    for k, b in exposures.items():
        # Independent-review finding, REPRODUCED (live SPX, 2026-09-14): call_vanna/put_vanna
        # are pre-initialized to a real 0.0 by _strike_bucket, so a strike where every contract
        # failed the OI gate returned (0.0, 0.0) here -- neither None, so the `cv is None and
        # pv is None` check never caught it and the row rendered a fabricated net_vanna of 0.0.
        # has_oi (math_exposure_core.py's own canonical signal) is the real gate.
        if not b.get("has_oi"):
            continue
        cv, pv = b.get("call_vanna"), b.get("put_vanna")
        if cv is None and pv is None:
            continue
        net = _fin(cv or 0.0) - _fin(pv or 0.0) if (_fin(cv) is not None or _fin(pv) is not None) else None
        if net is None:
            continue
        rows.append([round(float(k), 2), round(net, 2)])
    rows.sort(key=lambda r: r[0])
    return JSONResponse({
        "ticker": tk, "available": True, "spot": spot, "rows": rows,
        "method": ("live wide chain -> compute_exposures_by_strike (same faucet the Gamma/"
                   "DEX heatmaps use) -> net_vanna = call_vanna - put_vanna, aggregated "
                   "across every expiry (no per-expiry surface yet)"),
    })


@router.get("/api/options/charm-by-strike")
def get_charm_by_strike(ticker: str = Query(default=DEFAULT_TICKER)):
    """Per-strike dealer CHARM exposure (operator field-inventory audit, 2026-09-13): the
    SAME canonical faucet (math_levels.compute_charm_by_strike, the exact function
    /api/forces's charm_below/charm_above already sum) applied to the live wide chain, row-
    shaped for a strike bar chart the same way /api/terrain/strikes already is. Units:
    delta-shares decaying per day (RC-179 dealer convention: +call/-put)."""
    from math_levels import compute_charm_by_strike as _ccs
    from terrain_reprice import _live_terrain_contracts_and_spot
    from server import _touch_tracked_ticker_view

    tk = ticker_storage_key(ticker or DEFAULT_TICKER)
    _touch_tracked_ticker_view(tk)
    contracts, spot = _live_terrain_contracts_and_spot(tk)
    if not contracts:
        return JSONResponse({"ticker": tk, "available": False,
                             "reason": "no live wide chain cached yet for this ticker"})
    per_ch = _ccs(contracts, spot)
    rows = sorted(
        [round(float(k), 2), round(float(b["net_charm"]), 4)]
        for k, b in per_ch.items() if b.get("net_charm") is not None
    )
    return JSONResponse({
        "ticker": tk, "available": bool(rows), "spot": spot, "rows": rows,
        "reason": None if rows else "charm_by_strike produced no usable strikes for this chain",
        "method": ("live wide chain -> math_levels.compute_charm_by_strike (the same faucet "
                   "/api/forces's charm_below/charm_above already sum) -> net_charm = "
                   "call_charm - put_charm per strike, delta-shares/day"),
    })


@router.get("/api/options/tape")
def get_options_tape(ticker: str = Query(default=DEFAULT_TICKER),
                     contract: Optional[str] = Query(default=None),
                     limit: int = Query(default=100)):
    """Discrete option TRADE prints (operator field-inventory audit, 2026-09-13) — the
    Options Flow tape, locked to the operator's own required schema: Time/Symbol/Expiry/
    Type/Strike/Bid x Size/Ask x Size/Trade/Size/Premium/Volume/OI/IV/Delta/provenance.
    Sourced from app.options.order_flow.history.tape_rows_for_symbol, which reads the
    ALREADY-CAPTURED native LEVELONE_OPTIONS ticks in stream_options_quotes_raw verbatim —
    no new capture, no derived/estimated field, no fabricated buy/sell aggressor side.

    `contract`, when given, scopes to exactly that vendor symbol. Otherwise scopes to every
    CURRENTLY DESIRED contract for `ticker` (the primary + additional option contracts the
    operator has actually selected — the same identity `_desired_stream_greeks_for_ticker`
    already resolves for the gamma-surface overlay), merged newest-first and capped at
    `limit` across the whole merge, not per-contract."""
    from app.options.order_flow.history import tape_rows_for_symbol
    from app.options.order_flow.streaming import (
        contract_matches_underlying,
        get_active_option_contract,
        get_active_option_contracts,
    )

    tk = ticker_storage_key(ticker or DEFAULT_TICKER)
    try:
        bounded_limit = max(1, min(500, int(limit)))
    except (TypeError, ValueError):
        bounded_limit = 100

    if contract:
        symbols = [contract]
    else:
        candidates = list(get_active_option_contracts())
        primary = get_active_option_contract()
        if primary:
            candidates.append(primary)
        seen: set[str] = set()
        symbols = []
        for sym in candidates:
            if sym and sym not in seen and contract_matches_underlying(sym, tk):
                seen.add(sym)
                symbols.append(sym)

    if not symbols:
        return JSONResponse({"ticker": tk, "available": False, "rows": [],
                             "reason": "no active/additional option contract selected for this ticker"})

    rows: list[dict] = []
    for sym in symbols:
        rows.extend(tape_rows_for_symbol(sym, since_ts=0.0, limit=bounded_limit))
    rows.sort(key=lambda r: r["ts_recv"], reverse=True)
    rows = rows[:bounded_limit]
    return JSONResponse({
        "ticker": tk, "available": bool(rows), "symbols": symbols, "rows": rows,
        "reason": None if rows else "no trade prints captured yet for the selected contract(s)",
        "method": ("stream_options_quotes_raw (native LEVELONE_OPTIONS capture, already "
                   "retained) -> tape_rows_for_symbol (de-duplicated genuine trade prints, "
                   "context carried forward) -> merged newest-first across every currently "
                   "desired contract for this ticker"),
    })


@router.get("/api/options/gamma-surface")
def get_options_gamma_surface(ticker: str = Query(default=DEFAULT_TICKER)):
    """Strike × expiration signed GEX$ surface (cell = net_gex_1pct) through the ONE canonical
    faucet compute_exposures_by_strike.

    Source order is deliberate. PREFERRED is the LIVE surface: _terrain_refresh_one (the single
    levels producer) projects it each cycle from the same live wide chain + live spot it already
    fetches, and caches it (source=terrain_live_cache). FALLBACK is the banked MORNING wide chain,
    used only when the live cache is cold and labelled a reference (live=false, stale=true) — a
    morning snapshot is never presented as intraday. Exposes chain/spot as-of, source, and
    stale/degraded so the UI can fail stale visibly.

    RC-REHAB-1 (Phase 3, fifth extraction slice): every name below (_note_gamma_surface_demand,
    terrain_cache_get, _gamma_surface_coverage_summary, _option_contract_admission_summary,
    _gamma_surface_cell_state_counts, _stamp_surface_session, _GAMMA_SURFACE_CACHE,
    _gamma_surface_wanted, _ticker_on_terrain_board, _desired_option_symbols_for_ticker,
    _stamp_gamma_surface_cell_stream_state, project_gamma_surface, get_db (via `import server
    as _server` / `_server.get_db()`, see the route-extraction audit fix comment below), now_et,
    is_trading_day_et) is imported lazily from server -- every one has multiple OTHER callers
    still in server.py (verified before this move: none is exclusive to this route), so they
    stay there as shared infrastructure. Importing now_et/is_trading_day_et from server rather
    than time_et directly is deliberate: tests monkeypatch server.now_et to freeze "today" for
    the trading-day check below, and that patch only takes effect if this function looks the
    name up via server.now_et at call time, not a separately-bound direct import."""
    import sqlite3 as _sq

    # RC-REHAB-1 (route-extraction audit fix): `get_db` deliberately excluded from
    # this `from server import (...)` tuple -- see logger.py's identical fix comment
    # for why a blanket import eagerly resolving `get_db` raises ImportError before
    # the try/except around the banked-fallback read below (this route's own
    # designed DB-failure handling) ever gets a chance to run. `import server as
    # _server` defers resolution to the point of use, already inside that try.
    import server as _server
    from time_et import is_trading_day_et, now_et
    from gamma_surface_projection import project_gamma_surface
    from gamma_surface_state import (
        _desired_option_symbols_for_ticker,
        _gamma_surface_cell_state_counts,
        _gamma_surface_coverage_summary,
        _gamma_surface_wanted,
        _note_gamma_surface_demand,
        _option_contract_admission_summary,
        _stamp_gamma_surface_cell_stream_state,
    )
    from terrain_loop import _ticker_on_terrain_board, terrain_cache_get

    tk = ticker_storage_key(ticker or DEFAULT_TICKER)
    now = time.time()
    _note_gamma_surface_demand(tk)   # mark viewed -> the terrain loop will project this ticker's surface

    # ---- LIVE: surface projected this cycle from the canonical live terrain wide chain ----
    live = terrain_cache_get(tk)
    surf = (live or {}).get("_gamma_surface")
    if live and surf:
        # ONE freshness authority: terrain_staleness (RC-424) already merged onto the cache by
        # terrain_cache_get — serialize it verbatim, never a second age policy for the same truth.
        stale = bool(live.get("levels_stale"))
        strikes = surf.get("strikes") or []
        # Operator directive (2026-09-14, live SPX reproduction): a surface with real strikes/
        # contracts but zero cells carrying usable open interest is NOT "available" in any
        # sense an operator cares about -- `available` now reflects project_gamma_surface's
        # own gamma_available signal (computed from the SAME per-cell _has_data gate the grid
        # itself renders from), not merely "did the live cache have a surface object at all".
        # CAPS audit fix (2026-09-20): every real producer of a gamma surface
        # (project_gamma_surface and its refresh-path siblings in server.py) always
        # sets gamma_available as a computed bool (cells_with_data > 0) -- this key is
        # only ever missing on a malformed/incomplete surface. Defaulting to True in
        # that case would silently claim availability the surface cannot back up
        # (fabricating a "LIVE" signal a trader would act on); fail closed to False
        # instead, matching every other absence-has-a-type default in this file.
        _gamma_available = surf.get("gamma_available", False)  # caps-ok: fail-closed default (see comment above) -- False, never a fabricated True claim of availability
        # Always-live heatmap mandate (2026-09-15): `"live": True` above means "sourced from the
        # live terrain pathway", NOT "currently backed by a confirmed-fresh Schwab stream tick"
        # (a cold-stream surface still reaches here with cells stamped 'stale'/'unavailable' by
        # _terrain_refresh_one/refresh_gamma_surface_from_stream).
        #
        # Audit finding #6 (2026-09-16), FIXED: `stream_confirmed_live` used to mean "at least
        # one cell is live" (true with 1 of hundreds), and the field the UI actually rendered
        # a "LIVE" label from (this response's own `source`/`live` above) required NO per-cell
        # coverage at all -- a trader could see "LIVE" over a mostly stale/unavailable grid.
        # `stream_confirmed_live` is REMOVED (dead, misleadingly named, never consumed) and
        # replaced by `stream_coverage`, the ONE coverage verdict
        # (_gamma_surface_coverage_summary) with exact live/partial/stale/rejected/unavailable
        # counts and percentages, and `meets_live_requirement` gating the ONLY honest "LIVE"
        # claim: 100% of cells carrying a real contract identity, not source-path identity or
        # one live cell.
        _coverage = _gamma_surface_coverage_summary(surf)
        try:
            # Independent-review finding (2026-09-16, follow-up mandate item 1): "expose the
            # exact admitted, active, pending and rejected contracts" — a symbol-level
            # accounting, distinct from the per-cell disclosure above. Best-effort: a
            # diagnostic field must never take down the surface it is attached to.
            _contract_admission = _option_contract_admission_summary(tk)
        except Exception as _ca_e:  # institutional-swallow-ok: diagnostic-only, never load-bearing
            log.debug("contract admission summary skipped for %s: %s", tk, _ca_e)
            _contract_admission = None
        return JSONResponse({
            "ticker": tk, "symbol": tk, "available": _gamma_available,
            # "reason" (not a new field name) -- ed-gamma.js's own unavailable-branch already
            # reads surface.reason for the placeholder message; reusing it here means the
            # existing frontend contract picks this up with no client-side change required.
            # Acceptance-test fix (2026-09-20): every real producer sets gamma_available and
            # gamma_unavailable_reason together (_gamma_surface_unavailable_reason) -- so
            # `"gamma_available" not in surf` means the SAME malformed/incomplete surface the
            # fail-closed default above already detected, and surf.get("gamma_unavailable_reason")
            # would silently read back None instead of naming what actually happened.
            "reason": None if _gamma_available else (
                surf.get("gamma_unavailable_reason") if "gamma_available" in surf
                else "surface incomplete or malformed: no availability signal was computed this cycle"
            ),
            "source": "terrain_live_cache", "live": True, "stale": stale,
            "cell_stream_state_counts": _gamma_surface_cell_state_counts(surf),
            "stream_coverage": _coverage,
            "contract_admission": _contract_admission,
            "degraded": live.get("levels_stale_reason") if stale else None,
            # ONE spot faucet (operator directive, 2026-09-15): prefer the spot stamped
            # directly ON THIS SURFACE (by _terrain_refresh_one's REST cycle OR the eager
            # per-tick refresh_gamma_surface_from_stream, whichever produced this exact
            # surface_seq generation) over the top-level terrain payload's own spot fields --
            # the eager path can legitimately publish a NEWER resolve_spot value than the
            # REST cycle's own `live.get("spot")` without the top-level fields having caught
            # up, and this surface's own cells were computed from ITS stamp, not the top
            # level's. Falls back to the top-level fields only for a surface predating this
            # stamp (never expected in production, kept for defensive compatibility).
            "spot": surf.get("spot", live.get("spot")),  # caps-ok: prefer-real-A-fallback-to-real-B (see comment above) -- both sides are real measured terrain values, never a fabricated placeholder
            "spot_source": surf.get("spot_source", live.get("spot_source")),  # caps-ok: same prefer-real-A-fallback-to-real-B chain as "spot" above
            "chain_as_of_ts_utc": live.get("computed_ts_utc"),
            "spot_as_of_ts_utc": surf.get("spot_as_of_ts_utc", live.get("spot_as_of_ts_utc")),  # caps-ok: same prefer-real-A-fallback-to-real-B chain as "spot" above
            "age_sec": live.get("levels_age_sec"),            # terrain's canonical age
            "refresh_active": live.get("levels_refresh_active"),
            "chain_basis": live.get("chain_basis"),
            # coverage: the live terrain chain is strike_count-bounded (near-money), NOT the full
            # strike_range=ALL book — disclosed so the heatmap is never presented as a complete chain.
            "complete": False,
            "coverage": {
                "window": "live_near_money", "chain_basis": live.get("chain_basis"),
                "strike_count": len(strikes),
                "strike_min": (strikes[0] if strikes else None),
                "strike_max": (strikes[-1] if strikes else None),
                "expiry_count": len(surf.get("expirations") or []),
                "note": ("near-money LIVE window (strike_count-bounded terrain chain) — NOT the "
                         "full strike_range=ALL book. Proven-complete captures are per-expiry "
                         "(complete_chain_captures), not exposed by this surface"),
            },
            **_stamp_surface_session(surf, reference_date=None),
            "provenance": {
                "producer": "math_exposure_core.compute_exposures_by_strike",
                "source": "live_terrain_wide_chain (_terrain_refresh_one, strike_count-width basis)",
                "classification": "DERIVED", "cell_metric": "net_gex_1pct",
                "spot_basis": "live_resolve_spot",
            },
            "method": ("live terrain wide chain (current Greeks + live spot, this refresh cycle) -> "
                       "partition by native expirationDate -> compute_exposures_by_strike per expiry "
                       "-> net_gex_1pct cell; one producer, zero extra vendor calls"),
        })

    # ---- FALLBACK: banked MORNING wide chain — REFERENCE ONLY, never presented as intraday ----
    hit = _GAMMA_SURFACE_CACHE.get(tk)
    if hit and now - hit[0] < 300.0:
        return JSONResponse(hit[1])
    # #1-A: separate the two truths the UI must not conflate.
    #   REQUESTED = this endpoint has actually recorded demand for the surface (above).
    #   ON BOARD  = the ticker is in the ACTUAL current canonical terrain/logger board — read under
    #               the board's own lock (_ticker_on_terrain_board), NOT inferred from "a cached
    #               snapshot happens to exist". A stale snapshot is not proof of current membership.
    #   WARMING   = requested AND on the board AND the terrain producer can refresh THIS ticker right
    #               now — reusing terrain_staleness's canonical output merged onto `live`
    #               (levels_refresh_active, not quarantined, not paused). No copied scheduler policy.
    # A ticker not on the board is REQUESTED but NOT WARMING and no next refresh can occur for it —
    # the UI must say collection is not active for this symbol, never "awaiting next refresh".
    _requested = _gamma_surface_wanted(tk)
    _on_board = _ticker_on_terrain_board(tk)
    _warming = (_requested and _on_board and bool(live) and bool(live.get("levels_refresh_active"))
                and not live.get("levels_quarantined") and not live.get("levels_paused_on_purpose"))
    payload: dict = {"ticker": tk, "symbol": tk, "available": False, "source": "unavailable",
                     "live": False, "stale": True, "warming": _warming,
                     "requested": _requested, "on_board": _on_board,
                     "reason": "no live terrain surface and no banked wide chain"}
    try:
        db = _server.get_db()
        con = _sq.connect(f"file:{db.db_path}?mode=ro", uri=True, timeout=10.0)
        try:
            cand = con.execute(
                "SELECT et_date, spot, chain_json, ts_utc FROM option_chain_morning_full "
                "WHERE ticker=? ORDER BY et_date DESC LIMIT 12", (tk,)).fetchall()
        finally:
            con.close()
        # Operator directive (2026-09-14, SPX persisted-fallback hardening): a "morning
        # reference" that silently reaches back past today's session is not a morning
        # reference at all -- it is an unlabeled multi-day-old snapshot wearing the same
        # "banked_morning_reference" name as a genuine same-day one. Require the row's own
        # et_date to equal THIS session's ET date; anything older falls through to the
        # explicit "unavailable" payload above rather than being served as if it were today's.
        _today_et = now_et().strftime("%Y-%m-%d")
        rows_t = [r for r in cand if r[0] and str(r[0]) == _today_et and is_trading_day_et(str(r[0]))][:1]
        if not rows_t and any(r[0] and is_trading_day_et(str(r[0])) for r in cand):
            payload["reason"] = ("no live terrain surface; a banked wide chain exists but is "
                                  "from a prior session (not today's ET date) -- not served as "
                                  "a morning reference to avoid presenting stale data as current")
        if rows_t:
            et_date, s1, c1, ts1 = rows_t[0]
            spot1 = float(s1)
            surface = project_gamma_surface(decode_json_blob(c1), spot1)
            # Always-live heatmap mandate (2026-09-15): a banked-morning reference has no stream
            # overlay input at all -- every leg on every cell stamps 'unavailable' UNLESS the
            # daemon is already, independently, requesting that leg's contract (a genuine
            # 'pending' -- the caller is honestly waiting on the vendor, not merely looking at a
            # never-subscribed contract), consistent with "REST may bootstrap or recover the
            # surface, but it cannot satisfy LIVE".
            from app.options.order_flow.streaming import is_option_producer_daemon_available
            _stamp_gamma_surface_cell_stream_state(
                surface, {}, set(), None, set(_desired_option_symbols_for_ticker(tk)),
                daemon_available=is_option_producer_daemon_available())
            _age_sec = round(time.time() - float(ts1), 1) if ts1 is not None else None  # caps-ok: absence-has-a-type default (None, never a fabricated numeric age) when the timestamp is genuinely missing
            payload = {
                "ticker": tk, "symbol": tk, "available": True,
                "source": "banked_morning_reference", "live": False, "stale": True,
                "cell_stream_state_counts": _gamma_surface_cell_state_counts(surface),
                "stream_coverage": _gamma_surface_coverage_summary(surface),
                "warming": _warming, "requested": _requested, "on_board": _on_board,
                "degraded": ("live terrain surface unavailable — showing banked morning wide "
                             "reference (morning spot + morning Greeks; NOT intraday, NOT proven complete)"),
                "et_date": et_date, "spot": spot1,
                "chain_as_of_ts_utc": ts1, "spot_as_of_ts_utc": ts1, "age_sec": _age_sec,
                "chain_basis": "banked_morning", "complete": False,
                "coverage": {"window": "banked_morning_wide", "strike_count": len(surface.get("strikes") or []),
                             "note": ("banked morning wide reference — strike-count bounded, not intraday "
                                      "and not proven complete (not strike_range=ALL)")},
                **_stamp_surface_session(surface, reference_date=str(et_date)),
                "provenance": {
                    "producer": "math_exposure_core.compute_exposures_by_strike",
                    "source": "newest_banked_wide_chain:option_chain_morning_full",
                    "classification": "DERIVED", "cell_metric": "net_gex_1pct",
                    "spot_basis": "captured_morning_spot",
                },
                "method": ("REFERENCE: newest banked MORNING wide chain -> per-expiry "
                           "compute_exposures_by_strike; morning spot/Greeks, not intraday"),
            }
    except Exception as e:  # fail-closed to explicit unavailability
        payload = {"ticker": tk, "symbol": tk, "available": False, "source": "unavailable",
                   "live": False, "stale": True, "warming": _warming,
                   "requested": _requested, "on_board": _on_board,
                   "reason": f"gamma-surface read failed: {e}"}
    _GAMMA_SURFACE_CACHE[tk] = (now, payload)
    return JSONResponse(payload)


# Gamma-surface route cache and session stamping (moved from server.py, RC-REHAB-1 forty-
# seventh slice): /api/options/gamma-surface is their only consumer.
# RC-UI-1: strike × expiry GEX surface for the rebuilt Options→Gamma heatmap. A PROJECTION over the
# one canonical exposure authority, not a second producer: it partitions a wide chain by native
# expirationDate (via the existing _filter_contracts_by_selected_expiry slice) and invokes
# math_exposure_core.compute_exposures_by_strike per slice, shaping net_gex_1pct cells into a grid.
# No gamma/GEX/multiplier/OI/spot/sign/missingness math lives here.
# SOURCE (current, post live-terrain rewire): PREFERRED is the live terrain projection —
# _terrain_refresh_one projects it from the live wide chain + live spot it already fetches each cycle
# and caches it (in-memory, zero extra vendor calls), demand-gated to viewed tickers. FALLBACK is the
# banked MORNING wide reference (one DB read, 5-min cache) — labelled stale/not-intraday, never live.
_GAMMA_SURFACE_CACHE: dict = {}


def _stamp_surface_session(surface: dict, *, reference_date: Optional[str]) -> dict:
    """Session identity for a projected surface, stamped by the ONE ET clock (server side — a
    browser never decides what day it is): today's ET session date, whether the surface is a
    PRIOR-session reference (a banked capture from an earlier trading day viewed today), and which
    expiration columns have already expired relative to today. Presentation reads these flags to
    label an expired 0DTE column and a prior-session reference for what they are; it never infers
    them. No cell value is touched."""
    today = now_et().strftime("%Y-%m-%d")      # time_et: the ONE ET clock / session-calendar authority
    out = dict(surface)
    out["expirations"] = [
        dict(e, expired=bool(e.get("expiry") and str(e["expiry"]) < today))
        for e in (surface.get("expirations") or [])
    ]
    out["session_date_et"] = today
    out["prior_session"] = bool(reference_date and str(reference_date) < today)
    return out
