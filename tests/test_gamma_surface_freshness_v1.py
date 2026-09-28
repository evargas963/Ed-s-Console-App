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
from calibration.complete_chain_capture import CAPTURE_BASIS, persist_complete_chain_capture
from db import EdDB
from server import get_options_gamma_surface, ticker_storage_key
from time_et import ET

_SURF = {
    "expirations": [{"expiry": "2026-09-11", "dte": 2}], "strikes": [580.0, 583.0, 586.0],
    "cells": [{"strike": 580.0, "gex": [-90000]}, {"strike": 583.0, "gex": [958600]},
              {"strike": 586.0, "gex": [-264500]}],
    "contracts_total": 3, "contracts_used": 3, "contracts_excluded_malformed_expiry": 0,
    "gamma_available": True,   # project_gamma_surface always sets its verdict
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
    monkeypatch.setattr("server._is_loggable_session", lambda: True)   # an open-market test
    monkeypatch.setattr("server.resolve_spot", lambda tk, **_k: (584.0, "live_quote", time.time()))
    tk = ticker_storage_key("SPY")
    _clear(tk); _put_live(tk, computed_ts=time.time())
    try:
        d = _call(tk)
        assert d["source"] == "terrain_live_cache" and d["live"] is True
        assert d["cells"] == _SURF["cells"]     # served verbatim
        # the live price, and the price the cells were computed at, each named
        assert d["spot"] == 584.0 and d["priced_at_spot"] == 583.41
        assert d["provenance"]["spot_basis"] == "live_resolve_spot"
        # coverage: the levels' chain is every expiry, strike_range=ALL (fetch_full_chain)
        assert d["coverage"]["strike_count"] == 3 and d["coverage"]["strike_min"] == 580.0
        assert "strike_range=all" in d["coverage"]["note"].lower()
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


def test_warming_true_only_when_terrain_eligible(monkeypatch, view):
    # #1.3: WARMING is claimed only when the terrain producer can actually refresh THIS ticker,
    # reusing terrain_staleness's canonical output (levels_refresh_active + not quarantined/paused).
    tk = ticker_storage_key("SPY")
    with server._terrain_cache_lock:
        server._terrain_cache[tk] = {"computed_ts_utc": time.time(), "spot": 100.0}   # on the board, no surface yet
    monkeypatch.setattr(server, "_logger_tickers", [tk])   # enrolled like any ticker -- no built-in list
    monkeypatch.setattr(server, "terrain_skip_reason", lambda t: None)
    monkeypatch.setattr(server, "terrain_quarantine_reason", lambda t: None)
    monkeypatch.setattr(server, "terrain_quarantine_state", lambda t: {})
    view(tk)                                                             # a page open on it
    try:
        monkeypatch.setattr(server, "_is_loggable_session", lambda: True)   # eligible
        d = _call(tk)
        assert d["warming"] is True and d["requested"] is True
        monkeypatch.setattr(server, "_is_loggable_session", lambda: False)  # out of session -> not warming
        d2 = _call(tk)
        assert d2["warming"] is False and d2["requested"] is True           # still open -> requested
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
    monkeypatch.setattr(server, "_logger_tickers", [_BOARD])
    monkeypatch.setattr(server, "_terrain_cache", {})
    monkeypatch.setattr(server, "_terrain_refresh_last_error", {})
    monkeypatch.setattr(server, "terrain_skip_reason", lambda t: None)
    monkeypatch.setattr(server, "terrain_quarantine_reason", lambda t: None)
    monkeypatch.setattr(server, "terrain_quarantine_state", lambda t: {})
    monkeypatch.setattr(server, "_desired_stream_greeks_for_ticker", lambda tk, listed=None: {})
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **k: (_CRWD["spot"], "stub", _CAPTURED))
    return edb


@pytest.mark.parametrize("tk", [_BOARD, _OFF])
def test_first_view_in_session_warms_by_the_refresh_state(_fresh, monkeypatch, view, tk):
    monkeypatch.setattr(server, "_is_loggable_session", lambda: True)
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
    assert not server._gamma_surface_wanted(tk) and server._viewed_tickers() == []
    (client,) = view(tk)                            # /api/changes open on this ticker
    assert server._gamma_surface_wanted(tk) and server._viewed_tickers() == [tk]
    push_changes.unsubscribe(tk, client)            # the page closed or changed ticker
    assert not server._gamma_surface_wanted(tk) and server._viewed_tickers() == []


@pytest.mark.parametrize("tk", [_BOARD, _OFF])
def test_a_held_ticker_does_not_warm_and_says_why(_fresh, monkeypatch, tk):
    monkeypatch.setattr(server, "_is_loggable_session", lambda: True)
    monkeypatch.setattr(server, "terrain_quarantine_reason", lambda t: "held: Schwab refused the chain")
    d = _call(tk)
    assert d["warming"] is False and d["reason"] == "held: Schwab refused the chain"


@pytest.mark.parametrize("tk", [_BOARD, _OFF])
def test_closed_market_with_no_capture_gives_one_reason_on_every_route(_fresh, monkeypatch, tk):
    monkeypatch.setattr(server, "_is_loggable_session", lambda: False)
    d = _call(tk)
    assert d["warming"] is False and server.NO_CAPTURE_REASON in d["reason"]
    t = server.get_terrain(ticker=tk)
    assert server.NO_CAPTURE_REASON in t["error"]
    # ATR is from the bars, not the chain: served (here absent, with its reason) with no levels
    assert t["atr_daily"] is None and "0 trading days" in t["atr_daily_reason"]


@pytest.mark.parametrize("tk", [_BOARD, _OFF])
def test_closed_market_prices_the_stored_capture_on_every_route(_fresh, monkeypatch, view, tk):
    monkeypatch.setattr(server, "_is_loggable_session", lambda: False)
    view(tk)                                        # the page selects the ticker
    by_expiry: dict = {}
    for ct in _CRWD["chain"]:
        by_expiry.setdefault(ct["expirationDate"][:10], []).append(ct)
    for expiry, cts in by_expiry.items():
        persist_complete_chain_capture(_fresh.db_path, ticker=tk, expiry=expiry, contracts=cts,
                                       spot=_CRWD["spot"], completeness_basis=CAPTURE_BASIS,
                                       ts_utc=_CAPTURED)
    t = server.get_terrain(ticker=tk)                # the Trade Desk's first load
    assert not t["error"] and t["chain_basis"] == CAPTURE_BASIS and t["spot"] == _CRWD["spot"]
    assert t["atr_daily"] is None and "0 trading days" in t["atr_daily_reason"]
    assert _call(tk)["available"] is True           # the heatmap from the same publication


@pytest.mark.parametrize("tk", [_BOARD, _OFF])
def test_a_refresh_publishes_the_same_fields_for_any_ticker(_fresh, monkeypatch, pin_clock, view, tk):
    pin_clock(2026, 9, 2, 10, 5)
    monkeypatch.setattr(server, "_is_loggable_session", lambda: True)
    view(tk)                                        # selected on the page
    server._publish_levels(tk, [dict(c) for c in _CRWD["chain"]], _CAPTURED)
    t = server.get_terrain(ticker=tk)
    assert t["chain_basis"] == CAPTURE_BASIS
    assert t["atr_15m"] is None and "0 15-minute periods" in t["atr_15m_reason"]
    assert _call(tk)["available"] is True


def test_surface_session_identity_is_stamped_by_the_server_clock():
    """Real-data repair 2026-09-10: a banked 2026-09-09 reference viewed on 2026-09-10 rendered its
    expired 0DTE column as current structure. The server (the ONE ET clock) now stamps today's
    session date, per-expiration `expired`, and `prior_session` for a reference from an earlier
    day; presentation reads these, never a browser clock. Cell values are untouched."""
    tk = ticker_storage_key("SPY")
    surf = dict(_SURF, expirations=[{"expiry": "2000-01-03", "dte": 0}, {"expiry": "2999-01-15", "dte": 9}])
    _clear(tk)
    with server._terrain_cache_lock:
        server._terrain_cache[tk] = {"_gamma_surface": surf, "computed_ts_utc": time.time(), "spot": 583.41,
                                     "spot_source": "last", "spot_as_of_ts_utc": time.time(), "chain_basis": "full"}
    try:
        d = _call(tk)
        today = server.now_et().strftime("%Y-%m-%d")
        assert d["session_date_et"] == today
        assert [e["expired"] for e in d["expirations"]] == [True, False]
        assert d["prior_session"] is False                     # a live surface is this session's
        assert d["cells"] == _SURF["cells"]                    # values untouched
    finally:
        _clear(tk)
    # a banked reference from an earlier trading day is a PRIOR-session reference
    stamped = server._stamp_surface_session(surf, reference_date="2000-01-03")
    assert stamped["prior_session"] is True
    assert stamped["cells"] == surf["cells"] and stamped["strikes"] == surf["strikes"]
    assert server._stamp_surface_session(surf, reference_date=today)["prior_session"] is False


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
