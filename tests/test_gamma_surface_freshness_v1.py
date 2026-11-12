"""The heatmap's answer is the live levels' surface with the one freshness authority's age.

The live price and the price its cells were computed at are each named, and a ticker open on a
page is repriced for as long as the page has it (question 2: the screen shows it correctly and
promptly).

Through the real code: the daemon's status and price row as the console holds them, the console's
pages (live_ui), the levels producer, the routes. Real data: CRWD's captured chain
(tests/fixtures/real_crwd_complete_chain_quarter.json, 2026-09-02, spot 205.4), valued at its
capture. STAND-INS (named): the live price after the capture (206.0), and the CRWD chain published
under tickers that are and are not on the watchlist.
"""

import json
from datetime import datetime
from pathlib import Path

import pytest

import live_market_plane as lmp
import server
import time_et
from calibration.complete_chain_capture import CAPTURE_BASIS
from option_contract import read_chain
from server import ticker_storage_key
from tests.feed_live_helper import daemon_status
from tests.page_on_socket import pages
from time_et import ET

_CRWD = json.loads(
    (Path(__file__).parent / "fixtures" / "real_crwd_complete_chain_quarter.json").read_text(
        encoding="utf-8"
    )
)
_AT = datetime(2026, 9, 2, 10, 5, tzinfo=ET)  # the CRWD chain's capture
_ON, _OFF = "ZZFRESHON", "ZZFRESHOFF"  # on the watchlist, and not


def _call(tk):
    """The heatmap's panel for `tk` now: Auto, following the price, every column."""
    window = {"scope": "auto", "centre": None, "shift": 0, "cols": None, "expiry": None}
    return server.gamma_surface(ticker_storage_key(tk), time_et.now(), window)


def _daemon(price: float, at: float, *tickers) -> None:
    """Record the daemon's status at `at` and each ticker's quote received at `at`.

    The status has Schwab's socket open, `tickers` held, the watchlist [_ON]; each quote has its
    trade at _AT, in the plane the price row is built from.
    """
    lmp.record_feed_heartbeat(
        daemon_status(
            at,
            schwab_socket_open=True,
            watchlist=[_ON],
            held={"LEVELONE_EQUITIES": list(tickers)},
        )
    )
    for tk in tickers:
        lmp.record_from_level_one_equity(
            tk,
            {"LAST_PRICE": price, "TRADE_TIME_MILLIS": int(_AT.timestamp() * 1000)},
            received_ts=at,
        )


@pytest.fixture
def published():
    """CRWD's chain published at its capture under _ON and _OFF, at its own spot."""
    _daemon(_CRWD["spot"], _AT.timestamp(), _ON, _OFF)  # live when the chain is published
    for tk in (_ON, _OFF):
        server._publish_levels(
            tk,
            read_chain(_CRWD["chain"]),
            _AT.timestamp(),
            chain_spot=(_CRWD["spot"], _AT.timestamp()),
            now=_AT,
        )
    _daemon(_CRWD["spot"], time_et.now(), _ON, _OFF)  # live now, as the routes read it
    yield
    with server._terrain_cache_lock:
        for tk in (_ON, _OFF):
            server._terrain_cache.pop(tk, None)
            lmp._by_ticker.pop(tk, None)
            lmp._fields_by_ticker.pop(tk, None)
    lmp.record_feed_down()


@pytest.mark.usefixtures("published")
def test_the_live_surface_is_served_with_the_live_price():
    _daemon(206.0, _AT.timestamp(), _ON)  # the price has moved since
    d = server.gamma_surface_payload(_ON, "all", None, 0, None, None, _AT)
    surface = server.published_levels(_ON).gamma_surface
    # 2026-09-02 has no /markets answer held: the levels, and so the surface, are not live
    assert d["source"] == "terrain_live_cache" and d["levels_state"] == "NOT LIVE"
    assert [c["gex"] for c in d["cells"]] == [c["gex"] for c in surface["cells"]]  # served verbatim
    assert d["spot"] == 206.0 and surface["spot"] == _CRWD["spot"]
    assert [c["strike"] for c in d["cells"] if c["spot"]] == [
        min(surface["strikes"], key=lambda k: abs(k - 206.0))
    ]
    assert not [k for k in d if k.startswith("priced_at_spot")]


@pytest.mark.usefixtures("published")
def test_freshness_is_the_one_terrain_authority_not_a_second_policy():
    _levels, live = server.terrain_cache_get(_ON, time_et.now())  # the one authority
    d = _call(_ON)
    assert (d["levels_state"], d["levels_stale_reason"]) == (
        live["levels_state"],
        live["levels_stale_reason"],
    )
    assert d["levels_age_sec"] == pytest.approx(live["levels_age_sec"], abs=5.0)
    # the chain's time is served once, as the text the page draws
    assert d["levels_time_ct"] == live["levels_time_ct"] == server.ct_label(_AT.timestamp())


@pytest.mark.usefixtures("published")
@pytest.mark.parametrize("tk", [_ON, _OFF])
def test_a_ticker_open_on_a_page_is_viewed_until_the_page_leaves_it(tk):
    """2026-09-28 audit: "viewed" was a 300 s timer renewed only by some routes.

    The page's one connection is the one viewing signal: a route read does not make a ticker
    viewed, and it stays viewed for as long as the page has it open.
    """
    _call(tk)  # a route read alone: not viewed
    assert not server._gamma_surface_wanted(tk)
    with pages() as served:
        page = served.open(tk)  # the page's socket has this ticker selected
        assert server._gamma_surface_wanted(tk)
        served.close(page)  # the page closed or changed ticker
        assert not server._gamma_surface_wanted(tk)


@pytest.mark.usefixtures("published")
@pytest.mark.parametrize("tk", [_ON, _OFF])
def test_every_ticker_is_published_with_the_same_fields_and_atr_absent_without_a_sentence(tk):
    """On the watchlist or not, a publication carries the same fields.

    The chain basis, and ATR (from the bars, none here) absent, with no sentence in its place.
    """
    t = server.terrain(ticker_storage_key(tk), time_et.now())
    assert t["chain_basis"] == CAPTURE_BASIS
    for horizon in ("daily", "weekly", "monthly"):
        assert t[f"atr_{horizon}"] is None and f"atr_{horizon}_reason" not in t, horizon
    assert _call(tk)["available"] is True


def test_with_no_levels_the_atr_is_absent():
    """ATR is from the bars, not the chain.

    A ticker with no levels published still serves it (here absent, and no sentence in its place).
    """
    t = server.terrain("ZZNOLEVELSATR", time_et.now())
    assert t["atr_daily"] is None and "atr_daily_reason" not in t


def test_fallback_is_labelled_not_live_never_intraday():
    tk = ticker_storage_key("ZZTESTX")  # no live cache, no banked chain in the offline test DB
    with server._terrain_cache_lock:
        server._terrain_cache.pop(tk, None)
    d = _call(tk)
    assert (d["available"], d["source"]) == (False, "unavailable")
