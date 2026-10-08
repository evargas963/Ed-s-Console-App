"""Page-side one faucet (2026-09-27): every value on the console page has one server producer
(question 2: the screen shows it correctly; question 3: each value the one computation's).

One spot on every screen: each route that serves `spot` serves the live price at response time
(resolve_spot, the rule the header's price row uses); a value computed at another price names that
price `priced_at_spot`. Strike Detail's Net GEX is the heatmap's own cell, and OI/volume cell
totals are served, not summed in the browser.

Through the real code: the daemon's status and price row as the console holds them, the levels
producer (server._publish_levels), the routes. Real data: Schwab's CRWD chain as captured
2026-09-02 (tests/fixtures/real_crwd_complete_chain_quarter.json), published at its capture price
(205.4). STAND-IN (named): the live price after the capture, LIVE (206.4).
"""
import json
import time
from datetime import datetime
from pathlib import Path

import pytest

import app.options.order_flow.streaming as ofs
import live_market_plane as lmp
import server
from stream_spine import options_quote_msg
from time_et import ET

_REAL = json.loads((Path(__file__).resolve().parent / "fixtures" / "real_crwd_complete_chain_quarter.json")
                   .read_text(encoding="utf-8"))
_CONTRACTS = [dict(ct) for ct in _REAL["chain"]]
TK = "CRWD"
EXPIRY = _REAL["expiry"]                   # 2026-09-18
PUBLISHED = float(_REAL["spot"])           # Schwab's price at the capture
LIVE = PUBLISHED + 1.0                     # stand-in for the stream's price
_AT = datetime(2026, 9, 2, 10, 5, tzinfo=ET)


def _daemon(price, held_options=()):
    lmp.record_feed_heartbeat({"ts": time.time(), "schwab_socket_open": True,
                               "held": {"LEVELONE_EQUITIES": [TK], "LEVELONE_OPTIONS": list(held_options)}})
    ofs._price_rows[TK] = {"ticker": TK, "spot": price, "trade_ts": _AT.timestamp()}


@pytest.fixture
def held():
    """CRWD's chain published at its capture price, the live price since moved to LIVE."""
    _daemon(PUBLISHED)
    server._publish_levels(TK, [dict(c) for c in _CONTRACTS], _AT.timestamp(), now=_AT)
    _daemon(LIVE)
    with server._terrain_cache_lock:
        payload = server._terrain_cache[TK]
    yield payload
    with server._terrain_cache_lock:
        server._terrain_cache.pop(TK, None)
    ofs._price_rows.pop(TK, None)
    lmp.record_feed_down()


@pytest.mark.parametrize("route", [
    lambda: server.get_chain(ticker=TK, expiry=EXPIRY),
    lambda: server.get_options_gamma_surface(ticker=TK),
    lambda: server.get_terrain_strikes(ticker=TK),
    lambda: server.get_vanna_by_strike(ticker=TK),
    lambda: server.get_charm_by_strike(ticker=TK),
], ids=["chain", "gamma-surface", "terrain-strikes", "vanna", "charm"])
def test_every_route_serves_the_live_spot_and_names_the_computed_one(held, route):
    body = json.loads(route().body)
    assert body["spot"] == LIVE, "served the price the payload was computed at, not the live one"
    assert body["priced_at_spot"] == PUBLISHED


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
        # Schwab's values as sent: a reported 0 (strike 38.75's put OI) is a real zero
        assert c["oi"][col]["total"] == legs["CALL"]["openInterest"] + legs["PUT"]["openInterest"]
        assert c["volume"][col]["total"] == legs["CALL"]["totalVolume"] + legs["PUT"]["totalVolume"]
        checked += 1
    assert checked > 50


def test_a_book_with_no_age_is_not_reported_fresh():
    """LIVE badges read book_stale: an unknown book age is unknown (None), never False (fresh)."""
    from app.options.order_flow.engine import compute_book_microstructure
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
    assert body["expiries"] == [] and body["reason"] == server.terrain_staleness(None, "ZZNOLEVELS")["levels_stale_reason"]


@pytest.mark.parametrize("route", [
    lambda: server.get_chain(ticker=TK, expiry=EXPIRY),
    lambda: server.get_options_gamma_surface(ticker=TK),
    lambda: server.get_terrain_strikes(ticker=TK),
], ids=["chain", "gamma-surface", "terrain-strikes"])
def test_the_spot_row_is_served(held, route):
    """The row every panel marks as spot: the listed strike nearest the live price, served (it
    was worked out in six places in the page)."""
    body = json.loads(route().body)
    strikes = sorted({float(c["strikePrice"]) for c in _CONTRACTS})
    assert body["spot_strike"] == min(strikes, key=lambda k: abs(k - LIVE))


def test_put_call_ratios_over_every_expiry_are_served(held):
    """With no expiry selected the Put/Call rows show the whole book, served (the page used to
    pick the first expiry in its list, an expired one on 2026-09-27)."""
    assert held["pcr_all"] is not None
    assert held["pcr_all"] == held["pcr_by_expiry"][EXPIRY]      # one expiry: the same book


def test_heatmap_column_state_cell_age_and_front_expiry_are_served():
    """Column streaming status and a cell's age come from the server's own stream states; the
    front column is the nearest unexpired expiry. One call streaming (its update 2 s before the
    publication): the column is partly streaming and the cell's age is 2 s."""
    sym = next(c["symbol"] for c in _CONTRACTS if c["putCall"] == "CALL")
    _daemon(PUBLISHED, [sym])
    ofs._ingest_pushed(f"optquote.{sym}", options_quote_msg(symbol=sym, content={"key": sym, "GAMMA": 0.05},
                                                            src="schwab_options_l1", ts_recv=_AT.timestamp() - 2))
    try:
        server._publish_levels(TK, [dict(c) for c in _CONTRACTS], _AT.timestamp() - 10, now=_AT)
        body = server.gamma_surface_payload(TK, "all", None, 0, None, None, _AT)
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop(TK, None)
        ofs._price_rows.pop(TK, None)
        ofs._drop_released_options()
        lmp.record_feed_down()
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
    import live_price_rows
    from tests.feed_live_helper import mark_feed_live
    mark_feed_live("SPY")
    lmp.record_from_level_one_equity("SPY", {"LAST_PRICE": 772.04, "TRADE_TIME_MILLIS": 1790380799830},
                                     received_ts=time.time())
    row = live_price_rows.price_row("SPY")
    ofs._price_rows["SPY"] = row                     # the row as the daemon pushes it to the console
    try:
        spot = server.resolve_spot("SPY")
    finally:
        ofs._price_rows.pop("SPY", None)
        lmp.record_feed_down()
    assert (row["spot"], row["spot_disp"], row["trade_time_ct"]) == (772.04, "772.04", "Fri 09/25 06:59 PM CT")
    assert "spot_state" not in row and "closed_last" not in row
    assert spot == (772.04, server.SPOT_SOURCE_PLANE, 1790380799.83)
