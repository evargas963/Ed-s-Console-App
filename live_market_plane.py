"""
Layer A — authoritative in-process live quote plane (Ed Console).

Canonical quote fields per ticker are updated primarily from Schwab **streaming**
`LEVEL_ONE_EQUITY` WebSocket rows (`record_from_level_one_equity`). REST `/api/fast-quote`
remains a secondary / fallback path (`record_quote` from `_fetch_fast_quote_payload`).

Tier A `GET /api/live/state` and optional SSE `live_quote` events read this plane so
visible spot/bid/ask track the latest row. Tier B `GET /api/analytics/light` merges the
plane for live spot vs cached structure + order-flow engine input. Full analytical payloads
(`GET /api/analytics/state`, legacy `GET /api/state`, `_fetch_state`) also merge from the plane.

Layers (see server lifespan / architecture docs):
  A — Tick/quote plane (this module)
  B — Client fast mark-to-market (reads plane via HTTP + SSE live_quote)
  C — Analytical refresh (`_fetch_state`, SSE full snapshots)
  D — Persistence (DB, outcomes, training) — never on quote hot path
"""

from __future__ import annotations

import threading
import time
from typing import Any, Optional


_lock = threading.RLock()
# ticker UPPER -> last plane payload (streaming and/or REST fast quote)
_by_ticker: dict[str, dict[str, Any]] = {}
# ticker -> last fast_generation_id we pushed on SSE live_quote (coalesce duplicate rows)
_last_sse_pushed_gen: dict[str, float] = {}

_gen_lock = threading.Lock()
_fast_lane_gen_by_ticker: dict[str, int] = {}


def next_fast_generation(ticker: str) -> int:
    """Monotonic per-ticker generation for SSE coalescing (independent of decision_generation_id)."""
    t = (ticker or "").upper().strip()
    with _gen_lock:
        n = _fast_lane_gen_by_ticker.get(t, 0) + 1
        _fast_lane_gen_by_ticker[t] = n
        return n


def _safe_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        x = float(val)
    except (TypeError, ValueError):
        return None
    if x != x:  # NaN
        return None
    return x


def _plane_tuple_sig(spot: Any, bid: Any, ask: Any) -> tuple[Optional[float], Optional[float], Optional[float]]:
    return (
        round(spot, 6) if spot is not None else None,
        round(bid, 6) if bid is not None else None,
        round(ask, 6) if ask is not None else None,
    )


def _positive_float(val: Any) -> Optional[float]:
    f = _safe_float(val)
    if f is None or f <= 0:
        return None
    return f


def _epoch_seconds_from_millis(val: Any) -> Optional[float]:
    f = _safe_float(val)
    if f is None or f <= 0:
        return None
    return f / 1000.0


def record_from_level_one_equity(ticker: str, item: dict[str, Any]) -> bool:
    """
    Ingest one Schwab streaming LEVEL_ONE_EQUITY content row into the plane.
    Returns True if the stored row changed (new generation recorded).
    """
    if not item or not isinstance(item, dict):
        return False
    t = (ticker or "").upper().strip()
    if not t:
        return False

    last = _positive_float(item.get("LAST_PRICE"))
    mark = _positive_float(item.get("MARK"))
    bid = _positive_float(item.get("BID_PRICE")) or _positive_float(item.get("BID"))
    ask = _positive_float(item.get("ASK_PRICE")) or _positive_float(item.get("ASK"))

    with _lock:
        prev = _by_ticker.get(t)
        pspot = prev.get("spot") if prev else None
        pbid = prev.get("bid") if prev else None
        pask = prev.get("ask") if prev else None

    spot_f = last or mark
    spot_source = "LAST_PRICE" if last is not None else ("MARK" if mark is not None else None)
    bid_source = "BID_PRICE" if _positive_float(item.get("BID_PRICE")) is not None else ("BID" if bid is not None else None)
    ask_source = "ASK_PRICE" if _positive_float(item.get("ASK_PRICE")) is not None else ("ASK" if ask is not None else None)

    if spot_f is None or spot_f <= 0:
        return False

    quote_ts = (
        _epoch_seconds_from_millis(item.get("QUOTE_TIME_MILLIS"))
        or _epoch_seconds_from_millis(item.get("TRADE_TIME_MILLIS"))
    )
    new_sig = _plane_tuple_sig(spot_f, bid, ask)
    prev_sig = _plane_tuple_sig(pspot, pbid, pask) if prev else None
    prev_quote_ts = (prev or {}).get("fast_server_ts")
    if (
        prev_sig == new_sig
        and (prev or {}).get("quote_ingestion") == "schwab_streaming_level_one"
        and (quote_ts is None or prev_quote_ts == quote_ts)
    ):
        return False

    spread_frac = None
    quote_mid = None
    mid_source = None
    try:
        if mark is not None:
            mark_f = float(mark)
            if mark_f > 0:
                quote_mid = mark_f
                mid_source = "schwab_streaming_mark"
        if quote_mid is not None and bid is not None and ask is not None:
            bf, af = float(bid), float(ask)
            spread_frac = (af - bf) / quote_mid
    except (TypeError, ValueError):
        pass

    server_received_ts = time.time()
    out = {
        "ticker": t,
        "spot": float(spot_f),
        "bid": float(bid) if bid is not None else None,
        "ask": float(ask) if ask is not None else None,
        "spot_disp": f"{float(spot_f):.2f}",
        "bid_disp": f"{float(bid):.2f}" if bid is not None else "—",
        "ask_disp": f"{float(ask):.2f}" if ask is not None else "—",
        "quote_mid": quote_mid,
        "mid_source": mid_source,
        "spread": spread_frac,
        "spread_pts": round(float(ask) - float(bid), 4) if bid is not None and ask is not None else None,
        "spread_source": (
            "derived_bid_ask_mid_fraction"
            if spread_frac is not None and mid_source == "derived_bid_ask_mid"
            else (
                "derived_bid_ask_fraction_schwab_mark_denom"
                if spread_frac is not None and mid_source == "schwab_streaming_mark"
                else None
            )
        ),
        "spread_pts_source": (
            "derived_bid_ask_pts" if bid is not None and ask is not None else None
        ),
        "fast_generation_id": next_fast_generation(t),
        "fast_server_ts": quote_ts,
        "quote_time_source": "schwab_streaming_level_one" if quote_ts is not None else "unavailable",
        "server_received_ts": server_received_ts,
        "quote_ingestion": "schwab_streaming_level_one",
        "quote_source_detail": {
            "spot": spot_source,
            "bid": bid_source,
            "ask": ask_source,
            "mid": mid_source or "unavailable_missing_mark_and_bid_ask",
            "spread": "schwab_bid_ask" if bid is not None and ask is not None else "unavailable_missing_bid_or_ask",
            "carried_forward": False,
            "previous_spot_available": pspot is not None,
            "previous_bid_available": pbid is not None,
            "previous_ask_available": pask is not None,
        },
    }
    with _lock:
        _by_ticker[t] = out
    try:
        from planes.l1_events import notify_quote_updated

        notify_quote_updated(t)
    except Exception:
        pass
    return True


def record_quote(ticker: str, payload: dict[str, Any]) -> None:
    """Persist a full plane row (e.g. REST fast-quote). Replaces prior row for ticker."""
    t = (ticker or "").upper().strip()
    if not t:
        return
    with _lock:
        _by_ticker[t] = dict(payload)
    try:
        from planes.l1_events import notify_quote_updated

        notify_quote_updated(t)
    except Exception:
        pass


def get_quote(ticker: str) -> Optional[dict[str, Any]]:
    """Copy of latest plane row for ticker, or None."""
    t = (ticker or "").upper().strip()
    with _lock:
        row = _by_ticker.get(t)
        return dict(row) if row else None


def merge_into_state(ms_dict: dict[str, Any], ticker: str) -> None:
    """
    Tier C only: overlay spot/bid/ask/display fields from the live plane onto an analytical ms_dict.
    Call at end of _fetch_state before return so Layer C payloads carry Layer A truth.

    Does not write to Layer A storage (_by_ticker). For L1 read-path overlay, use
    apply_l1_live_quote_overlay (same field merge, explicit L1 contract).
    """
    q = get_quote(ticker)
    if not q:
        return
    for k in (
        "spot",
        "bid",
        "ask",
        "spot_disp",
        "bid_disp",
        "ask_disp",
        "quote_mid",
        "mid_source",
        "spread",
        "spread_pts",
        "spread_source",
        "spread_pts_source",
        "quote_ingestion",
    ):
        if k in q and q[k] is not None:
            ms_dict[k] = q[k]
    fts = q.get("fast_server_ts")
    if fts is not None:
        ms_dict["_live_plane_fast_ts"] = fts
    ms_dict["_quote_authority"] = "live_market_plane"


def apply_l1_live_quote_overlay(l1_payload: dict[str, Any], ticker: str) -> None:
    """
    L1 only: merge current Layer A quote fields onto an L1 snapshot dict for HTTP cache reads.

    Part of server-side Tier B full_overlay assembly (Issue 28): invoked from server._l1_http_get_projection
    on cache hits — same path feeds GET /api/analytics/light and SSE payload; the client does not re-apply
    this overlay to Tier B semantics.

    Reads from _by_ticker via get_quote; never writes Layer A storage. Layer A remains pure
    quote rows — L1 semantics (structural, OF, merge metadata) never flow into _by_ticker.
    """
    q = get_quote(ticker)
    if not q:
        return
    for k in (
        "spot",
        "bid",
        "ask",
        "spot_disp",
        "bid_disp",
        "ask_disp",
        "quote_mid",
        "mid_source",
        "spread",
        "spread_pts",
        "spread_source",
        "spread_pts_source",
        "quote_ingestion",
    ):
        if k in q and q[k] is not None:
            l1_payload[k] = q[k]
    fts = q.get("fast_server_ts")
    if fts is not None:
        l1_payload["_live_plane_fast_ts"] = fts
    l1_payload["_quote_authority"] = "live_market_plane"
    l1_payload["l1_live_overlay_applied"] = True


def take_fresh_sse_quote_payload(ticker: str) -> Optional[dict[str, Any]]:
    """
    If the plane has a quote row not yet sent on SSE for this ticker (by fast_generation_id),
    return a payload for event: live_quote. Otherwise None.
    """
    t = (ticker or "").upper().strip()
    with _lock:
        row = _by_ticker.get(t)
        if not row:
            return None
        fg = row.get("fast_generation_id")
        if fg is None:
            return None
        prev = _last_sse_pushed_gen.get(t)
        if prev is not None and fg == prev:
            return None
        _last_sse_pushed_gen[t] = float(fg)
    out = dict(row)
    out["_plane_layer"] = "tick"
    out["_update_source"] = "live_plane_sse"
    return out


def reset_sse_push_cursor(ticker: str) -> None:
    """Force next SSE live_quote push (e.g. after ticker change)."""
    t = (ticker or "").upper().strip()
    with _lock:
        _last_sse_pushed_gen.pop(t, None)
