"""Tier A live-state builder (server.py decomposition, twenty-sixth slice,
RC-REHAB-1, 2026-09-23), for GET /api/live/state.

_tier_a_live_state_dict moves here verbatim. It is not a _fetch_state phase (no
server_state_ prefix): /api/live/state is a deliberately lightweight route --
live_market_plane + an optional single REST quote bootstrap, no chain, exposures,
build_market_state, DB, news, or model health -- called directly from
app/api/routes/live.py (also `from server import _tier_a_live_state_dict`
externally, so server.py keeps a re-export).

MONKEYPATCH/RUNTIME-STATE NOTE: every server.py-local name this function touches
(get_client, _schwab_auth_http_unavailable, _plane_fast_quote_has_spot,
_memoized_quote_response, _parse_quote_node_session_fields, resolve_spot,
_chg_pct_with_rest_backfill, current_spot_state, _latest_cache_entry_for_ticker,
_state_cache, _lmp) has a confirmed OTHER caller elsewhere in server.py -- checked
individually before this slice, not assumed -- so all stay in server.py, reached
via the established lazy `import server` pattern.

_derive_session (market_context.py) is re-imported here directly from its own
module -- not server.py-specific logic. resolve_chg_pct (market_context.py),
float_finite_or_none (numeric_contract.py), and get_streaming_diagnostics/
get_plane_authority_for_ticker (app.options.order_flow.streaming) were already
lazily imported inline inside the function body in the original code and stay
that way, unchanged.
"""
from __future__ import annotations

import time
from typing import Optional

from fastapi import HTTPException
from market_context import _derive_session


def _tier_a_live_state_dict(ticker: str, expiry: Optional[str]) -> dict:
    """
    Tier A — live-only JSON for GET /api/live/state.
    live_market_plane + optional single REST quote bootstrap. No chain, exposures,
    build_market_state, DB, news, or model health. Session from ET clock only.
    """
    import server as _srv

    t0_mono = time.monotonic()
    tkr = ticker.upper().strip()
    sess = _derive_session()
    row = _srv._lmp.get_quote(tkr)
    client = None
    try:
        client = _srv.get_client()
    except HTTPException as he:
        if _srv._schwab_auth_http_unavailable(he) and not _srv._plane_fast_quote_has_spot(row):
            return {
                "_tier": "A_live",
                "ticker": tkr,
                "selected_exp": expiry,
                "session_label": sess,
                "state_error": "token_invalid",
                "error": "token_invalid",
                "state_error_detail": str(he.detail or ""),
                "remediation": "Run: python reauth_schwab.py --manual",
                "_server_build_ts": time.time(),
                "_pipeline_ms": round((time.monotonic() - t0_mono) * 1000),
                "_endpoint": "/api/live/state",
            }
        client = None
    # Operator-reproduced defect (2026-09-14, spot 360 audit): this gate previously trusted
    # ANY plane row with a spot, however old — if the streaming websocket silently stalled,
    # the header kept painting that stopped price as live forever, with no fallback, while
    # resolve_spot()'s OWN new plane leg (the same ~30s freshness boundary)
    # would already have fallen through to a fresher REST quote — reopening the exact
    # divergence this file's spot authority exists to prevent, just in the other direction.
    # An over-age row is now treated the same as no row: fall through to the REST bootstrap.
    #
    # Operator-reproduced defect, round 2 (LIVE, 2026-09-14): the pre-existing `and client`
    # gate here silently abandoned this bootstrap whenever the EARLIER get_client() call (the
    # try/except above, whose only job is a DIFFERENT question -- "is there a plane row to
    # fall back on at all if auth is down") happened to raise -- leaving `client = None` with
    # no retry, ever, for THIS request. Before this file had any freshness concept that was a
    # harmless no-op (the plane was trusted regardless), so a transient auth hiccup was
    # invisible. Now that a stale row is correctly rejected above, that same transient hiccup
    # left the header STUCK: MEASURED live, a plane row 2.9 hours old kept being served
    # (quote_ingestion: schwab_streaming_level_one, unchanged) across repeated requests, while
    # /api/fast-quote -- which resolves get_client() itself, independently, on every call --
    # succeeded immediately and returned a genuinely fresh price. _memoized_quote_response
    # already resolves its own client when none is supplied; call it that way and let it
    # retry, instead of trusting a client this function decided not to need for anything else.
    _row_fresh = bool(row) and _srv._lmp.quote_is_fresh(row)
    _quote_node_for_resolve = None
    if not row or row.get("spot") is None or not _row_fresh:
        q_resp = None
        try:
            q_resp = _srv._memoized_quote_response(tkr, client=client)   # RC-112/W3-C8: one vendor faucet
        except HTTPException:
            # get_client() failed again on this attempt too -- fall through to whatever `row`
            # already holds (a stale-but-present plane row, honestly labelled by its own
            # quote_ingestion/server_received_ts, or the "no_quote" fail-closed response
            # below if there was never a row at all). Never a silent 500 for a display route.
            pass
        if q_resp and q_resp.status_code == 200:
            q_json = q_resp.json()
            _node = q_json.get(tkr.upper()) or q_json.get(tkr) or {}
            _quote_node_for_resolve = _node
            pq = _srv._parse_quote_node_session_fields(_node)
            spot_source = pq["spot_source"]
            spot = pq["spot"]
            bid, ask = pq["bid"], pq["ask"]
            if spot and float(spot) > 0:
                sf = float(spot)
                quote_ts = pq["quote_ts"]
                server_received_ts = time.time()
                from market_context import resolve_chg_pct
                chg_pct = resolve_chg_pct(tkr, pq.get("chg_pct"))
                row = {
                    "ticker": tkr,
                    "spot": sf,
                    "chg_pct": chg_pct,
                    "bid": bid,
                    "ask": ask,
                    "spot_disp": f"{sf:.2f}",
                    "bid_disp": f"{float(bid):.2f}" if bid is not None else "—",
                    "ask_disp": f"{float(ask):.2f}" if ask is not None else "—",
                    "spread": None,
                    "spread_pts": None,
                    "quote_ingestion": "rest_tier_a",
                    "exchange_quote_ts": quote_ts,
                    "quote_time_source": "schwab_rest_quote" if quote_ts is not None else "unavailable",
                    "server_received_ts": server_received_ts,
                    "fast_generation_id": _srv._lmp.next_fast_generation(tkr),
                    "quote_source_detail": {
                        "spot": "LAST_PRICE" if spot_source == "lastPrice" else None,
                        "bid": "bidPrice" if bid is not None else "unavailable_missing_bid",
                        "ask": "askPrice" if ask is not None else "unavailable_missing_ask",
                        "mid": "unavailable_missing_mark_and_bid_ask",
                        "spread": "unavailable_missing_bid_or_ask",
                        "quote_ts": pq["quote_ts_clock"],  # M6: exchange clock carried in exchange_quote_ts
                        "carried_forward": False,
                    },
                }
                mid = pq["quote_mid"]
                mid_src = pq["mid_source"]
                if mid is not None:
                    row["quote_mid"] = mid
                    row["mid_source"] = mid_src
                row["quote_source_detail"]["mid"] = mid_src or "unavailable_missing_mark_and_bid_ask"
                if bid is not None and ask is not None:
                    try:
                        b_px, a_px = float(bid), float(ask)
                        raw_spread = round(a_px - b_px, 4)
                        row["spread_pts"] = raw_spread if raw_spread >= 0.0 else None
                        row["spread_pts_source"] = "derived_bid_ask_pts"
                        if mid is not None and mid > 0:
                            row["spread"] = (a_px - b_px) / mid
                            row["spread_source"] = (
                                "derived_bid_ask_mid_fraction"
                                if mid_src == "derived_bid_ask_mid"
                                else "derived_bid_ask_fraction_schwab_mark_denom"
                            )
                        row["quote_source_detail"]["spread"] = "schwab_bid_ask"
                    except (TypeError, ValueError):
                        pass
    if not row or row.get("spot") is None:
        return {
            "_tier": "A_live",
            "ticker": tkr,
            "selected_exp": expiry,
            "session_label": sess,
            "state_error": "no_quote",
            "state_error_detail": "No live plane or REST quote available yet.",
            "_server_build_ts": time.time(),
            "_pipeline_ms": round((time.monotonic() - t0_mono) * 1000),
            "_endpoint": "/api/live/state",
        }
    # ONE spot faucet (operator directive, 2026-09-15, repo-wide audit): this route used to
    # decide spot purely from its OWN plane-then-REST precedence check (_row_fresh above) --
    # a second, independently-coded implementation of resolve_spot's exact same precedence,
    # not a call to it (resolve_spot's own docstring already documented this exact bypass as
    # a known, unfixed gap: "the header/analytics stack... reads [the plane] directly,
    # bypassing this function entirely"). The decision criteria are structurally identical
    # (same _lmp.get_quote/_lmp.quote_is_fresh calls, same REST-quote fallback), so this call
    # reuses the quote node already fetched above (no second vendor round-trip) and simply
    # makes resolve_spot's own answer authoritative for the SERVED number, instead of trusting
    # a parallel implementation that could theoretically diverge from it. allow_stored=False
    # preserves this endpoint's existing "Tier A — live-only... no chain/DB" contract: an
    # outage still fails closed to no_quote below, never silently serves a stored snapshot.
    _rs_spot, _rs_source, _rs_ts = _srv.resolve_spot(tkr, quote_node=_quote_node_for_resolve, allow_stored=False)
    if _rs_spot is None:
        # Independent review, 2026-09-16 (CORRECTED): the first version of this fix fell back
        # to row["spot"] here -- exactly the "a consumer independently selects/serves a second
        # source when the ONE authority has nothing" pattern this whole change exists to ban,
        # reintroduced by the fix itself. Structurally this branch should not fire (identical
        # precedence to what built `row`), but "should not happen" is not a license to serve a
        # value resolve_spot did not produce. Fail closed instead, the same contract every
        # other resolve_spot-backed route in this file already uses.
        _srv.log.warning("Tier A live/state: resolve_spot found nothing for %s while row had a "
                    "spot (%.4f) -- failing closed rather than serving row's own value, this "
                    "divergence should not happen given identical precedence and needs "
                    "investigation.", tkr, float(row["spot"]))
        return {
            "_tier": "A_live",
            "ticker": tkr,
            "selected_exp": expiry,
            "session_label": sess,
            "state_error": "no_quote",
            "state_error_detail": "No live plane or REST quote available yet.",
            "_server_build_ts": time.time(),
            "_pipeline_ms": round((time.monotonic() - t0_mono) * 1000),
            "_endpoint": "/api/live/state",
        }
    spot_f = float(_rs_spot)
    from numeric_contract import float_finite_or_none as _fin
    # single source: finite bid/ask (raw float() admitted NaN into spread AND the bid/ask
    # echoed into `out` below); canonical reader also removes the try/except.
    bid = _fin(row.get("bid"))
    ask = _fin(row.get("ask"))
    spread_dollar = None
    if bid is not None and ask is not None:
        spread_dollar = round(ask - bid, 4)
    chg_pct = _srv._chg_pct_with_rest_backfill(tkr, row, client=client)
    out: dict = {
        "_tier": "A_live",
        "ticker": tkr,
        "selected_exp": expiry,
        "session_label": sess,
        "spot": spot_f,
        "spot_source": _rs_source,
        "spot_state": _srv.current_spot_state(_rs_source, tkr),
        "spot_as_of_ts_utc": _rs_ts,
        "chg_pct": chg_pct,
        "bid": bid,
        "ask": ask,
        "spot_disp": f"{spot_f:.2f}",
        "bid_disp": row.get("bid_disp"),
        "ask_disp": row.get("ask_disp"),
        "quote_mid": row.get("quote_mid"),
        "mid_source": row.get("mid_source"),
        "spread": spread_dollar,
        "spread_semantic": "dollar",
        "spread_pts": row.get("spread_pts"),
        "spread_source": (
            "derived_bid_ask_pts"
            if spread_dollar is not None
            else row.get("spread_source")
        ),
        "spread_pts_source": row.get("spread_pts_source"),
        "quote_source_detail": row.get("quote_source_detail"),
        "quote_ingestion": row.get("quote_ingestion"),
        "quote_time_source": row.get("quote_time_source"),
        "server_received_ts": row.get("server_received_ts"),
        "exchange_quote_ts": row.get("exchange_quote_ts"),
        "fast_generation_id": row.get("fast_generation_id"),
        "_live_plane_fast_ts": row.get("exchange_quote_ts"),
        "_server_build_ts": time.time(),
        "_pipeline_ms": round((time.monotonic() - t0_mono) * 1000),
        "_endpoint": "/api/live/state",
    }
    try:
        from app.options.order_flow.streaming import get_streaming_diagnostics, get_plane_authority_for_ticker

        out["streaming_plane"] = {
            **get_streaming_diagnostics(),
            "plane_quote_authority": get_plane_authority_for_ticker(tkr),
        }
    except Exception:
        out["streaming_plane"] = {}
    lw: dict = {}
    ck_hit: Optional[dict] = None
    if expiry:
        c = _srv._state_cache.get((tkr, expiry))
        if c and c.get("ms_dict"):
            ck_hit = c
    if ck_hit is None:
        h2 = _srv._latest_cache_entry_for_ticker(tkr)
        if h2:
            ck_hit = h2[1]
    if ck_hit and ck_hit.get("ms_dict"):
        md0 = ck_hit["ms_dict"]
        for k in (
            "vix",
            "pcr_val",
            "spy_chg_pct",
            "qqq_chg_pct",
            "iwm_chg_pct",
            "spy_last",
            "qqq_last",
            "iwm_last",
            "dte_warn",
            "dte_color",
        ):
            if k in md0 and md0[k] is not None:
                lw[k] = md0[k]
        # The Tier C bundle's own generation (the SAME entry-level analytics_version every
        # /api/analytics/state response carries via _attach_analytics_freshness_contract), so a
        # consumer that caches a Tier C value (the shell's put/call OI row) can see the
        # generation advance on the plane it already polls and re-read ONCE — never per tick,
        # never forever stale. Not a second clock: it is the bundle's existing identity.
        _ver = ck_hit.get("analytics_version")
        if _ver is not None:
            lw["analytics_version"] = int(_ver)
    if lw:
        out["analytics_lightweight"] = lw
    _srv._lmp.merge_into_state(out, tkr)
    # merge_into_state (correctly, per its own fix) overwrites chg_pct unconditionally
    # whenever the CURRENT plane row carries the key at all, including a stale/None value —
    # that row was never told about the resolve_chg_pct/backfill result just computed above
    # (this route intentionally does not write its transient backfill into the shared plane
    # cache), so a stale plane-row chg_pct here would silently undo it. The value already
    # resolved above is this response's actual answer; re-assert it as the last word.
    out["chg_pct"] = chg_pct
    return out
