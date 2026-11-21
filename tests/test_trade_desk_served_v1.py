"""The Trade Desk computes nothing (P1-3, PR B): every value it shows is served.

Real data only: Schwab's SPY 1-minute bars (2026-09-24/25), SPY level crosses (2026-09-09..25), a
TSLA NASDAQ book and the SPY 0DTE and CRWD chains (tests/fixtures). Expected values are worked
out here from the fixtures themselves.
"""

import json
from dataclasses import fields
from datetime import datetime
from pathlib import Path

import pytest

import app.options.order_flow.state as ofls
import live_market_plane as lmp
import live_price_rows
import server
import time_et
from app.options.order_flow import streaming as ofs
from calc.liquidity_value_engine import LEVEL_NAMES, PHASE2A_LEVEL_IDS
from calc.order_flow import (
    FlowInput,
    _tilt,
    book_readout,
    compute_book_microstructure,
)
from calc.terrain_engine import (
    SAME_DAY_LEVELS,
    WALL_BREACHED,
    WALL_CONTAINS,
    compute_terrain,
    price_relations,
)
from calc.terrain_read import level_side
from db import LevelCrossEvent
from option_contract import read_chain
from push import confluence as push_confluence
from push import desk as push_desk
from push import levels as push_levels
from push import liquidity as push_liquidity
from state import bar_store, cross_store, level_store, price_level_store
from tests.feed_live_helper import (
    daemon_bars,
    daemon_status,
    hold_schwab_daily,
    keep_candles,
    newest_bars,
    price_history,
    publish_capture,
    recorder,
    stored_crosses,
)
from tests.real_chains import (
    SPY_0DTE,
    SPY_AFTER_HOURS_PRINT,
    SPY_CLOSE,
    SPY_PRINT_A_STRIKE_AWAY,
    SPY_PRINT_ON_A_STRIKE,
    book_ranks,
)
from time_et import ET

_FX = Path(__file__).resolve().parent / "fixtures"


def _load(name):
    return json.loads((_FX / name).read_text(encoding="utf-8"))


def test_the_book_side_is_served_from_the_real_book():
    fx = _load("real_equity_book.json")
    nat = fx["book"]["native"]
    bid5 = sum(r["TOTAL_VOLUME"] for r in nat["BIDS"][:5])
    ask5 = sum(r["TOTAL_VOLUME"] for r in nat["ASKS"][:5])
    book = ofls.read_book(nat, "NYSE_BOOK")  # the one reader, as the console's intake reads it
    m = compute_book_microstructure(FlowInput(book=book), now_ts=fx["book"]["ts_recv"])
    assert (m["depth"]["5"]["bid_total"], m["depth"]["5"]["ask_total"]) == (bid5, ask5)
    # the book's lean, a word, is the Liquidity readout's (the one producer): this book's top five
    # (440 bid, 1,840 ask: -61.4%) is OFFER_HEAVY
    readout = book_readout({"NYSE_BOOK": book, "NASDAQ_BOOK": None})["NYSE_BOOK"]
    assert readout["views"]["5"]["pct"] == pytest.approx((bid5 - ask5) / (bid5 + ask5) * 100)
    assert _tilt(readout["views"]["5"]["pct"]) == "OFFER_HEAVY"


def _desk_events(tk, crosses, now, tf, limit=12000):
    """Build the desk's queue at `now` on real crosses, its chart asking `limit` minutes of bars.

    Written by the console's own writer under `tk` (a stand-in ticker no other test holds, so it
    has no live price either), loaded as the console's start loads them. Returns the queue and
    the rows as stored (their cross ids).
    """
    stored = stored_crosses(
        recorder(server.get_db().db_path),
        [
            LevelCrossEvent(
                **{**{f.name: r[f.name] for f in fields(LevelCrossEvent)}, "ticker": tk}
            )
            for r in crosses
        ],
    )
    ofs.bind_daemon(None)
    cross_store._crosses.pop(tk, None)
    cross_store.load([tk])
    try:
        return push_desk.desk_events_payload(tk, tf, now, limit), stored
    finally:
        cross_store._crosses.pop(tk, None)


@pytest.mark.parametrize(
    "tk,crosses,now",
    [
        (
            "ZZDESKSPY",
            "real_spy_level_crosses.json",
            datetime(2026, 9, 25, 18, 0, tzinfo=time_et.ET),
        ),
        (
            "ZZDESKSPX",
            "real_spx_level_crosses_2026_09_25_28.json",
            datetime(2026, 9, 28, 12, 0, tzinfo=time_et.ET),
        ),
    ],
)
def test_each_cross_is_served_as_recorded_and_the_chart_draws_the_newest_at_each_level(
    tk, crosses, now
):
    """Each level cross is the queue's entry as recorded; the chart draws the newest per level.

    Its level's price, direction and time -- and the chart's few are the newest cross at each
    level, for the newest DESK_MARKERS levels; a marker and its queue entry are one served item
    (real SPY and $SPX crosses, each under a stand-in ticker).
    """
    body, rows = _desk_events(tk, _load(crosses)["rows"], now, "D")
    items = [it for it in body["items"] if it["dom"] == "LEVELS"]
    assert items
    by_key = {f"x{r.cross_id}": r for r in rows}
    for it in items:
        r = by_key[it["key"]]
        assert (it["price"], it["dir"], it["ts"]) == (r.level_value, r.direction, r.ts_utc)
    newest_at = {}
    for it in sorted(items, key=lambda it: it["ts"]):
        newest_at[it["price"]] = it
    want = {
        it["key"]
        for it in sorted(newest_at.values(), key=lambda it: it["ts"])[-push_desk.DESK_MARKERS :]
    }
    assert {it["key"] for it in items if it["marker"]} == want


def test_a_marker_before_the_charts_first_bar_is_counted_and_worded():
    """Register P-14: the chart left out a marker with no bar to stand on, uncounted.

    Real SPY level crosses (2026-09-09..25) in the 60-minute desk's two-day window; Schwab's SPY
    1-minute bars of 2026-09-24/25 held as the bar writer holds them, the chart's span the newest
    of them, Friday's: a marker of Thursday's has no bar, and the desk panel counts and words
    those. Stand-in: ticker ZZDESKOFF carries them.
    """
    tk = "ZZDESKOFF"
    minutes = _load("real_spy_1m_bars_2026_09_24_25.json")["bars"]
    friday = [
        b
        for b in minutes
        if datetime.fromtimestamp(b["timestamp"] / 1000, ET).date().isoformat() == "2026-09-25"
    ]
    keep_candles(tk, minutes)
    try:
        body, _rows = _desk_events(
            tk,
            _load("real_spy_level_crosses.json")["rows"],
            datetime(2026, 9, 25, 18, 0, tzinfo=time_et.ET),
            "60",
            len(friday),
        )
    finally:
        bar_store._bars.pop(tk, None)
    # the 60-minute chart's first bar: the hour of the clock Friday's first minute (09:30 ET) is in
    first = friday[0]["timestamp"] / 1000 // 3600 * 3600
    marked = [it for it in body["items"] if it["dom"] == "LEVELS" and it["marker"]]
    off = [it for it in marked if it["ts"] < first]
    assert 0 < len(off) < len(marked)
    assert body["markers_off_chart"] == len(off)
    assert body["markers_off_chart_text"] == (
        f"{len(off)} of {len(marked)} chart markers not drawn: their crosses are before the "
        "chart's first bar, Fri 09/25 08:00 AM CT"
    )


#: Wednesday 2026-10-07 after the close: the desk's "this session" window opens at 09:30 ET, the
#: regular open Schwab's /markets sent for that day (tests/conftest.py)
_WED_EVENING = datetime(2026, 10, 7, 18, 0, tzinfo=time_et.ET)


def test_the_desk_event_feed_numbers_orders_and_counts_the_real_crosses():
    """SPY's level crosses of 2026-10-06 and 10-07 as the console recorded them.

    From tests/fixtures/real_spy_level_crosses_2026_10_06_07.json, written by the console's own
    writer and loaded as its start loads them. Stand-in: ticker ZZDESKX carries them.
    """
    tk = "ZZDESKX"
    fx = _load("real_spy_level_crosses_2026_10_06_07.json")["rows"]
    stored_crosses(
        recorder(server.get_db().db_path),
        [
            LevelCrossEvent(
                **{**{f.name: r[f.name] for f in fields(LevelCrossEvent)}, "ticker": tk}
            )
            for r in fx
        ],
    )
    ofs.bind_daemon(None)
    cross_store._crosses.pop(tk, None)
    cross_store.load([tk])
    try:
        body = push_desk.desk_events_payload(tk, "30", _WED_EVENING, 12000)
    finally:
        cross_store._crosses.pop(tk, None)
    start = datetime(2026, 10, 7, 9, 30, tzinfo=time_et.ET).timestamp()
    assert body["window_start_ts_utc"] == start
    # the events: the window's crosses, one per (time, value, direction)
    events = {}
    for r in fx:
        if r["ts_utc"] >= start:
            events.setdefault((r["ts_utc"], r["level_value"], r["direction"]), r)
    crosses = [it for it in body["items"] if it["dom"] == "LEVELS"]
    assert len(crosses) == len(events) > 0
    assert sorted(it["n"] for it in crosses) == list(range(1, len(events) + 1))
    oldest = min(events)[0]
    assert next(it for it in crosses if it["n"] == 1)["ts"] == oldest
    ts = [it["ts"] for it in body["items"] if it["ts"] is not None]
    assert ts == sorted(ts, reverse=True)  # newest first
    up = sum(1 for k in events if k[2] == "up")
    assert body["cross_counts"] == {"up": up, "down": len(events) - up}


def _spy_close_at(msg):
    """SPY's 2026-10-22 close capture published at Schwab's price in it (764.04).

    And every relation of a real SPY print after it (`msg`, as the daemon received it) to those
    levels.
    """
    published = compute_terrain(
        "SPY",
        read_chain(SPY_CLOSE.chain),
        SPY_CLOSE.spot,
        now=SPY_CLOSE.now,
        sessions=time_et.sessions(),
    ).to_dict()
    ranks = book_ranks(SPY_CLOSE.chain, SPY_CLOSE.spot)  # worked out from the raw chain
    assert (published["put_wall"], published["call_wall"]) == (
        ranks["put_wall"],
        ranks["call_wall"],
    )
    assert (published["put_wall"], published["call_wall"]) == (764.0, 765.0)
    price = msg["native"]["LAST_PRICE"]
    return published | price_relations(published, price).to_dict() | {"spot": price}


def test_the_flip_side_is_the_live_prices():
    for msg in (SPY_AFTER_HOURS_PRINT, SPY_PRINT_A_STRIKE_AWAY):
        out = _spy_close_at(msg)
        side = level_side(out["gamma_flip"], out["spot"])
        assert (
            out["flip_relation"]
            == {None: None, "ABOVE": "BELOW", "BELOW": "ABOVE", "AT": "AT"}[side]
        )


def test_a_breached_wall_says_where_the_live_price_is():
    """The 16:39 print (773.1269) is past the call wall 765.

    The 16:33 print (764.00) is on the put wall 764, which contains nothing there.
    """
    out = _spy_close_at(SPY_PRINT_A_STRIKE_AWAY)
    assert (
        out["call_wall_state"] == WALL_BREACHED and out["call_wall_lean"] == "BREACHED — spot above"
    )
    out = _spy_close_at(SPY_PRINT_ON_A_STRIKE)
    assert out["spot"] == out["put_wall"]
    assert out["put_wall_state"] == WALL_BREACHED and out["put_wall_lean"] == "BREACHED — spot at"
    assert out["call_wall_state"] == WALL_CONTAINS


def test_a_containing_wall_carries_no_word():
    """The 18:00 print (764.27) is between the put wall 764 and the call wall 765.

    Both walls hold the price, which their states say; neither carries a word (operator
    2026-11-19: the dealer words are gone).
    """
    out = _spy_close_at(SPY_AFTER_HOURS_PRINT)
    assert out["call_wall_state"] == out["put_wall_state"] == WALL_CONTAINS
    assert out["regime"] != "UNAVAILABLE"
    assert out["call_wall_lean"] is None and out["put_wall_lean"] is None


#: Stand-in: ticker ZZDESK carries Schwab's SPY bars and SPY 0DTE chain, ZZDESKEM the CRWD chain
DESK, DESK_EM = "ZZDESK", "ZZDESKEM"
#: the levels are served after Friday 2026-10-02's close
FRIDAY_CLOSE = datetime(2026, 10, 2, 16, 5, tzinfo=time_et.ET)


def _spy_bars() -> list:
    """Schwab's SPY 1-minute bars of Thursday 2026-10-01 and Friday 10-02.

    From its /pricehistory answer of 2026-10-07
    (tests/fixtures/real_pricehistory_spy_tsla_2026_10_07.json), every candle of those two ET
    days.
    """
    days = {"2026-10-01", "2026-10-02"}
    return [
        {
            "timestamp": c["datetime"],
            "open": c["open"],
            "high": c["high"],
            "low": c["low"],
            "close": c["close"],
            "volume": c["volume"],
        }
        for c in price_history("SPY", "1m")["body"]["candles"]
        if datetime.fromtimestamp(c["datetime"] / 1000, time_et.ET).date().isoformat() in days
    ]


def _forget(tk):
    bar_store._bars.pop(tk, None)
    lmp._by_ticker.pop(tk, None)
    lmp._fields_by_ticker.pop(tk, None)
    with level_store._lock:
        level_store._levels.pop(tk, None)
    for key in [k for k in price_level_store._MATERIALIZED_SNAPSHOTS if k[0] == tk]:
        del price_level_store._MATERIALIZED_SNAPSHOTS[key]


def _priced(tk, chain, spot, ts_utc):
    """Price the chain as the console prices a stored capture (at its own time and spot)."""
    at = datetime.fromtimestamp(ts_utc, time_et.ET)
    publish_capture(tk, chain, ts_utc, spot, at.date().isoformat(), at)
    return level_store.published_levels(tk).served()


def _live_price(tk, last):
    """Schwab's LAST_PRICE in the daemon's plane, its feed live at FRIDAY_CLOSE.

    FRIDAY_CLOSE is the time the levels are served at.
    """
    at = FRIDAY_CLOSE.timestamp()
    lmp.record_feed_heartbeat(
        daemon_status(at, schwab_socket_open=True, held={"LEVELONE_EQUITIES": [tk]})
    )
    lmp.record_from_level_one_equity(tk, {"LAST_PRICE": last}, received_ts=at)


@pytest.fixture
def spy_levels():
    """ZZDESK's levels served after Friday's close.

    The SPY 0DTE chain priced at its capture time (tests/real_chains.py), the SPY bars published
    by the bar writer, and the last bar's close as Schwab's LAST_PRICE (stand-in). Returns
    (spot, terrain, serve(tf)).
    """
    bars = _spy_bars()
    _forget(DESK)
    terrain = _priced(DESK, SPY_0DTE.chain, SPY_0DTE.spot, SPY_0DTE.now.timestamp())
    spot = bars[-1]["close"]
    keep_candles(DESK, bars)
    server._publish_price_levels(DESK, FRIDAY_CLOSE)  # as the bar writer does

    def serve(tf="1"):
        _live_price(DESK, spot)
        return push_levels.levels_payload(DESK, tf, FRIDAY_CLOSE)

    yield spot, terrain, serve
    _forget(DESK)


def test_levels_carry_the_gamma_family_into_the_one_distance_order(spy_levels):
    spot, terrain, serve = spy_levels
    body = serve()
    by_id = {r["id"]: r for r in body["levels"]}
    assert (
        sum(terrain.get(gid) is not None for gid, _ in server.OPTION_LEVELS) >= 8
    )  # the real chain prices most
    for gid, _label in server.OPTION_LEVELS:
        if terrain.get(gid) is not None:
            assert by_id[gid]["family"] == "gamma" and by_id[gid]["price"] == terrain[gid]
            assert gid in body["by_distance"]
    priced = [r for r in body["levels"] if r["price"] is not None]
    assert body["by_distance"] == [
        r["id"] for r in sorted(priced, key=lambda r: abs(r["price"] - spot))
    ]
    assert all(
        r["side"] == level_side(r["price"], spot) and r["distance"] == r["price"] - spot
        for r in priced
    )


#: every key and word the implied one-day move and its ±1σ band were served under (operator
#: 2026-11-20: the bands are removed from everywhere)
ONE_DAY_MOVE = {
    "implied_1d_move",
    "atm_iv_text",
    "move_points_text",
    "move_dte_text",
    "move_text",
    "em_up",
    "em_dn",
    "expected_move",
    "+1σ move",
    "−1σ move",
    "EM+",
    "EM−",
}


def _keys_and_words(value, out):
    """Collect every key and every string of a served payload, at any depth."""
    if isinstance(value, dict):
        for k, v in value.items():
            out.add(k)
            _keys_and_words(v, out)
    elif isinstance(value, list):
        for v in value:
            _keys_and_words(v, out)
    elif isinstance(value, str):
        out.add(value)
    return out


def test_no_payload_serves_a_one_day_move_or_its_band():
    """Real CRWD chain (expiries a day and more out), priced at 2026-09-02 12:00 ET.

    The chain that priced a one-day move and its ±1σ band: the terrain, the levels, the
    confluence matrix and the liquidity zones served from it carry neither, by any key or word,
    and no confluence row is marked inside a band. Stand-in: its capture spot as Schwab's
    LAST_PRICE.
    """
    fx = _load("real_crwd_complete_chain_quarter.json")
    spot = float(fx["spot"])
    priced_at = datetime(2026, 9, 2, 12, 0, tzinfo=time_et.ET)
    _forget(DESK_EM)
    try:
        terrain = _priced(DESK_EM, fx["chain"], spot, priced_at.timestamp())
        _live_price(DESK_EM, spot)
        levels = push_levels.levels_payload(DESK_EM, "1", FRIDAY_CLOSE)
        # the matrix of the chain's one expiry (2026-09-18), asked while it is open
        confluence = push_confluence.confluence_payload(DESK_EM, None, priced_at)
        liquidity = push_liquidity.liquidity_snapshot(DESK_EM, FRIDAY_CLOSE)
    finally:
        _forget(DESK_EM)
    assert terrain["call_wall"] is not None and levels["levels"] and confluence["rows"]
    for name, body in (
        ("terrain", terrain),
        ("levels", levels),
        ("confluence", confluence),
        ("liquidity", liquidity),
    ):
        assert not ONE_DAY_MOVE & _keys_and_words(body, set()), name
    assert not any("inside" in row for row in confluence["rows"])


#: every id and word the VWAP's standard deviation bands were served under (operator 2026-11-20)
VWAP_BANDS = {
    "VWAP_P1",
    "VWAP_M1",
    "VWAP_P2",
    "VWAP_M2",
    "VWAP +1σ",
    "VWAP −1σ",
    "VWAP +2σ",
    "VWAP −2σ",
    "VWAP+1σ",
    "VWAP−1σ",
    "VWAP+2σ",
    "VWAP−2σ",
}


def test_no_payload_serves_a_vwap_band(spy_levels):
    """SPY's real 1-minute bars (2026-10-01 and 02), whose session priced VWAP bands.

    The levels at every chart timeframe and the liquidity zones carry the session VWAP, its line
    and its level, and no band of standard deviations: no band level, no band word, and each
    point of the VWAP curve is [time, vwap].
    """
    _spot, _terrain, serve = spy_levels
    liquidity = push_liquidity.liquidity_snapshot(DESK, FRIDAY_CLOSE)
    for tf in ("1", "5", "15"):
        body = serve(tf)
        assert "VWAP" in {r["id"] for r in body["levels"]}, tf
        assert body["vwap_series"] and all(len(p) == 2 for p in body["vwap_series"]), tf
        assert not VWAP_BANDS & _keys_and_words(body, set()), tf
    assert not VWAP_BANDS & _keys_and_words(liquidity, set())


def test_every_level_is_served_with_its_name_and_short_tag(spy_levels):
    """Both level names are served now, from one table (LEVEL_NAMES).

    The proximity strip printed raw ids (OVERNIGHT_HIGH, PD_VAH) and the chart kept its own
    short-name table.
    """
    _spot, _terrain, serve = spy_levels
    body = serve()
    snap = [r for r in body["levels"] if r["id"] in LEVEL_NAMES]
    assert len(snap) >= 8  # the real SPY bars price most of them
    # every level the engine can produce has its name: none is ever served by its id
    assert set(PHASE2A_LEVEL_IDS) <= set(LEVEL_NAMES)
    assert "VWAP" in {r["label"] for r in snap} and not any("σ" in r["label"] for r in snap)
    for r in body["levels"]:
        assert r["label"] and r["short"], r["id"]
        if r["id"] in LEVEL_NAMES:
            assert (r["label"], r["short"]) == LEVEL_NAMES[r["id"]]
    # the 0DTE rows too: a page draws `label`, never an id in its place
    assert [r["label"] for r in body["zero_dte"]] == [label for _id, label in SAME_DAY_LEVELS]


def test_vwap_is_served_per_chart_bar(spy_levels):
    _spot, _terrain, serve = spy_levels
    one = serve("1")["vwap_series"]
    fifteen = serve("15")["vwap_series"]
    buckets = {}
    for r in one:  # stamped with the bar's start, the last minute's value
        k = int(r[0] // 900)
        buckets[k] = [k * 900] + list(r[1:])
    assert len(one) > 100 and fifteen == [buckets[k] for k in sorted(buckets)]


def test_levels_are_served_in_ladder_order_with_distance(spy_levels):
    """The levels panel and the Trade Desk used to sort and measure levels in the page.

    They sorted levels, measured distance to spot and applied the 0.15% near-spot rule in the
    page. Real SPY 1-minute bars (2026-10-01 and 02).
    """
    spot, _terrain, serve = spy_levels
    body = serve()
    priced = [r for r in body["levels"] if r["price"] is not None]
    assert len(priced) > 5
    assert [r["price"] for r in priced] == sorted((r["price"] for r in priced), reverse=True)
    for r in priced:
        assert r["distance"] == pytest.approx(r["price"] - spot)
        assert "near_spot" not in r  # no proximity flag (operator 2026-09-29)
    assert body["by_distance"] == [
        r["id"] for r in sorted(priced, key=lambda r: abs(r["price"] - spot))
    ]


def test_the_volume_profile_the_value_area_is_read_from_is_served(spy_levels):
    """The Trade Desk reference draws the session's volume profile at the chart's left edge.

    That is as of 2026-09-28. The profile was built for the value area and dropped; /api/levels
    serves that same profile: its POC/VAH/VAL are the served TODAY_ levels, its bins hold every
    RTH bar's volume, and each bin says whether it is inside the value area. Real SPY 1-minute
    bars.
    """
    _spot, _terrain, serve = spy_levels
    body = serve()
    vp = body["volume_profile"]
    by_id = {r["id"]: r["price"] for r in body["levels"]}
    assert (vp["poc"], vp["vah"], vp["val"]) == (
        by_id["TODAY_POC"],
        by_id["TODAY_VAH"],
        by_id["TODAY_VAL"],
    )
    prices = [b[0] for b in vp["bins"]]
    assert prices == sorted(prices) and len(prices) > 100
    assert all(b[2] == (vp["val"] <= b[0] <= vp["vah"]) for b in vp["bins"])
    # the profile's scale is served: the POC bin's volume, the largest
    assert (
        vp["max_volume"]
        == max(b[1] for b in vp["bins"])
        == next(b[1] for b in vp["bins"] if b[0] == vp["poc"])
    )
    at = [(datetime.fromtimestamp(b["timestamp"] / 1000, time_et.ET), b) for b in _spy_bars()]
    rth = [
        b
        for d, b in at
        if d.date().isoformat() == "2026-10-02" and time_et.session_label(d) == "RTH"
    ]
    # every RTH bar's volume is in the profile; a bar that sent no volume cannot be placed and is
    # counted and served (operator 2026-09-29: accounted for, not silently dropped) -- Schwab sent
    # volume on every one of Friday's 390
    assert sum(b[1] for b in vp["bins"]) == pytest.approx(
        sum(b["volume"] for b in rth if b["volume"] is not None), rel=1e-9
    )
    assert (
        (vp["bars"], vp["bars_without_volume"])
        == (len(rth), sum(1 for b in rth if b["volume"] is None))
        == (390, 0)
    )
    assert vp["basis"].startswith("Estimated volume by price")


def _price(value):
    """Return a price as the operator's format shows it, two decimals, worked apart from code."""
    return f"{value:.2f}"


def test_the_chart_reads_the_prior_value_area_and_the_poc_label_as_served(spy_levels):
    """Register P-16: the desk map picked PD_VAL, PD_VAH, VWAP and TODAY_POC out by id.

    It composed "VA <val> – <vah>" and "POC est <poc>" itself. The levels panel serves the prior
    session's value area (the band's low and high, and its words), the VWAP's words and the POC's
    label. Real SPY 1-minute bars of 2026-10-01 and 02 and Schwab's daily candles of 2026-10-07.
    """
    _spot, _terrain, serve = spy_levels
    hold_schwab_daily("SPY", under=DESK)  # the prior session: Thursday 10-01
    try:
        server._publish_price_levels(DESK, FRIDAY_CLOSE)
        body = serve()
    finally:
        bar_store._series.pop((DESK, "1d"), None)
    by_id = {r["id"]: r["price"] for r in body["levels"]}
    low, high = by_id["PD_VAL"], by_id["PD_VAH"]
    assert low < high
    assert body["prior_value_area"] == {
        "low": low,
        "high": high,
        "text": f"VA {_price(low)} – {_price(high)}",
    }
    assert body["vwap_text"] == _price(by_id["VWAP"])
    vp = body["volume_profile"]
    assert vp["poc"] == by_id["TODAY_POC"] and vp["poc_label"] == f"POC est {_price(vp['poc'])}"
    assert "prior_value_area" not in {f["family"] for f in body["families_absent"]}


def test_no_prior_value_area_band_when_the_prior_session_has_none():
    """Schwab's $SPX 1-minute bars carry no volume: no profile, so no value area for either day.

    The daemon's record of 2026-10-01 and 02 (real_daemon_bars_spx_2026_10_01_02.json) and
    Schwab's $SPX daily candles (real_schwab_daily_spx_2026_10.json): the prior session's value
    area is declared absent with why, and the panel serves no band, no POC label and no VWAP.
    """
    tk = "ZZDESKSPX"
    _forget(tk)
    for r in newest_bars(daemon_bars("real_daemon_bars_spx_2026_10_01_02.json", "$SPX"), "$SPX"):
        bar = server._schwab_bar(
            r["bar_start_ms"], r["open"], r["high"], r["low"], r["close"], r["volume"]
        )
        assert bar is not None
        bar_store.keep_bar(tk, bar)
    hold_schwab_daily("$SPX", under=tk)
    try:
        server._publish_price_levels(tk, FRIDAY_CLOSE)
        body = push_levels.levels_payload(tk, "1", FRIDAY_CLOSE)
    finally:
        bar_store._series.pop((tk, "1d"), None)
        _forget(tk)
    absent = {f["family"]: f["reason"] for f in body["families_absent"]}
    assert absent["prior_value_area"] == (
        "no RTH volume in the prior session 2026-10-01's bars for its volume profile"
    )
    assert {r["id"] for r in body["levels"]} >= {"PDH", "PDL", "PDC"}
    assert body["prior_value_area"] is None
    assert body["volume_profile"] is None and body["vwap_text"] is None


@pytest.mark.usefixtures("spy_levels")
def test_after_the_close_the_levels_are_measured_from_schwabs_last_trade():
    """Monday 2026-09-28 21:40 ET: the Trade Desk chart drew no key level at all after the close.

    /api/levels served 30 SPY levels and an empty by_distance, because it was measured only from a
    live price. The spot is Schwab's last trade at any hour (operator 2026-10-01: "we use what
    schwab gives us and we display it"): the levels are ordered, and their distance measured, from
    it, carrying its trade time. Real SPY 1-minute bars (2026-10-01 and 02); the last trade is the
    one the daemon captured on Friday 10-02 (its newest SPY message that evening).
    """
    at = FRIDAY_CLOSE.timestamp()
    lmp.record_feed_heartbeat(
        daemon_status(at, schwab_socket_open=True, held={"LEVELONE_EQUITIES": [DESK]})
    )
    lmp.record_from_level_one_equity(
        DESK, {"LAST_PRICE": 769.5, "TRADE_TIME_MILLIS": 1790983830151}, received_ts=at
    )
    body = push_levels.levels_payload(DESK, "1", FRIDAY_CLOSE)
    priced = [r for r in body["levels"] if r["price"] is not None]
    assert len(priced) > 5 and body["spot"] == 769.5
    assert body["spot_time_ct"] == "Fri 10/02 06:30 PM CT"  # Schwab's TRADE_TIME_MILLIS
    assert body["by_distance"] == [
        r["id"] for r in sorted(priced, key=lambda r: abs(r["price"] - 769.5))
    ]
    assert all(r["distance"] == r["price"] - 769.5 for r in priced)


def test_the_desk_window_is_schwabs_last_session_open_and_its_words_are_served():
    """Register P-15: the page kept its own copy of the lookback words.

    The window's session start was a hard-coded 9:30 with a 24-hour stand-in when no session was
    found. The open is the one Schwab's /markets sent (tests/conftest.py).
    """
    sat = datetime(2026, 10, 3, 11, 0, tzinfo=ET)  # Saturday: Friday's open
    assert (
        push_desk._desk_window_start("30", sat)
        == datetime(2026, 10, 2, 9, 30, tzinfo=ET).timestamp()
    )
    mon = datetime(2026, 10, 5, 10, 0, tzinfo=ET)
    assert (
        push_desk._desk_window_start("30", mon)
        == datetime(2026, 10, 5, 9, 30, tzinfo=ET).timestamp()
    )
    assert push_desk._desk_window_start("1", mon) == mon.timestamp() - 900
    # the reference's 5-minute Market Map lists the session's events (its queue: "since open")
    assert (
        push_desk._desk_window_start("5", mon)
        == datetime(2026, 10, 5, 9, 30, tzinfo=ET).timestamp()
    )
    words = {tf: words for tf, (_lb, words) in push_desk.DESK_LOOKBACK.items()}
    assert words["30"] == words["5"] == "this session"


def test_every_bar_carries_its_change():
    for b in _load("real_spy_1m_bars_2026_09_24_25.json")["bars"][:50]:
        bar = live_price_rows.bar_change(b["open"], b["close"])
        assert bar["chg"] == pytest.approx(b["close"] - b["open"])
        assert bar["chg_pct"] == pytest.approx((b["close"] - b["open"]) / b["open"] * 100)
        # as the pinned readout shows it: signed, two decimals, the percent beside it
        chg, pct = b["close"] - b["open"], (b["close"] - b["open"]) / b["open"] * 100
        chg_sign, pct_sign = ("+" if chg >= 0 else "-"), ("+" if pct >= 0 else "-")
        want = f"{chg_sign}{abs(chg):.2f} ({pct_sign}{abs(pct):.2f}%)"
        assert bar["chg_text"] == want, b


def test_a_bar_with_an_open_of_zero_shows_its_change_alone():
    """A percent of an open of 0 is not a number: the text is the change alone."""
    bar = live_price_rows.bar_change(0.0, 1.5)
    assert (bar["chg_pct"], bar["chg_text"]) == (None, "+1.50")
