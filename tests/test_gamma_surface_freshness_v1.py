"""The heatmap's answer is the live levels' surface with the one freshness authority's age, the live
price and the price its cells were computed at each named, and a ticker open on a page is
repriced for as long as the page has it (question 2: the screen shows it correctly and promptly).

Through the real code: the daemon's status and price row as the console holds them, the console's
pages (push_changes), the levels producer, the routes. Real data: CRWD's captured chain
(tests/fixtures/real_crwd_complete_chain_quarter.json, 2026-09-02, spot 205.4), valued at its
capture. STAND-INS (named): the live price after the capture (206.0), and the CRWD chain published
under tickers that are and are not on the watchlist.
"""
import json
import time
from datetime import datetime
from pathlib import Path

import pytest

import app.options.order_flow.streaming as ofs
import live_market_plane as lmp
import push_changes
import server
from calibration.complete_chain_capture import CAPTURE_BASIS
from server import get_options_gamma_surface, ticker_storage_key
from time_et import ET

_CRWD = json.loads((Path(__file__).parent / "fixtures" / "real_crwd_complete_chain_quarter.json")
                   .read_text(encoding="utf-8"))
_AT = datetime(2026, 9, 2, 10, 5, tzinfo=ET)                     # the CRWD chain's capture
_ON, _OFF = "ZZFRESHON", "ZZFRESHOFF"                             # on the watchlist, and not


def _call(tk):
    return json.loads(get_options_gamma_surface(tk).body)


def _daemon(price: float, *tickers) -> None:
    """The daemon's status (Schwab's socket open, `tickers` held, the watchlist [_ON]) and each
    ticker's price row."""
    lmp.record_feed_heartbeat({"ts": time.time(), "schwab_socket_open": True, "watchlist": [_ON],
                               "held": {"LEVELONE_EQUITIES": list(tickers)}})
    for tk in tickers:
        ofs._price_rows[tk] = {"ticker": tk, "spot": price, "trade_ts": _AT.timestamp()}


@pytest.fixture
def published():
    """CRWD's chain published at its capture under _ON and _OFF, at its own spot."""
    _daemon(_CRWD["spot"], _ON, _OFF)
    for tk in (_ON, _OFF):
        server._publish_levels(tk, [dict(c) for c in _CRWD["chain"]], _AT.timestamp(), now=_AT)
    yield
    with server._terrain_cache_lock:
        for tk in (_ON, _OFF):
            server._terrain_cache.pop(tk, None)
            ofs._price_rows.pop(tk, None)
    lmp.record_feed_down()


def test_the_live_surface_is_served_with_the_live_price_and_its_own_price_named(published):
    _daemon(206.0, _ON)                                            # the price has moved since
    d = server.gamma_surface_payload(_ON, "all", None, 0, None, None, _AT)
    with server._terrain_cache_lock:
        surface = server._terrain_cache[_ON]["_gamma_surface"]
    assert d["source"] == "terrain_live_cache" and d["live"] is True
    assert [c["gex"] for c in d["cells"]] == [c["gex"] for c in surface["cells"]]      # served verbatim
    assert d["spot"] == 206.0 and d["priced_at_spot"] == _CRWD["spot"]
    assert [c["strike"] for c in d["cells"] if c["spot"]] == [min(surface["strikes"], key=lambda k: abs(k - 206.0))]
    assert d["provenance"]["spot_basis"] == "live_resolve_spot"


def test_freshness_is_the_one_terrain_authority_not_a_second_policy(published):
    live = server.terrain_cache_get(_ON)                          # the one authority
    d = _call(_ON)
    assert d["stale"] == bool(live.get("levels_stale"))
    assert d["age_sec"] == pytest.approx(live.get("levels_age_sec"), abs=5.0)
    assert (d["degraded"] or None) == (live.get("levels_stale_reason") if live.get("levels_stale") else None)
    assert d["chain_as_of_ts_utc"] == _AT.timestamp()


@pytest.mark.parametrize("tk", [_ON, _OFF])
def test_a_ticker_open_on_a_page_is_viewed_until_the_page_leaves_it(published, tk):
    """2026-09-28 audit: "viewed" was a 300 s timer renewed only by some routes. The page's one
    connection is the one viewing signal: a route read does not make a ticker viewed, and it
    stays viewed for as long as the page has it open."""
    _call(tk)                                       # a route read alone: not viewed
    assert not server._gamma_surface_wanted(tk)
    client = push_changes.subscribe(tk)             # /api/changes open on this ticker
    try:
        assert server._gamma_surface_wanted(tk)
    finally:
        push_changes.unsubscribe(tk, client)        # the page closed or changed ticker
    assert not server._gamma_surface_wanted(tk)


@pytest.mark.parametrize("tk", [_ON, _OFF])
def test_every_ticker_is_published_with_the_same_fields_and_atr_served_with_its_reason(published, tk):
    """On the watchlist or not, a publication carries the same fields: the chain basis, and ATR
    (from the bars, none here) served absent with its reason."""
    t = server.get_terrain(ticker=tk)
    assert t["chain_basis"] == CAPTURE_BASIS
    assert t["atr_daily"] is None and "0 trading days" in t["atr_daily_reason"]
    assert t["atr_15m"] is None and "0 15-minute periods" in t["atr_15m_reason"]
    assert _call(tk)["available"] is True


def test_fallback_is_labelled_not_live_never_intraday():
    tk = ticker_storage_key("ZZTESTX")   # no live cache, no banked chain in the offline test DB
    with server._terrain_cache_lock:
        server._terrain_cache.pop(tk, None)
    d = _call(tk)
    assert d["live"] is False and d["stale"] is True
    assert d["source"] in ("unavailable", "banked_morning_reference")
    if d["source"] == "banked_morning_reference":
        assert "not intraday" in d["degraded"].lower() or "morning" in d["degraded"].lower()
