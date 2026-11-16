"""Page-side one faucet: every value on the console page has one server producer.

Question 2: the screen shows it correctly; question 3: each value the one computation's.

One spot on every screen: each route that serves `spot` serves the live price at response time
(resolve_spot, the rule the header's price row uses), and no other price. Strike Detail's Net
GEX is the heatmap's own cell, and OI/volume cell totals are served, not summed in the browser.

Through the real code: the daemon's status and price row as the console holds them, the levels
producer (server._publish_levels), the routes. Real data: CRWD's 2026-10-16 expiry, every strike,
captured 2026-10-07 10:38:40 ET (tests/real_chains.py CRWD), published at the price Schwab sent in
that answer (PUBLISHED, 269.04), and CRWD's LEVELONE_EQUITIES message the daemon received at
10:38:00 ET (tests/fixtures/real_crwd_quote_2026_10_07.json, LIVE: its LAST_PRICE 269.395), made
the price row by the daemon's own function.
"""

import inspect
import json
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.routing import APIRoute

import app.options.order_flow.streaming as ofs
import live_market_plane as lmp
import server
import time_et
from app.market_data.schwab.streaming.live_ui import Asked
from calc.order_flow import compute_book_microstructure
from instrument_identity import ticker_storage_key
from numeric_contract import count_text, dollars_text, strike_text
from option_contract import read_chain
from push import chain as push_chain
from push import expiries as push_expiries
from push import strikes as push_strikes
from push import surface as push_surface
from push import verdict as push_verdict
from state import level_store
from stream_spine import verbatim_msg
from tests.feed_live_helper import daemon_status, mark_feed_live, publish_capture
from tests.real_chains import CRWD, SPY_CLOSE, SPY_PRINT_A_STRIKE_AWAY
from time_et import ET

_QUOTE = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "real_crwd_quote_2026_10_07.json").read_text(
        encoding="utf-8"
    )
)

_CONTRACTS = [dict(ct) for ct in CRWD.chain]
TK = ticker_storage_key(CRWD.ticker)
EXPIRY = str(CRWD.chain[0]["expirationDate"])[:10]  # 2026-10-16
PUBLISHED = CRWD.spot  # Schwab's price in the chain answer
LIVE = _QUOTE["native"]["LAST_PRICE"]  # Schwab's last trade, as the daemon received it
_AT = CRWD.now
#: a per-strike panel's window as the page asks it: Auto, following the price
AUTO = {"scope": "auto", "centre": None, "shift": 0}


def _daemon(at: float, held_options=()):
    """Record the daemon's heartbeat at `at`, holding TK and `held_options`, and its price row.

    The price row for TK is made from Schwab's captured quote.
    """
    lmp.record_from_level_one_equity(TK, _QUOTE["native"], received_ts=_QUOTE["ts_recv"])
    lmp.record_feed_heartbeat(
        daemon_status(
            at,
            schwab_socket_open=True,
            held={"LEVELONE_EQUITIES": [TK], "LEVELONE_OPTIONS": list(held_options)},
        )
    )


def _publish(fetched_ts: float):
    """Publish the chain as the stored capture it is, at the price Schwab sent with it."""
    publish_capture(TK, _CONTRACTS, fetched_ts, PUBLISHED, _AT.date().isoformat(), _AT)


def _forget():
    with level_store._lock:
        level_store._levels.pop(TK, None)
    lmp._by_ticker.pop(TK, None)
    lmp._fields_by_ticker.pop(TK, None)
    lmp.record_feed_heartbeat(daemon_status(time_et.now(), schwab_socket_open=True))
    lmp.record_feed_down()


@pytest.fixture
def held():
    """CRWD's chain published at the price Schwab sent with it.

    The live price is Schwab's last trade.
    """
    _publish(_AT.timestamp())
    _daemon(time_et.now())  # live now, as the routes read it
    yield level_store.published_levels(TK)
    _forget()


#: a reader's parameters for every page panel (server.PAGE_PANELS)
ASKED = {**AUTO, "cols": None, "expiry": EXPIRY, "tf": "1", "limit": 1500, "minutes": 60}
ASKED["venue"] = "NYSE_BOOK"


def test_every_panel_that_serves_a_price_serves_the_live_spot_and_no_other(held):
    """Every page panel, found from the app (no GET route answers a ticker).

    A panel that serves a price serves `spot`, the live price, and not the price the payload was
    computed at, which no page reads (operator 2026-11-12: "Yes, remove it"). The strikes panel
    serves neither: its pages take the price from the header row.
    """
    now = time_et.now()
    served = {}
    for kind, panel in server.PAGE_PANELS.items():
        contract = next(iter(held.contracts))
        body = panel(Asked(TK, now, {**ASKED, "contract": contract}))
        if {"spot", "priced_at_spot"} & set(body):
            served[kind] = (body.get("spot"), "priced_at_spot" in body)
    assert {"terrain", "surface", "chain", "levels"} <= set(served) and "strikes" not in served
    routes = [r for r in server.app.routes if isinstance(r, APIRoute) and "GET" in r.methods]
    assert [r.path for r in routes if "ticker" in inspect.signature(r.endpoint).parameters] == []
    assert {p: s for p, s in served.items() if s != (LIVE, False)} == {}


def test_the_page_reads_no_route_only_its_socket():
    """Every value reaches the page on its one socket (docs/DATA_FLOW.md §1, AGENTS.md rule 4).

    The routes left read nothing the page draws: the page and its icon, the launcher's health
    and build (launch.py), and the operator's commands (an add or removal of a watchlist
    ticker, the flow panel's contract), whose answers are their results.
    """
    routes = {
        (method, r.path)
        for r in server.app.routes
        if isinstance(r, APIRoute)
        for method in r.methods
    }
    assert routes == {
        ("GET", "/"),
        ("GET", "/favicon.ico"),
        ("GET", "/api/health"),
        ("GET", "/api/build"),
        ("POST", "/api/watchlist"),
        ("DELETE", "/api/watchlist/{ticker}"),
        ("POST", "/api/flow-contract"),
    }


def test_strike_side_sums_split_at_the_live_spot(held):
    rows = held.snap.per_strike["all"]
    below = [r for r in rows if r[0] < LIVE]
    above = [r for r in rows if r[0] > LIVE]
    assert below and above, "the real chain has strikes on both sides of the live price"
    body = push_strikes.strikes(TK, time_et.now(), AUTO)
    sums = body["today_side_sums"]
    assert server.resolve_spot(TK, now=time_et.now())[0] == LIVE
    assert sums["gex_below"] == pytest.approx(sum(r[1] for r in below), abs=0.1)
    assert sums["gex_above"] == pytest.approx(sum(r[1] for r in above), abs=0.1)


def test_chain_serves_this_expirys_net_gex_from_the_heatmaps_own_column(held):
    """Strike Detail's Net row: this expiry's column of the published surface, verbatim.

    Each ladder row carries the surface's cell at its strike; a strike the surface has no value
    for carries None (unknown), never 0.
    """
    surf = held.gamma_surface
    col = [e["expiry"] for e in surf["expirations"]].index(EXPIRY)
    cells = {c["strike"]: c["gex"][col] for c in surf["cells"]}
    assert any(v is not None for v in cells.values()), "the real chain yields net GEX cells"
    body = push_chain.chain(TK, time_et.now(), {"expiry": EXPIRY})
    assert body["ladder"] and "net_gex_by_strike" not in body
    for row in body["ladder"]:
        assert row["net_gex"] == cells.get(row["strike"])
    # every surface value of this expiry reaches the ladder row at its strike
    shown = {r["strike"]: r["net_gex"] for r in body["ladder"]}
    assert {k: v for k, v in cells.items() if v is not None and k in shown} == {
        k: v for k, v in shown.items() if v is not None
    }


def test_oi_and_volume_cells_carry_the_served_total(held):
    """The OI/Volume heatmap colours by the cell's served total.

    Schwab's call OI + put OI at the strike, read straight from the chain; the browser adds
    nothing.
    """
    surf = held.gamma_surface
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


@pytest.mark.usefixtures("held")
def test_days_to_expiry_are_schwabs_as_sent():
    """The expiry dropdown's DTE: Schwab's daysToExpiration from the chain.

    Not the browser's clock (it counted days in UTC, a day off after 7 PM Central).
    """
    body = push_expiries.expiries(TK, time_et.now())
    assert body["expiries"] == [EXPIRY]
    assert body["dte"] == {EXPIRY: _CONTRACTS[0]["daysToExpiration"]}
    # the dropdown's texts are served (the page reformatted the date itself)
    y, m, d = EXPIRY.split("-")
    assert body["labels"] == {EXPIRY: f"{m}/{d}/{y}"}
    assert body["dte_text"] == {EXPIRY: f"{_CONTRACTS[0]['daysToExpiration']:g}DTE"}


def test_with_no_published_levels_the_expiries_carry_the_levels_reason():
    body = push_expiries.expiries("ZZNOLEVELS", time_et.now())
    assert (
        body["expiries"] is None  # unknown, never an empty list standing for it
        and body["reason"]
        == push_verdict.terrain_staleness(None, "ZZNOLEVELS", now=time_et.now())[
            "levels_stale_reason"
        ]
    )


@pytest.mark.parametrize(
    "route",
    [
        lambda: push_chain.chain("SPY", time_et.now(), {"expiry": "2026-10-22"}),
        lambda: push_surface.gamma_surface(
            "SPY", time_et.now(), {**AUTO, "cols": None, "expiry": None}, requested=False
        ),
        lambda: push_strikes.strikes("SPY", time_et.now(), AUTO),
    ],
    ids=["chain", "gamma-surface", "terrain-strikes"],
)
def test_the_spot_row_is_served(route):
    """The row every panel marks as spot: the listed strike nearest the live price, served.

    It was worked out in six places in the page. SPY's 2026-10-22 close capture, published at the
    price Schwab sent in it (764.04), and SPY's first print after it a strike away (16:39:03 ET,
    LAST_PRICE 773.1269, as the daemon received it): the row is the live price's strike.
    """
    print_ = SPY_PRINT_A_STRIKE_AWAY
    strikes = sorted({float(c["strikePrice"]) for c in SPY_CLOSE.chain})
    live = min(strikes, key=lambda k: abs(k - print_["native"]["LAST_PRICE"]))
    assert live != min(strikes, key=lambda k: abs(k - SPY_CLOSE.spot))
    held = SPY_CLOSE
    publish_capture(
        "SPY", held.chain, held.now.timestamp(), held.spot, held.now.date().isoformat(), held.now
    )
    lmp.record_from_level_one_equity("SPY", print_["native"], received_ts=print_["ts_recv"])
    lmp.record_feed_heartbeat(
        daemon_status(time_et.now(), schwab_socket_open=True, held={"LEVELONE_EQUITIES": ["SPY"]})
    )
    try:
        body = route()
    finally:
        with level_store._lock:
            level_store._levels.pop("SPY", None)
        lmp._by_ticker.pop("SPY", None)
        lmp._fields_by_ticker.pop("SPY", None)
        lmp.record_feed_heartbeat(daemon_status(time_et.now(), schwab_socket_open=True))
        lmp.record_feed_down()
    assert body["spot_strike"] == live


def test_put_call_ratios_over_every_expiry_are_served(held):
    """With no expiry selected the Put/Call rows show the whole book, served.

    The page used to pick the first expiry in its list, an expired one on 2026-09-27.
    """
    assert held.snap.pcr_all is not None
    assert held.snap.pcr_all == held.snap.pcr_by_expiry[EXPIRY]  # one expiry: the same book


def test_heatmap_column_state_cell_age_and_front_expiry_are_served():
    """Column streaming status and a cell's time come from the server's own stream states.

    The front column is the nearest unexpired expiry. One call streaming (its update 2 s before the
    publication, carrying the gamma Schwab sent for it): the column is partly streaming and the
    cell's leg carries the time that update was received.
    """
    call = next(c for c in _CONTRACTS if c["putCall"] == "CALL" and c.get("gamma") is not None)
    sym = call["symbol"]
    _daemon(_AT.timestamp(), [sym])
    ofs._ingest_pushed(
        f"optquote.{sym}",
        verbatim_msg(
            symbol=sym,
            content={"key": sym, "GAMMA": call["gamma"]},
            src="schwab_options_l1",
            ts_recv=_AT.timestamp() - 2,
        ),
    )
    try:
        _publish(_AT.timestamp() - 10)
        body = push_surface.gamma_surface_payload(
            TK, "all", None, 0, None, None, _AT, requested=False
        )
    finally:
        _forget()
    assert body["stream_by_expiry"][EXPIRY] == "partial"
    received = [
        c["stream"][0]["call"]["ts_recv"]
        for c in body["cells"]
        if c["stream"][0] and c["stream"][0]["call"]["ts_recv"] is not None
    ]
    assert received == [_AT.timestamp() - 2]
    assert [e["expiry"] for e in body["expirations"] if e["front"]] == [EXPIRY]


@pytest.mark.usefixtures("held")
def test_chain_flags_are_served():
    """ADJUSTED DELIVERABLE and duplicate contracts: served flags, not page rules."""
    body = push_chain.chain(TK, time_et.now(), {"expiry": EXPIRY})
    plain = [c["symbol"] for c in _CONTRACTS if len(c.get("optionDeliverablesList") or []) == 1]
    assert plain and not set(plain) & set(body["adjusted_deliverable_symbols"])
    assert body["has_duplicate_contracts"] is False


def test_an_index_option_is_not_flagged_adjusted_only_schwabs_nonstandard_would_be():
    """An index option is not flagged adjusted; only Schwab's nonStandard would be.

    TICK-03 (2026-09-28 audit): the page's ADJUSTED DELIVERABLE flag was our own rule, which
    compared Schwab's deliverable symbol "$SPX" with the ticker stripped of its "$" -- so every
    $SPX and $VIX contract read adjusted, while Schwab's own nonStandard flag was false on all 43
    board tickers. The flag is Schwab's, as sent: real $SPX contracts
    (tests/fixtures/real_spx_chain_contracts_2026_09_28.json, nonStandard false) are not flagged.
    """
    fx = json.loads(
        (Path(__file__).parent / "fixtures" / "real_spx_chain_contracts_2026_09_28.json").read_text(
            encoding="utf-8"
        )
    )
    at = datetime.fromtimestamp(fx["ts_utc"], ET)
    lmp.record_feed_heartbeat(
        daemon_status(time_et.now(), schwab_socket_open=True, held={"LEVELONE_EQUITIES": ["$SPX"]})
    )
    lmp.record_from_level_one_equity(
        "$SPX",
        {"LAST_PRICE": fx["spot"], "TRADE_TIME_MILLIS": int(fx["ts_utc"] * 1000)},
        received_ts=fx["ts_utc"],
    )
    try:
        server._publish_levels("$SPX", read_chain(fx["contracts"]), fx["ts_utc"], now=at)
        body = push_chain.chain("$SPX", time_et.now(), {"expiry": "2026-10-16"})
    finally:
        with level_store._lock:
            level_store._levels.pop("$SPX", None)
        lmp._by_ticker.pop("$SPX", None)
        lmp._fields_by_ticker.pop("$SPX", None)
        lmp.record_feed_down()
    assert {c["nonStandard"] for c in fx["contracts"]} == {False}
    assert (
        len(body["contracts"]) == len(fx["contracts"])
        and body["adjusted_deliverable_symbols"] == []
    )


def test_the_largest_gex_strike_is_served(held):
    rows = held.snap.per_strike["all"]
    body = push_strikes.strikes(TK, time_et.now(), AUTO)
    top = max(rows, key=lambda r: abs(r.value))
    # the row by name, with its net GEX and volume as the screen shows them
    assert body["max_abs_row"] == {
        "strike": top.strike,
        "strike_text": strike_text(top.strike),
        "value": top.value,
        "volume": top.volume,
        "text": dollars_text(top.value),
        "volume_text": count_text(top.volume),
    }


def test_at_any_hour_the_price_is_schwabs_last_trade_with_schwabs_trade_time():
    """Sunday 2026-09-27: the daemon held SPY's last trade (Friday 18:59:59 CT).

    It is replayed as it captured it (stream_quotes_raw). Operator, 2026-10-01: "From Schwab's
    mouth to our UI's ears. Period." -- no live/closed verdict by our clock: the row serves
    Schwab's last price as the spot with Schwab's trade time, and every consumer reads it.
    """
    mark_feed_live("SPY")
    lmp.record_from_level_one_equity(
        "SPY", {"LAST_PRICE": 772.04, "TRADE_TIME_MILLIS": 1790380799830}, received_ts=time_et.now()
    )
    row = ofs.price_row("SPY", time_et.now())  # the daemon's one row, as the console reads it
    try:
        spot = server.resolve_spot("SPY", now=time_et.now())
    finally:
        lmp._by_ticker.pop("SPY", None)
        lmp._fields_by_ticker.pop("SPY", None)
        lmp.record_feed_down()
    assert (row["spot"], row["spot_disp"], row["trade_time_ct"]) == (
        772.04,
        "772.04",
        "Fri 09/25 06:59 PM CT",
    )
    assert "spot_state" not in row and "closed_last" not in row
    assert spot == (772.04, server.SPOT_SOURCE_PLANE, 1790380799.83)
