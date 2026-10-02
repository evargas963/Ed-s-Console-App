"""RC-UI-1 — proof that /api/options/gamma-surface PREFERS the live terrain surface, borrows its
freshness from the ONE authority (terrain_staleness via terrain_cache_get, RC-424) rather than a
second age policy, discloses its coverage (the full chain the levels were priced from), and
never presents the banked morning snapshot as intraday."""
import json
import time
from datetime import datetime
from pathlib import Path

import pytest

import server
from calibration.complete_chain_capture import CAPTURE_BASIS
from db import EdDB
from server import get_options_gamma_surface, ticker_storage_key
from time_et import ET

_SURF = {
    "expirations": [{"expiry": "2026-09-11", "dte": 2}], "strikes": [580.0, 583.0, 586.0],
    "cells": [{"strike": 580.0, "gex": [-90000]}, {"strike": 583.0, "gex": [958600]},
              {"strike": 586.0, "gex": [-264500]}],
    "contracts_total": 3, "contracts_used": 3, "contracts_excluded_malformed_expiry": 0,
    # the spot THIS surface was computed from, stamped on it by its producer (served as-is;
    # no fall-through to the terrain payload's own spot)
    "spot": 583.41, "spot_source": "streaming_plane", "spot_as_of_ts_utc": 1.0,
}


def _call(tk):
    return json.loads(get_options_gamma_surface(tk).body)


def _put_live(tk, *, computed_ts):
    with server._terrain_cache_lock:
        server._terrain_cache[tk] = {
            "_gamma_surface": _SURF, "computed_ts_utc": computed_ts, "spot": 583.41,
            "spot_source": "last", "spot_as_of_ts_utc": computed_ts, "chain_basis": "full",
        }


def _clear(tk):
    with server._terrain_cache_lock:
        server._terrain_cache.pop(tk, None)


def test_live_terrain_surface_is_preferred_and_discloses_coverage(monkeypatch):
    monkeypatch.setattr("server.resolve_spot", lambda tk, **_k: (584.0, "live_quote", time.time()))
    tk = ticker_storage_key("SPY")
    _clear(tk); _put_live(tk, computed_ts=time.time())
    try:
        d = _call(tk)
        assert d["source"] == "terrain_live_cache" and d["live"] is True
        assert [{"strike": c["strike"], "gex": c["gex"]} for c in d["cells"]] == _SURF["cells"]  # served verbatim
        assert [c["spot"] for c in d["cells"]] == [False, True, False]   # the live 584 is nearest the 583 row
        # the live price, and the price the cells were computed at, each named
        assert d["spot"] == 584.0 and d["priced_at_spot"] == 583.41
        assert d["provenance"]["spot_basis"] == "live_resolve_spot"
    finally:
        _clear(tk)


def test_freshness_is_the_one_terrain_authority_not_a_second_policy(monkeypatch):
    # gamma-surface freshness must EQUAL terrain_cache_get's canonical freshness, field-for-field.
    # The clock is held still: the two reads compared ages taken at two real instants and failed
    # when a loaded machine put 2.5 s between them (2026-09-27).
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now)
    tk = ticker_storage_key("SPY")
    _clear(tk); _put_live(tk, computed_ts=now - 240)   # 4 min old — a 5-min roster cadence is legitimate
    try:
        live = server.terrain_cache_get(tk)                    # the one authority
        d = _call(tk)
        assert d["stale"] == bool(live.get("levels_stale"))
        assert d["age_sec"] == live.get("levels_age_sec") == 240.0   # one authority, one as-of
        expected_reason = live.get("levels_stale_reason") if bool(live.get("levels_stale")) else None
        assert (d["degraded"] or None) == expected_reason
        # no separate 180s threshold survives on the module
        assert not hasattr(server, "GAMMA_SURFACE_LIVE_STALE_SEC")
    finally:
        _clear(tk)


def _board_is(board):
    """The capture daemon's heartbeat, carrying its board (the console's one source for it)."""
    import live_market_plane as lmp
    now = time.time()
    lmp.record_feed_heartbeat({"ts": now, "schwab_socket_open": True, "board": list(board)}, now)


def test_a_viewed_ticker_warms_at_any_hour(monkeypatch, pin_clock, view):
    # WARMING: viewed. The daemon fetches the viewed ticker's chain at any hour, so a Saturday is
    # warming too (it read "not warming" outside the archival window before).
    pin_clock(2026, 9, 26, 12, 0)
    tk = ticker_storage_key("SPY")
    with server._terrain_cache_lock:
        server._terrain_cache[tk] = {"computed_ts_utc": time.time(), "spot": 100.0}   # on the board, no surface yet
    _board_is([tk])                                                      # enrolled like any ticker -- no built-in list
    view(tk)                                                             # a page open on it
    try:
        d = _call(tk)
        assert d["warming"] is True and d["requested"] is True
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)


# ── any viewed ticker, on the board or not (2026-09-28 audit) ────────────────────────────────
# Warming read "a snapshot already exists" (true for board tickers, priced at startup) instead of
# the refresh state; a closed market gave /api/terrain "no capture" without looking for one while
# the surface route priced the stored capture; ATR absent showed a bare dash. One rule each.

_BOARD, _OFF = "NFLX", "ZZQX"                      # ZZQX: an arbitrary symbol, never on the board
_CRWD = json.loads((Path(__file__).parent / "fixtures" / "real_crwd_complete_chain_quarter.json")
                   .read_text(encoding="utf-8"))
_CAPTURED = datetime(2026, 9, 2, 10, 5, tzinfo=ET).timestamp()   # the CRWD chain's capture


@pytest.fixture
def _fresh(monkeypatch, tmp_path, view):
    edb = EdDB(tmp_path / "ed.db")
    monkeypatch.setattr(server, "get_db", lambda: edb)
    _board_is([_BOARD])
    monkeypatch.setattr(server, "_terrain_cache", {})
    monkeypatch.setattr(server, "_terrain_refresh_last_error", {})
    monkeypatch.setattr(server, "_desired_stream_greeks_for_ticker", lambda tk, listed=None: {})
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **k: (_CRWD["spot"], "stub", _CAPTURED))
    return edb


@pytest.mark.parametrize("tk", [_BOARD, _OFF])
def test_first_view_warms_any_ticker_on_or_off_the_board(_fresh, monkeypatch, view, tk):
    """A viewed ticker is the daemon's active ticker, whose chain it fetches ahead of every
    other, on the board or not (operator 2026-10-01)."""
    view(tk)                                        # the page selects the ticker
    d = _call(tk)                                   # the first view: no levels published yet
    assert d["requested"] is True and d["warming"] is True
    assert d["reason"] == "no terrain snapshot has been computed yet"


@pytest.mark.parametrize("tk", [_BOARD, _OFF])
def test_a_ticker_open_on_a_page_is_viewed_until_the_page_leaves_it(_fresh, monkeypatch, view, tk):
    """2026-09-28 audit: "viewed" was a 300 s timer renewed only by the levels, chain and heatmap
    routes, which the Liquidity and Order Flow workspaces do not read -- an off-board ticker
    shown there stopped refreshing 300 s after it was chosen (a board ticker refreshes anyway).
    The page's one connection is the one viewing signal: a route read does not make a ticker
    viewed, and the ticker stays viewed for as long as the page has it open."""
    import push_changes
    _call(tk)                                       # a route read alone: not viewed
    assert not server._gamma_surface_wanted(tk)
    (client,) = view(tk)                            # /api/changes open on this ticker
    assert server._gamma_surface_wanted(tk)
    push_changes.unsubscribe(tk, client)            # the page closed or changed ticker
    assert not server._gamma_surface_wanted(tk)


def test_a_chain_schwab_refused_says_schwabs_answer(_fresh, view):
    """The daemon's chain fetch failed: the ticker's reason is Schwab's answer, delivered by the
    daemon (no console fetch, no hold)."""
    view(_BOARD)
    server._on_chain(_BOARD, None, _CAPTURED, "full chain returned HTTP 400")
    d = _call(_BOARD)
    assert d["warming"] is True
    assert d["reason"] == ("no terrain snapshot has been computed yet — "
                           "chain fetch failed (full chain returned HTTP 400)")


@pytest.mark.parametrize("tk", [_BOARD, _OFF])
def test_with_no_levels_the_atr_is_served_with_its_reason(_fresh, monkeypatch, tk):
    t = server.get_terrain(ticker=tk)
    # ATR is from the bars, not the chain: served (here absent, with its reason) with no levels
    assert t["atr_daily"] is None and "0 trading days" in t["atr_daily_reason"]


@pytest.mark.parametrize("tk", [_BOARD, _OFF])
def test_a_refresh_publishes_the_same_fields_for_any_ticker(_fresh, monkeypatch, pin_clock, view, tk):
    pin_clock(2026, 9, 2, 10, 5)
    view(tk)                                        # selected on the page
    server._publish_levels(tk, [dict(c) for c in _CRWD["chain"]], _CAPTURED)
    t = server.get_terrain(ticker=tk)
    assert t["chain_basis"] == CAPTURE_BASIS
    assert t["atr_15m"] is None and "0 15-minute periods" in t["atr_15m_reason"]
    assert _call(tk)["available"] is True


def test_surface_session_identity_is_stamped_by_the_server_clock():
    """Real-data repair 2026-09-10: a banked 2026-09-09 reference viewed on 2026-09-10 rendered its
    expired 0DTE column as current structure. The server (the ONE ET clock) stamps each column
    `expired` and the nearest unexpired one `front`; presentation reads these, never a browser
    clock. Cell values are untouched."""
    tk = ticker_storage_key("SPY")
    surf = dict(_SURF, expirations=[{"expiry": "2000-01-03", "dte": 0}, {"expiry": "2999-01-15", "dte": 9}])
    _clear(tk)
    with server._terrain_cache_lock:
        server._terrain_cache[tk] = {"_gamma_surface": surf, "computed_ts_utc": time.time(), "spot": 583.41,
                                     "spot_source": "last", "spot_as_of_ts_utc": time.time(), "chain_basis": "full"}
    try:
        d = _call(tk)
        assert [e["expired"] for e in d["expirations"]] == [True, False]
        assert [e["front"] for e in d["expirations"]] == [False, True]
        assert [{"strike": c["strike"], "gex": c["gex"]} for c in d["cells"]] == _SURF["cells"]  # values untouched
        assert not any(c["spot"] for c in d["cells"])   # no live price here: no row is marked as the price
    finally:
        _clear(tk)


def test_fallback_is_labelled_not_live_never_intraday():
    tk = ticker_storage_key("ZZTESTX")   # no live cache, no banked chain in the offline test DB
    _clear(tk)
    try:
        d = _call(tk)
        assert d["live"] is False and d["stale"] is True
        assert d["source"] in ("unavailable", "banked_morning_reference")
        if d["source"] == "banked_morning_reference":
            assert "not intraday" in d["degraded"].lower() or "morning" in d["degraded"].lower()
    finally:
        _clear(tk)
