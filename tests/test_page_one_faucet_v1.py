"""Page-side one faucet: every value on the console page has one server producer
(question 2: the screen shows it correctly; question 3: each value the one computation's).

One spot on every screen: each route that serves `spot` serves the live price at response time
(resolve_spot, the rule the header's price row uses); a value computed at another price names that
price `priced_at_spot`. Strike Detail's Net GEX is the heatmap's own cell, and OI/volume cell
totals are served, not summed in the browser.

Through the real code: the daemon's status and price row as the console holds them, the levels
producer (server._publish_levels), the routes. Real data: CRWD's 2026-10-16 expiry, every strike,
captured 2026-10-07 10:38:40 ET (tests/real_chains.py CRWD), published at the price Schwab sent in
that answer (PUBLISHED, 269.04), and CRWD's LEVELONE_EQUITIES message the daemon received at
10:38:00 ET (tests/fixtures/real_crwd_quote_2026_10_07.json, LIVE: its LAST_PRICE 269.395), made
the price row by the daemon's own function.
"""
import inspect
import json
import time
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import app.options.order_flow.streaming as ofs
import live_market_plane as lmp
from app.options.order_flow.engine import compute_book_microstructure
from tests.feed_live_helper import mark_feed_live
import live_price_rows
import server
from instrument_identity import ticker_storage_key
from stream_spine import options_quote_msg
from tests.real_chains import CRWD, SPY_CLOSE, SPY_PRINT_A_STRIKE_AWAY
from time_et import ET

_QUOTE = json.loads((Path(__file__).resolve().parent / "fixtures" / "real_crwd_quote_2026_10_07.json")
                    .read_text(encoding="utf-8"))

_CONTRACTS = [dict(ct) for ct in CRWD.chain]
TK = ticker_storage_key(CRWD.ticker)
EXPIRY = str(CRWD.chain[0]["expirationDate"])[:10]     # 2026-10-16
PUBLISHED = CRWD.spot                                  # Schwab's price in the chain answer
LIVE = _QUOTE["native"]["LAST_PRICE"]                  # Schwab's last trade, as the daemon received it
_AT = CRWD.now


def _daemon(at: float, held_options=()):
    """The daemon's heartbeat at `at`, holding TK and `held_options`, and its price row for TK made
    from Schwab's captured quote."""
    lmp.record_from_level_one_equity(TK, _QUOTE["native"], received_ts=_QUOTE["ts_recv"])
    lmp.record_feed_heartbeat({"ts": at, "schwab_socket_open": True,
                               "held": {"LEVELONE_EQUITIES": [TK], "LEVELONE_OPTIONS": list(held_options)}})
    ofs._price_rows[TK] = live_price_rows.price_row(TK, at)


def _publish(fetched_ts: float):
    """The chain published as the stored capture it is, at the price Schwab sent with it."""
    server._publish_levels(TK, captures=[{"contracts": [dict(c) for c in _CONTRACTS], "ts_utc": fetched_ts,
                                          "spot": PUBLISHED, "et_date": _AT.date().isoformat(),
                                          "basis": server.CAPTURE_BASIS, "spot_ts": None}], now=_AT)


def _forget():
    with server._terrain_cache_lock:
        server._terrain_cache.pop(TK, None)
    ofs._price_rows.pop(TK, None)
    lmp._by_ticker.pop(TK, None)
    lmp._fields_by_ticker.pop(TK, None)
    lmp.record_feed_heartbeat({"ts": time.time(), "schwab_socket_open": True, "held": {}})
    lmp.record_feed_down()


@pytest.fixture
def held():
    """CRWD's chain published at the price Schwab sent with it; the live price is Schwab's last trade."""
    _publish(_AT.timestamp())
    _daemon(time.time())                                 # live now, as the routes read it
    with server._terrain_cache_lock:
        payload = server._terrain_cache[TK]
    yield payload
    _forget()


def test_every_route_serves_the_live_spot_and_names_the_computed_one(held):
    """Every GET route that answers a ticker, found from the app, each answering this request: a
    route that serves a price serves `spot`, the live price, and `priced_at_spot`, the price the
    payload was computed at."""
    client = TestClient(server.app)
    paths = [r.path for r in server.app.routes
             if isinstance(r, APIRoute) and "GET" in r.methods
             and "ticker" in inspect.signature(r.endpoint).parameters
             and not inspect.iscoroutinefunction(r.endpoint)]      # /api/changes is a stream
    served, refused = {}, {}
    for path in paths:
        answer = client.get(path, params={"ticker": TK, "expiry": EXPIRY, "venue": "NYSE_BOOK"})
        body = answer.json()
        if answer.status_code != 200:
            refused[path] = answer.status_code
        elif {"spot", "priced_at_spot"} & set(body):
            served[path] = (body.get("spot"), body.get("priced_at_spot"))
    assert refused == {} and served
    assert {p: s for p, s in served.items() if s != (LIVE, PUBLISHED)} == {}


def test_strike_side_sums_split_at_the_live_spot(held):
    rows = held["_per_strike"]["all"]
    below = [r for r in rows if r[0] < LIVE]
    above = [r for r in rows if r[0] > LIVE]
    assert below and above, "the real chain has strikes on both sides of the live price"
    sums = json.loads(server.get_terrain_strikes(ticker=TK).body)["today_side_sums"]
    assert sums["spot_basis"] == LIVE
    assert sums["gex_below"] == pytest.approx(sum(r[1] for r in below), abs=0.1)
    assert sums["gex_above"] == pytest.approx(sum(r[1] for r in above), abs=0.1)


def test_chain_serves_this_expirys_net_gex_from_the_heatmaps_own_column(held):
    """Strike Detail's Net row: this expiry's column of the published surface, verbatim."""
    surf = held["_gamma_surface"]
    col = [e["expiry"] for e in surf["expirations"]].index(EXPIRY)
    expected = [[c["strike"], c["gex"][col]] for c in surf["cells"] if c["gex"][col] is not None]
    assert expected, "the real chain yields net GEX cells for its expiry"
    body = json.loads(server.get_chain(ticker=TK, expiry=EXPIRY).body)
    assert body["net_gex_by_strike"] == expected


def test_oi_and_volume_cells_carry_the_served_total(held):
    """The OI/Volume heatmap colours by the cell's served total: Schwab's call OI + put OI at the
    strike, read straight from the chain; the browser adds nothing."""
    surf = held["_gamma_surface"]
    col = [e["expiry"] for e in surf["expirations"]].index(EXPIRY)
    checked = 0
    for c in surf["cells"]:
        legs = {ct["putCall"]: ct for ct in _CONTRACTS if ct["strikePrice"] == c["strike"]}
        if set(legs) != {"CALL", "PUT"}:
            continue
        # Schwab's values as sent: a reported 0 is a real zero
        assert c["oi"][col]["total"] == legs["CALL"]["openInterest"] + legs["PUT"]["openInterest"]
        assert c["volume"][col]["total"] == legs["CALL"]["totalVolume"] + legs["PUT"]["totalVolume"]
        checked += 1
    assert checked > 50


def test_a_book_with_no_age_is_not_reported_fresh():
    """LIVE badges read book_stale: an unknown book age is unknown (None), never False (fresh)."""
    out = compute_book_microstructure({"content": {}}, now_ts=1_800_000_000.0)
    assert out["ages"]["book_age_sec"] is None and out["ages"]["book_stale"] is None


def test_days_to_expiry_are_schwabs_as_sent(held):
    """The expiry dropdown's DTE: Schwab's daysToExpiration from the chain, not the browser's
    clock (it counted days in UTC, a day off after 7 PM Central)."""
    body = json.loads(server.get_expiries(ticker=TK).body)
    assert body["expiries"] == [EXPIRY]
    assert body["dte"] == {EXPIRY: _CONTRACTS[0]["daysToExpiration"]}
    # the dropdown's label is served (the page reformatted the date itself)
    y, m, d = EXPIRY.split("-")
    assert body["labels"] == {EXPIRY: f"{m}/{d}/{y} · {_CONTRACTS[0]['daysToExpiration']:g}DTE"}


def test_with_no_published_levels_the_expiries_carry_the_levels_reason():
    body = json.loads(server.get_expiries(ticker="ZZNOLEVELS").body)
    assert body["expiries"] == [] and body["reason"] == server.terrain_staleness(None, "ZZNOLEVELS", now=time.time())["levels_stale_reason"]


@pytest.mark.parametrize("route", [
    lambda: server.get_chain(ticker="SPY", expiry="2026-10-22"),
    lambda: server.get_options_gamma_surface(ticker="SPY"),
    lambda: server.get_terrain_strikes(ticker="SPY"),
], ids=["chain", "gamma-surface", "terrain-strikes"])
def test_the_spot_row_is_served(route):
    """The row every panel marks as spot: the listed strike nearest the live price, served (it
    was worked out in six places in the page). SPY's 2026-10-22 close capture, published at the
    price Schwab sent in it (764.04), and SPY's first print after it a strike away (16:39:03 ET,
    LAST_PRICE 773.1269, as the daemon received it): the row is the live price's strike."""
    print_ = SPY_PRINT_A_STRIKE_AWAY
    strikes = sorted({float(c["strikePrice"]) for c in SPY_CLOSE.chain})
    live = min(strikes, key=lambda k: abs(k - print_["native"]["LAST_PRICE"]))
    assert live != min(strikes, key=lambda k: abs(k - SPY_CLOSE.spot))
    server._publish_levels("SPY", captures=[{"contracts": [dict(c) for c in SPY_CLOSE.chain],
                                             "ts_utc": SPY_CLOSE.now.timestamp(), "spot": SPY_CLOSE.spot,
                                             "et_date": SPY_CLOSE.now.date().isoformat(),
                                             "basis": server.CAPTURE_BASIS, "spot_ts": None}], now=SPY_CLOSE.now)
    lmp.record_from_level_one_equity("SPY", print_["native"], received_ts=print_["ts_recv"])
    lmp.record_feed_heartbeat({"ts": time.time(), "schwab_socket_open": True, "held": {"LEVELONE_EQUITIES": ["SPY"]}})
    ofs._price_rows["SPY"] = live_price_rows.price_row("SPY", time.time())
    try:
        body = json.loads(route().body)
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop("SPY", None)
        ofs._price_rows.pop("SPY", None)
        lmp._by_ticker.pop("SPY", None)
        lmp._fields_by_ticker.pop("SPY", None)
        lmp.record_feed_heartbeat({"ts": time.time(), "schwab_socket_open": True, "held": {}})
        lmp.record_feed_down()
    assert body["spot_strike"] == live


def test_put_call_ratios_over_every_expiry_are_served(held):
    """With no expiry selected the Put/Call rows show the whole book, served (the page used to
    pick the first expiry in its list, an expired one on 2026-09-27)."""
    assert held["pcr_all"] is not None
    assert held["pcr_all"] == held["pcr_by_expiry"][EXPIRY]      # one expiry: the same book


def test_heatmap_column_state_cell_age_and_front_expiry_are_served():
    """Column streaming status and a cell's age come from the server's own stream states; the
    front column is the nearest unexpired expiry. One call streaming (its update 2 s before the
    publication, carrying the gamma Schwab sent for it): the column is partly streaming and the
    cell's age is 2 s."""
    call = next(c for c in _CONTRACTS if c["putCall"] == "CALL" and c.get("gamma") is not None)
    sym = call["symbol"]
    _daemon(_AT.timestamp(), [sym])
    ofs._ingest_pushed(f"optquote.{sym}", options_quote_msg(symbol=sym, content={"key": sym, "GAMMA": call["gamma"]},
                                                            src="schwab_options_l1", ts_recv=_AT.timestamp() - 2))
    try:
        _publish(_AT.timestamp() - 10)
        body = server.gamma_surface_payload(TK, "all", None, 0, None, None, _AT)
    finally:
        ofs._drop_released_options(_AT.timestamp())
        _forget()
    assert body["stream_by_expiry"][EXPIRY] == "partial"
    ages = [c["stream"][0]["age_sec"] for c in body["cells"] if c["stream"][0] and c["stream"][0]["age_sec"] is not None]
    assert ages == [pytest.approx(2.0)]
    assert [e["expiry"] for e in body["expirations"] if e["front"]] == [EXPIRY]


def test_chain_flags_are_served(held):
    """ADJUSTED DELIVERABLE and duplicate contracts: served flags, not page rules."""
    body = json.loads(server.get_chain(ticker=TK, expiry=EXPIRY).body)
    plain = [c["symbol"] for c in _CONTRACTS if len(c.get("optionDeliverablesList") or []) == 1]
    assert plain and not set(plain) & set(body["adjusted_deliverable_symbols"])
    assert body["has_duplicate_contracts"] is False


def test_an_index_option_is_not_flagged_adjusted_only_schwabs_nonstandard_would_be():
    """TICK-03 (2026-09-28 audit): the page's ADJUSTED DELIVERABLE flag was our own rule, which
    compared Schwab's deliverable symbol "$SPX" with the ticker stripped of its "$" -- so every
    $SPX and $VIX contract read adjusted, while Schwab's own nonStandard flag was false on all 43
    board tickers. The flag is Schwab's, as sent: real $SPX contracts
    (tests/fixtures/real_spx_chain_contracts_2026_09_28.json, nonStandard false) are not flagged."""
    fx = json.loads((Path(__file__).parent / "fixtures" / "real_spx_chain_contracts_2026_09_28.json")
                    .read_text(encoding="utf-8"))
    at = datetime.fromtimestamp(fx["ts_utc"], ET)
    lmp.record_feed_heartbeat({"ts": time.time(), "schwab_socket_open": True, "held": {"LEVELONE_EQUITIES": ["$SPX"]}})
    ofs._price_rows["$SPX"] = {"ticker": "$SPX", "spot": fx["spot"], "trade_ts": fx["ts_utc"]}
    try:
        server._publish_levels("$SPX", [dict(c) for c in fx["contracts"]], fx["ts_utc"], now=at)
        body = json.loads(server.get_chain(ticker="$SPX", expiry="2026-10-16").body)
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop("$SPX", None)
        ofs._price_rows.pop("$SPX", None)
        lmp.record_feed_down()
    assert {c["nonStandard"] for c in fx["contracts"]} == {False}
    assert len(body["contracts"]) == len(fx["contracts"]) and body["adjusted_deliverable_symbols"] == []


def test_the_largest_gex_strike_is_served(held):
    rows = held["_per_strike"]["all"]
    body = json.loads(server.get_terrain_strikes(ticker=TK).body)
    assert body["max_abs_row"] == max(rows, key=lambda r: abs(r[1]))


def test_at_any_hour_the_price_is_schwabs_last_trade_with_schwabs_trade_time():
    """Sunday 2026-09-27: the daemon held SPY's last trade (Friday 18:59:59 CT), replayed as it
    captured it (stream_quotes_raw). Operator, 2026-10-01: "From Schwab's mouth to our UI's ears.
    Period." -- no live/closed verdict by our clock: the row serves Schwab's last price as the
    spot with Schwab's trade time, and every consumer reads it."""
    mark_feed_live("SPY")
    lmp.record_from_level_one_equity("SPY", {"LAST_PRICE": 772.04, "TRADE_TIME_MILLIS": 1790380799830},
                                     received_ts=time.time())
    row = live_price_rows.price_row("SPY", time.time())
    ofs._price_rows["SPY"] = row                    # the row as the daemon pushes it to the console
    try:
        spot = server.resolve_spot("SPY", now=time.time())
    finally:
        ofs._price_rows.pop("SPY", None)
        lmp.record_feed_down()
    assert (row["spot"], row["spot_disp"], row["trade_time_ct"]) == (772.04, "772.04", "Fri 09/25 06:59 PM CT")
    assert "spot_state" not in row and "closed_last" not in row
    assert spot == (772.04, server.SPOT_SOURCE_PLANE, 1790380799.83)
