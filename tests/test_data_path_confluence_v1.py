"""Schwab -> the confluence matrix. The score is the chain already priced, ranked once."""

from __future__ import annotations

import json
import statistics
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import app.options.order_flow.state as ofls
import live_market_plane as lmp
import live_price_rows
import server
from app.options.order_flow import streaming as ofs
from calc.confluence_composite import (
    LEANS,
    SHADED,
    at_price,
    build_matrix,
    in_score_weights,
    iv_by_strike,
    magnitudes,
    score_magnitudes,
    under_strike,
    window_rows,
)
from calc.math_exposure_core import bucket_metric, compute_exposures_by_strike
from calc.math_levels import compute_charm_by_strike
from calc.terrain_engine import TerrainSnapshot
from calibration.complete_chain_capture import CAPTURE_BASIS, StoredCapture
from numeric_contract import price_text
from option_contract import read_chain
from push import chain as push_chain
from push import confluence as push_confluence
from push import levels as push_levels
from push import strike_rows
from push import verdict as push_verdict
from state import capture_store, level_store
from stream_spine import verbatim_msg
from tests.capture_store import store_capture
from tests.conftest import MARKETS_ANSWERS
from tests.feed_live_helper import ROUND_SEC, daemon_status, publish_capture
from tests.real_chains import (
    CRWD,
    MRVL,
    NFLX,
    SPY_0DTE,
    SPY_AFTER_HOURS_PRINT,
    SPY_CLOSE,
    SPY_PRINT_A_STRIKE_AWAY,
    TSLA,
)
from tests.shared_helpers import fixture_json
from tests.test_order_flow_book_payload_v1 import _same
from tests.test_served_numbers_v1 import screen_text
from time_et import (
    ET,
    INDEX_OPTIONS,
    age_text,
    ct_label,
    record_markets,
    sessions,
    valuation_instant,
)

_FX = Path(__file__).resolve().parent / "fixtures"

_QUOTE = fixture_json("real_crwd_quote_2026_10_07.json")
#: SPY's and TSLA's LEVELONE_EQUITIES messages at their 2026-10-07 chain captures (SPY_0DTE, TSLA)
_AT_CAPTURE = {
    q["ticker"]: q
    for q in fixture_json("real_spy_tsla_quotes_at_chain_capture_2026_10_07.json")["quotes"]
}
_SPY_TWO_CLOSES = fixture_json("real_spy_2026_10_23_expiry_two_closes_2026_10_21_22.json")
_SPY_MONDAY = fixture_json("real_spy_2026_10_19_close_capture_and_premarket_zero_volume.json")
_IWM_ON_A_STRIKE = fixture_json("real_iwm_0dte_chain_priced_on_a_strike_2026_10_23.json")
_SPY_PRINT_ON_A_STRIKE = fixture_json("real_spy_print_on_a_strike_2026_10_22.json")
_SPY_PRINT_ABOVE = fixture_json("real_spy_print_above_the_0dte_strikes_2026_10_23.json")


def _chain_spot(tk: str, quote: dict) -> tuple:
    """Return the spot the daemon sends with a chain completed when `quote` was its last message.

    `quote` is Schwab's LEVELONE_EQUITIES message, the last it had: that message taken in by the
    daemon's plane at its receipt time, and the price row the daemon's own function makes then.
    (LAST_PRICE, its trade time).
    """
    at = quote["ts_recv"]
    lmp.record_from_level_one_equity(tk, quote["native"], received_ts=at)
    lmp.record_feed_heartbeat(
        daemon_status(
            at,
            schwab_socket_open=True,
            held={"LEVELONE_EQUITIES": [tk]},
            chain_round_sec=ROUND_SEC,  # a running daemon reports its round of the watchlist
        )
    )
    row = live_price_rows.price_row(tk, at)
    return row["spot"], row["trade_ts"]


def _forget(tk: str) -> None:
    with level_store._lock:
        level_store._levels.pop(tk, None)
    lmp._by_ticker.pop(tk, None)
    lmp._fields_by_ticker.pop(tk, None)
    lmp.record_feed_heartbeat(daemon_status(0.0, schwab_socket_open=True))
    lmp.record_feed_down()


def _spy_0dte_twice(
    second: list, first_at: datetime, second_ts: datetime, now: datetime
) -> tuple[dict, dict]:
    """SPY's captured 0DTE chain delivered at `first_at`, then `second` taken at `second_ts`.

    Each with SPY's quote at the capture as its chain spot. Return the matrix of the chain's
    expiry as served after each: at `first_at`, then at `now`, when the second is priced.
    """
    tk, expiry = "SPY", str(SPY_0DTE.chain[0]["expirationDate"])[:10]
    try:
        spot = _chain_spot(tk, _AT_CAPTURE[SPY_0DTE.ticker])
        server._publish_levels(
            tk, read_chain(SPY_0DTE.chain), first_at.timestamp(), chain_spot=spot, now=first_at
        )
        first = push_confluence.confluence_payload(tk, expiry, first_at)
        server._publish_levels(
            tk, read_chain(second), second_ts.timestamp(), chain_spot=spot, now=now
        )
        return first, push_confluence.confluence_payload(tk, expiry, now)
    finally:
        _forget(tk)


def _store_by_expiry(tk: str, chain: list, spot: float, at: datetime) -> None:
    """`chain` stored as the capture taken at `at`, one capture per expiry, at Schwab's `spot`."""
    by_expiry: dict = {}
    for ct in chain:
        by_expiry.setdefault(str(ct["expirationDate"])[:10], []).append(ct)
    for exp, cts in by_expiry.items():
        store_capture(
            server.get_db().db_path,
            ticker=tk,
            expiry=exp,
            contracts=[dict(c) for c in cts],
            spot=spot,
            chain_spot=spot,
            completeness_basis=CAPTURE_BASIS,
            ts_utc=at.timestamp(),
        )


def _published_0dte() -> level_store.PublishedLevels:
    """SPY's captured 0DTE chain (SPY_0DTE) published by the levels producer.

    Published as the stored capture it is, at Schwab's price in it.
    """
    held = SPY_0DTE
    publish_capture(
        "SPY", held.chain, held.now.timestamp(), held.spot, held.now.date().isoformat(), held.now
    )
    return level_store.published_levels("SPY")


def _hold_with(levels: level_store.PublishedLevels, **snap_fields) -> None:
    """`levels` held with its snapshot's `snap_fields` in their place.

    The request ranks the expiry it shows on them (_ranked_matrix).
    """
    level_store.publish("SPY", replace(levels, snap=replace(levels.snap, **snap_fields)))


def _book_magnitudes(live: TerrainSnapshot, expiry: str, spot: float) -> dict:
    """Each strike's factor magnitudes of one published expiry, as the matrix builds them."""
    book = next(b for (e, _d), (b, _x) in live.books.items() if e == expiry)
    charm = live.charm_by_expiry[expiry]
    iv = live.iv_by_expiry[expiry]
    mags = {s: magnitudes(b, charm.get(s), iv.get(s), spot) for s, b in book.items()}
    return {s: {k: v for k, v in m.items() if not k.startswith("_")} for s, m in mags.items()}


def _nflx_far_book() -> tuple[dict, dict]:
    """NFLX's 2027-12-17 expiry as the levels producer priced it.

    From tests/real_chains.py NFLX, captured 2026-10-07: its book, and each strike's factor
    magnitudes as the matrix builds them.
    """
    try:
        publish_capture(
            "NFLX",
            NFLX.chain,
            NFLX.now.timestamp(),
            NFLX.spot,
            NFLX.now.date().isoformat(),
            NFLX.now,
        )
        live = level_store.published_levels("NFLX").snap
    finally:
        _forget("NFLX")
    book = next(b for (e, _d), (b, _x) in live.books.items() if e == "2027-12-17")
    return book, _book_magnitudes(live, "2027-12-17", NFLX.spot)


def _traded(m: dict) -> bool:
    return (m["OI"] is not None and m["OI"] > 0) or (m["VOL"] is not None and m["VOL"] > 0)


def _scores_by_definition(mags: dict, weights: dict) -> dict:
    """Return the score as defined, stated apart from the code.

    Over the strikes with open interest or
    volume, each weighted factor's 5th and 95th percentiles (Hyndman-Fan type 7, Python's
    statistics.quantiles with method="inclusive"), each value placed between them and clipped to
    [0, 1], weighted, summed and times 100; a strike missing a weighted factor has none.
    """
    universe = [s for s, m in mags.items() if _traded(m)]
    required = [k for k, w in weights.items() if w > 0]
    cuts = {}
    for k in required:
        q = statistics.quantiles(
            [mags[s][k] for s in universe if mags[s][k] is not None], n=20, method="inclusive"
        )
        cuts[k] = (q[0], q[18])
    out = {}
    for s in universe:
        if any(mags[s][k] is None for k in required):
            continue
        out[s] = 100.0 * sum(
            weights[k] * min(1.0, max(0.0, (mags[s][k] - cuts[k][0]) / (cuts[k][1] - cuts[k][0])))
            for k in required
        )
    return out


def test_a_missing_gamma_blanks_the_score_and_the_top_is_not_100():
    """NFLX's 2027-12-17 book: strikes where Schwab sent no gamma (-999) have no net gamma.

    So their score is absent with that reason. Every other strike's score is the definition's, and
    the top one is not rescaled to 100.
    """
    _book, mags = _nflx_far_book()
    weights = in_score_weights("MONTHLY")
    scored, _flat, spans = score_magnitudes(mags, weights)
    blank = [s for s, m in mags.items() if m["GEXM"] is None and _traded(m)]
    expected = _scores_by_definition(mags, weights)
    assert blank and len(expected) > 10
    assert all(spans[k] is not None for k, w in weights.items() if w > 0)
    assert all(scored[s]["score"] is None and "net gamma" in scored[s]["missing"] for s in blank)
    assert {s: scored[s]["score"] for s in expected} == pytest.approx(
        expected, rel=1e-12, abs=1e-12
    )
    top = max(r["score"] for r in scored.values() if r["score"] is not None)
    assert top == pytest.approx(max(expected.values()), rel=1e-12) and top < 100


def test_an_am_settled_expiry_past_the_year_is_scored():
    """$SPX's AM-settled 2027-12-17 expiry, captured 2026-10-07: each strike has a score.

    The expiry is past the year Schwab's /markets answers: each strike with open interest has
    its charm and vanna, so it has a score, and the score is the definition's.
    """
    fx = fixture_json("real_spx_chain_2026_10_07_2027_12_17.json")
    tk, at = server.ticker_storage_key(fx["ticker"]), datetime.fromtimestamp(fx["ts_utc"], ET)
    try:
        publish_capture(tk, fx["chain"], fx["ts_utc"], fx["spot"], at.date().isoformat(), at)
        live = level_store.published_levels(tk).snap
    finally:
        _forget(tk)
    mags = _book_magnitudes(live, "2027-12-17", fx["spot"])
    weights = in_score_weights("MONTHLY")
    scored, _flat, _spans = score_magnitudes(mags, weights)
    expected = _scores_by_definition(mags, weights)
    assert len(expected) > 10
    assert {s: scored[s]["score"] for s in expected} == pytest.approx(
        expected, rel=1e-12, abs=1e-12
    )


def test_a_missing_factor_is_not_called_flat():
    """NFLX's 2027-12-17 strikes 2.5 to 4, priced by the levels producer.

    Schwab sent -999 for the
    volatility of the calls at 2.5, 3 and 3.5, with no puts open there, so those have no charm, and
    4 has it. Charm does not vary where present, but the note does not call it flat, because it is
    missing elsewhere; each strike missing it has no score and says charm.
    """
    _book, book_mags = _nflx_far_book()
    mags = {s: book_mags[s] for s in (2.5, 3.0, 3.5, 4.0)}
    scored, flat, spans = score_magnitudes(mags, in_score_weights("MONTHLY"))
    traded = [s for s, m in mags.items() if _traded(m)]
    present = [s for s in traded if mags[s]["CHARMM"] is not None]
    assert spans["CHARMM"] is None and present and len(present) < len(traded)
    assert len({mags[s]["CHARMM"] for s in present}) == 1
    assert "CHARMM" not in flat
    assert all(
        scored[s]["score"] is None and "charm" in scored[s]["missing"]
        for s in traded
        if s not in present
    )


def _publish_close(tk: str = "SPY") -> level_store.PublishedLevels:
    """SPY's 2026-10-22 close capture, published as the stored capture it is, at Schwab's price."""
    held = SPY_CLOSE
    publish_capture(
        tk, held.chain, held.now.timestamp(), held.spot, held.now.date().isoformat(), held.now
    )
    return level_store.published_levels(tk)


def test_the_matrix_reads_the_priced_book_and_leaves_flow_out():
    """SPY's 2026-10-22 close capture, its same-day expiry.

    The matrix ranks the book the publication priced, each row's net and gross gamma that book's
    own numbers (millions, two decimals, net signed), flow and the change in gamma empty, and a
    same-day expiry's score cannot pass 72.
    """
    try:
        live = _publish_close()
        book = live.snap.books[("2026-10-22", 0.0)][0]
        body = push_confluence.confluence_payload("SPY", "2026-10-22", SPY_CLOSE.now)
    finally:
        level_store._levels.pop("SPY", None)
    assert body["available"] is True
    assert (body["preset"], body["ceiling"]) == ("0DTE", 72)
    weights = in_score_weights(body["preset"])
    assert weights["FLOWM"] == 0 and weights["DGEXM"] == 0 and "weights_in_score" not in body
    assert body["expiries"][0]["label"] == "0DTE · 2026-10-22"
    checked = grossed = 0
    for row in body["rows"]:
        bucket = book[row["strike"]]
        assert row["strike_text"] == price_text(row["strike"])
        assert row["flow_text"] is None and row["dgex_text"] is None
        net = bucket_metric(bucket, "net_gex_1pct")
        call, put = bucket_metric(bucket, "call_gex_1pct"), bucket_metric(bucket, "put_gex_1pct")
        if net is not None and abs(net) >= 5_000:
            assert row["net_gex_text"] == screen_text(net, "dollars")
            assert row["net_gex"] == net and abs(net) <= body["peaks"]["net_gex"]
            checked += 1
        if call is not None and put is not None and call >= 0 and put >= 0:
            assert row["gross_text"] == screen_text(call + put, "dollars")
            grossed += 1
    assert checked > 5 and grossed > 5


def _rail_levels(body: dict) -> list[dict]:
    """Every level the Confluence answer serves: each lane's inside the rows, then those past."""
    lanes = body["rail_lanes"]
    return [*lanes["session"], *lanes["options"], *body["levels_above"], *body["levels_below"]]


def test_the_rail_sorts_and_places_each_level_against_the_shown_strikes():
    """SPY's 2026-10-22 close capture: the server, not the page, places each level.

    Inside the shown strikes each lane's levels come highest price first; a level above the
    highest strike or below the lowest is listed past them; one price line per price inside,
    marked when a session level sits there; each price names every level at it. An answer
    with no chain has an empty rail.
    """
    try:
        _publish_close()
        body = push_confluence.confluence_payload("SPY", "2026-10-22", SPY_CLOSE.now)
    finally:
        level_store._levels.pop("SPY", None)
    top, bottom = body["rows"][0]["strike"], body["rows"][-1]["strike"]
    assert top > bottom, "the rows run highest strike first"
    for lane, levels in body["rail_lanes"].items():
        assert all(lv["lane"] == lane and bottom <= lv["price"] <= top for lv in levels)
        prices = [lv["price"] for lv in levels]
        assert prices == sorted(prices, reverse=True)
    assert all(lv["price"] > top for lv in body["levels_above"])
    assert all(lv["price"] < bottom for lv in body["levels_below"])
    inside = [*body["rail_lanes"]["session"], *body["rail_lanes"]["options"]]
    assert inside and (body["levels_above"] or body["levels_below"])
    assert sorted(line["price_text"] for line in body["rail_lines"]) == sorted(
        {lv["price_text"] for lv in inside}
    )
    for line in body["rail_lines"]:
        at = [lv for lv in inside if lv["price_text"] == line["price_text"]]
        assert line["session"] == any(lv["lane"] == "session" for lv in at)
    for lv in _rail_levels(body):
        assert lv["title"] in body["level_names"][lv["price_text"]].split(" + ")
    _forget("ZZNOCHAIN")
    none = push_confluence.confluence_payload("ZZNOCHAIN", None, SPY_CLOSE.now)
    assert none["available"] is False
    assert none["rail_lanes"] == {"session": [], "options": []}
    assert none["levels_above"] == none["levels_below"] == none["rail_lines"] == []


def test_a_zero_book_is_zero_charm_and_the_wall_is_drawn_at_its_own_price():
    """SPY's 2026-10-22 close capture: a strike with open interest 0 everywhere has charm 0.

    A strike whose every contract Schwab sent with open interest 0 is 0 on the charm map (its
    one producer), and its book's charm magnitude is that 0; with no charm entry the magnitude
    is not known. The publication's call wall is a level at its own price, in the options
    lane, its text two decimals.
    """
    zero_oi = sorted(
        k
        for k in {c["strikePrice"] for c in SPY_CLOSE.chain}
        if all(c["openInterest"] == 0 for c in SPY_CLOSE.chain if c["strikePrice"] == k)
    )
    strike = zero_oi[0]
    inside = datetime(2026, 10, 22, 15, 0, tzinfo=ET)  # before the close: charm has time
    legs = read_chain([c for c in SPY_CLOSE.chain if c["strikePrice"] == strike])
    charm = compute_charm_by_strike(legs, SPY_CLOSE.spot, now=inside, sessions=sessions())
    assert charm == {strike: {"call_charm": 0.0, "put_charm": 0.0, "net_charm": 0.0}}
    try:
        live = _publish_close()
        bucket = live.snap.books[("2026-10-22", 0.0)][0][strike]
        body = push_confluence.confluence_payload("SPY", "2026-10-22", SPY_CLOSE.now)
    finally:
        level_store._levels.pop("SPY", None)
    assert magnitudes(bucket, charm[strike], None, SPY_CLOSE.spot)["CHARMM"] == 0.0
    assert magnitudes(bucket, None, None, SPY_CLOSE.spot)["CHARMM"] is None
    walls = [level for level in _rail_levels(body) if level["abbrev"] == "CW"]
    assert [(w["price"], w["price_text"], w["lane"]) for w in walls] == [
        (live.snap.call_wall, price_text(live.snap.call_wall), "options")
    ]


def test_a_served_strike_with_no_open_interest_shows_zero_charm_and_says_why_it_is_unscored():
    """SPY's 2026-10-14 expiry as the console served it 2026-10-01 08:59:47 ET.

    From tests/fixtures/real_spy_2026_10_14_chain_oi_zero.json: strikes 761 to 764, inside the
    window, have open interest 0 on both legs and no volume. Each one's charm on the matrix is
    0.00, not missing; with no open interest and no volume the strike is not scored, and says
    why.
    """
    fx = json.loads(
        (
            Path(__file__).resolve().parent / "fixtures" / "real_spy_2026_10_14_chain_oi_zero.json"
        ).read_text(encoding="utf-8")
    )
    at = datetime.fromtimestamp(fx["chain_as_of_ts_utc"], ET)
    zero = {
        k
        for k in {c["strikePrice"] for c in fx["contracts"]}
        if all(c["openInterest"] == 0 for c in fx["contracts"] if c["strikePrice"] == k)
    }
    try:
        publish_capture(
            "SPY",
            fx["contracts"],
            fx["chain_as_of_ts_utc"],
            fx["priced_at_spot"],
            at.date().isoformat(),
            at,
        )
        body = push_confluence.confluence_payload("SPY", fx["expiry"], at)
    finally:
        level_store._levels.pop("SPY", None)
    shown = [r for r in body["rows"] if r["strike"] in zero]
    assert len(shown) >= 4
    assert all(r["charm_text"] == "0" and r["charm_reason"] is None for r in shown)
    assert all(
        r["score"] is None and r["missing"] == ["no open interest and no volume"] for r in shown
    )


def _around(listed: list[float], price: float) -> list[float]:
    """Return the window as defined for every per-strike panel.

    docs/DATA_FLOW.md "Strike windows", Auto: the eleven listed strikes centred on the one
    nearest the price, held inside the list, lowest first.
    """
    on = min(range(len(listed)), key=lambda i: abs(listed[i] - price))
    first = min(max(0, on - 5), len(listed) - 11)
    return listed[first : first + 11]


def _close_then_print(quote: dict) -> dict:
    """SPY's 2026-10-22 close capture, then `quote`, a print of SPY's after it.

    The print is taken in by the plane and made the price row by the daemon's own function.
    Return the matrix of the capture's same-day expiry as served when the print was received.
    """
    tk, at = "SPY", datetime.fromtimestamp(quote["ts_recv"], ET)
    try:
        _publish_close(tk)
        _chain_spot(tk, quote)
        return push_confluence.confluence_payload(tk, "2026-10-22", at)
    finally:
        _forget(tk)


def _close_strikes() -> list[float]:
    """Return the strikes listed on SPY's 2026-10-22 close capture for that day, lowest first."""
    return sorted(
        {
            float(c["strikePrice"])
            for c in SPY_CLOSE.chain
            if str(c["expirationDate"])[:10] == "2026-10-22"
        }
    )


def test_with_no_live_price_the_window_is_the_chains_middle_and_says_so():
    """IWM's same-day expiry captured 2026-10-23 15:37:16 ET, with no live price held.

    Priced at the underlyingPrice Schwab sent in it, 276.00, with no live price held: the rows
    are the eleven middle strikes of the chain, not those around the chain's price, and the
    notes say why (operator 2026-10-29: one window for every per-strike panel).
    """
    fx = _IWM_ON_A_STRIKE
    tk, at = fx["ticker"], datetime.fromtimestamp(fx["ts_utc"], ET)
    listed = sorted({float(c["strikePrice"]) for c in fx["chain"]})
    try:
        publish_capture(tk, fx["chain"], fx["ts_utc"], fx["spot"], at.date().isoformat(), at)
        body = push_confluence.confluence_payload(tk, "2026-10-23", at)
    finally:
        _forget(tk)
    on, middle = listed.index(fx["spot"]), len(listed) // 2
    assert abs(on - middle) > 10
    assert body["spot"] is None and "priced_at_spot" not in body
    assert sorted(r["strike"] for r in body["rows"]) == listed[middle - 5 : middle + 6]
    assert body["notes"][-1] == strike_rows.WINDOW_NO_PRICE
    assert not any(r["spot_line"] for r in body["rows"])


def test_the_window_follows_the_live_price_off_the_chains_price():
    """SPY's 2026-10-22 close capture and SPY's first print after it a whole strike away.

    The capture is priced at Schwab's price in it; the print (SPY_PRINT_A_STRIKE_AWAY) is taken
    in by the plane and made the price row by the daemon's own function: the window is every
    panel's, centred on the strike nearest that live price, not on the price the chain was
    ranked at (operator 2026-10-29).
    """
    quote = SPY_PRINT_A_STRIKE_AWAY
    live = quote["native"]["LAST_PRICE"]
    body = _close_then_print(quote)
    listed = _close_strikes()
    assert body["spot"] == live and "priced_at_spot" not in body
    assert (
        sorted(r["strike"] for r in body["rows"])
        == _around(listed, live)
        != _around(listed, SPY_CLOSE.spot)
    )


def test_a_price_on_a_listed_strike_puts_the_spot_line_on_that_strike():
    """SPY's 2026-10-22 close capture, and SPY's first print after it on one of its strikes.

    The print (LAST_PRICE 764.00, received 16:33:27 ET) is taken in by the plane and made the
    price row by the daemon's own function: the window is that strike and the five listed
    strikes each side of it, and the spot line is that strike's row, not the one above it.
    """
    quote = _SPY_PRINT_ON_A_STRIKE
    on = quote["native"]["LAST_PRICE"]
    body = _close_then_print(quote)
    listed = _close_strikes()
    k = listed.index(on)
    assert body["spot"] == on and k >= 5
    assert sorted(r["strike"] for r in body["rows"]) == listed[k - 5 : k + 6]
    assert [r["strike"] for r in body["rows"] if r["spot_line"]] == [on]


def test_a_price_above_every_listed_strike_has_no_spot_line():
    """SPY's 2026-10-07 chain as captured here and SPY's first kept print above all its strikes.

    The chain's 20 strikes nearest the price, 767 to 786, and SPY's first kept print above all
    of them (LAST_PRICE 787.5169, received 2026-10-23 17:09:50 ET): no listed strike is at or
    above the price, so no row carries the spot line, and the price is still shown.
    """
    held, price = SPY_0DTE, _SPY_PRINT_ABOVE["native"]["LAST_PRICE"]
    chain = read_chain(held.chain)
    book, _diag = compute_exposures_by_strike(
        chain, spot=held.spot, now=held.now, sessions=sessions(), product=INDEX_OPTIONS
    )
    matrix = build_matrix(book, {}, iv_by_strike(chain), held.spot, 0.0)
    rows = window_rows(matrix, _around(sorted(matrix.ranked), price))
    assert price > max(matrix.strikes)
    assert under_strike(price, matrix.strikes) is None
    shown = at_price(rows, matrix.strikes, price)
    assert (shown["spot"], shown["spot_text"]) == (price, price_text(price))
    assert shown["rows"] and not any(r["spot_line"] for r in shown["rows"])
    assert all("spot_line" not in r for r in rows), "the rows given are not changed"


#: Sunday 2026-10-11, after MRVL's front expiry (2026-10-09) passed
_SUNDAY = datetime(2026, 10, 11, 12, 0, tzinfo=ET)
#: the answers tests/e2e/console-confluence.spec.js draws, kept equal to the route's own
#: (mrvl_answers), never hand written; tests/conftest.py, imported first, sets the tests'
#: environment:
#:   python -c "import tests.conftest, tests.test_data_path_confluence_v1 as t
#:   t.write_mrvl_e2e_fixture()"
_MRVL_ANSWERS = _FX / "real_mrvl_confluence_payloads_2026_10_07.json"


def _publish_mrvl() -> None:
    """MRVL's full chain, published as the stored capture it is, at the price Schwab sent."""
    publish_capture(
        "MRVL", MRVL.chain, MRVL.now.timestamp(), MRVL.spot, MRVL.now.date().isoformat(), MRVL.now
    )


def mrvl_answers() -> dict:
    """Return the confluence panel on MRVL's published chain, no live price row.

    Its first two expiries asked
    at the capture instant, and the front one asked on Sunday, after it passed. The daemon's last
    status stands, its round of the watchlist reported (ROUND_SEC), its feed down: none left by
    another test decides the verdict.
    """
    lmp.record_feed_heartbeat(daemon_status(MRVL.now.timestamp(), chain_round_sec=ROUND_SEC))
    lmp.record_feed_down()
    try:
        _publish_mrvl()
        by_expiry = {
            e: push_confluence.confluence_payload("MRVL", e, MRVL.now)
            for e in ("2026-10-09", "2026-10-16")
        }
        front_passed = push_confluence.confluence_payload("MRVL", "2026-10-09", _SUNDAY)
    finally:
        level_store._levels.pop("MRVL", None)
    return json.loads(
        json.dumps(
            {
                "source": "/api/confluence (push.confluence.confluence_payload) on MRVL's full "
                "chain captured 2026-10-07 10:31:20 ET (tests/fixtures/real_mrvl_full_chain_"
                "2026_10_07.json), published as the stored capture at the price Schwab sent; no "
                "live price row (spot absent). by_expiry: each expiry asked at the capture "
                "instant; front_passed: the front expiry asked on Sunday 2026-10-11, after it "
                "passed. Written by tests/test_data_path_confluence_v1.py write_mrvl_e2e_fixture.",
                "by_expiry": by_expiry,
                "front_passed": front_passed,
            }
        )
    )


def write_mrvl_e2e_fixture() -> None:
    """Regeneration utility (never called by a test).

    Schwab's /markets answers held as the tests
    hold them (tests/conftest.py), then the route's answers written to the browser test's
    fixture.
    """
    for a in json.loads(MARKETS_ANSWERS.read_text(encoding="utf-8"))["answers"].values():
        if a["status"] == 200:
            record_markets(json.loads(a["body"]))
    _MRVL_ANSWERS.write_text(json.dumps(mrvl_answers(), indent=1) + "\n", encoding="utf-8")


def test_the_mrvl_answers_the_browser_draws_are_the_routes_own():
    """The confluence browser test's answers are the route's on MRVL's captured chain.

    Each column's shading number and peak served beside its text. Every key and text equal; a
    number to its last digits (MRVL's GRC, a level of the gamma curve, differs in its 17th
    digit between Windows and Linux).
    """
    served = mrvl_answers()
    assert _same(json.loads(_MRVL_ANSWERS.read_text(encoding="utf-8")), served), (
        "drifted from the route; regenerate with write_mrvl_e2e_fixture()"
    )
    front = served["by_expiry"]["2026-10-09"]
    assert set(front["peaks"]) == {*SHADED, *LEANS}
    assert any(r["net_gex"] is not None and r["net_gex"] < 0 for r in front["rows"])


def test_a_passed_expiry_is_not_the_one_the_matrix_opens_on():
    """MRVL's full chain captured Wednesday 2026-10-07 still holds Friday's 2026-10-09 expiry.

    On Sunday the matrix opens on the next one, and a request for Friday's opens there too.
    """
    tk = "MRVL"
    listed = sorted({str(c["expirationDate"])[:10] for c in MRVL.chain})
    try:
        _publish_mrvl()
        opened = push_confluence.confluence_payload(tk, None, _SUNDAY)
        asked = push_confluence.confluence_payload(tk, listed[0], _SUNDAY)
    finally:
        level_store._levels.pop(tk, None)
    assert listed[:2] == ["2026-10-09", "2026-10-16"]
    assert (opened["available"], opened["expiry"]) == (True, "2026-10-16")
    assert "2026-10-09" not in [e["expiry"] for e in opened["expiries"]]
    assert (asked["available"], asked["expiry"]) == (True, "2026-10-16")


def test_the_matrix_reads_the_expiry_charm_map_and_does_not_rebuild_it():
    """Charm is the map the book stored for this expiry.

    SPY's captured 0DTE chain valued an hour
    before its capture is a different charm map than the chain valued at its capture would build;
    stored with the book, it is the charm on the matrix (thousands, two decimals, signed).
    """
    held = SPY_0DTE
    chain = read_chain(held.chain)
    expiry = str(held.chain[0]["expirationDate"])[:10]
    book, _diag = compute_exposures_by_strike(
        chain, spot=held.spot, now=held.now, sessions=sessions(), product=INDEX_OPTIONS
    )
    earlier = compute_charm_by_strike(
        chain,
        held.spot,
        now=held.now - timedelta(hours=1),
        sessions=sessions(),
        product=INDEX_OPTIONS,
    )
    at_capture = compute_charm_by_strike(
        chain, held.spot, now=held.now, sessions=sessions(), product=INDEX_OPTIONS
    )
    strike = min(book, key=lambda s: abs(s - held.spot))
    try:
        levels = _published_0dte()
        _hold_with(levels, charm_by_expiry=levels.snap.charm_by_expiry | {expiry: earlier})
        body = push_confluence.confluence_payload("SPY", expiry, held.now)
    finally:
        level_store._levels.pop("SPY", None)
    row = next(r for r in body["rows"] if r["strike"] == strike)
    assert earlier[strike]["net_charm"] != at_capture[strike]["net_charm"]
    assert row["charm_text"] == screen_text(earlier[strike]["net_charm"], "compact")


def test_the_matrix_reads_the_expiry_volatility_blend_and_does_not_rebuild_it():
    """The volatility column is the blend the book stored for this expiry.

    The blend of SPY's
    2026-10-22 close chain, stored with SPY's 2026-10-07 0DTE book, is not the blend that chain
    would build; it is the volatility on the matrix (one decimal).
    """
    held = SPY_0DTE
    chain = read_chain(held.chain)
    expiry = str(held.chain[0]["expirationDate"])[:10]
    puts = iv_by_strike(read_chain(SPY_CLOSE.chain))
    whole = iv_by_strike(chain)
    try:
        levels = _published_0dte()
        _hold_with(levels, iv_by_expiry=levels.snap.iv_by_expiry | {expiry: puts})
        body = push_confluence.confluence_payload("SPY", expiry, held.now)
    finally:
        level_store._levels.pop("SPY", None)
    differ = [
        r
        for r in body["rows"]
        if r["strike"] in puts
        and r["strike"] in whole
        and f"{puts[r['strike']]:.2f}" != f"{whole[r['strike']]:.2f}"
    ]
    assert differ and all(r["iv_text"] == f"{puts[r['strike']]:.2f}" for r in differ)


def _window_has(rows: list, key: str) -> bool:
    return any(row.get(key) is not None for row in rows)


def test_the_close_keeps_the_vanna_a_settled_clock_drops():
    """SPY's captured 0DTE chain settles at the index close: no time left, no vanna, charm or score.

    Operator 2026-11-15: no floor of ours on the time left ("yes the formula needs to account for
    time"), and a settled value is "-" like every value not known ("no settled just a dash"). At
    the close and after it alike, those three are missing.
    """
    held = SPY_0DTE
    at = datetime(2026, 10, 7, 18, 0, tzinfo=ET)
    valued = valuation_instant(at, INDEX_OPTIONS)
    chain = read_chain(held.chain)
    on_file = sessions()
    at_close, _diag = compute_exposures_by_strike(
        chain, spot=held.spot, now=valued, sessions=on_file, product=INDEX_OPTIONS
    )
    after, _diag = compute_exposures_by_strike(
        chain, spot=held.spot, now=at, sessions=on_file, product=INDEX_OPTIONS
    )
    strike = min(at_close, key=lambda s: abs(s - held.spot))
    assert bucket_metric(at_close[strike], "net_vanna") is None
    assert bucket_metric(after[strike], "net_vanna") is None
    iv = iv_by_strike(chain)
    charm_close = compute_charm_by_strike(
        chain, held.spot, now=valued, sessions=on_file, product=INDEX_OPTIONS
    )
    charm_late = compute_charm_by_strike(
        chain, held.spot, now=at, sessions=on_file, product=INDEX_OPTIONS
    )
    close = build_matrix(at_close, charm_close, iv, held.spot, 0.0)
    late = build_matrix(after, charm_late, iv, held.spot, 0.0)
    close_rows = window_rows(close, _around(sorted(close.ranked), held.spot))
    late_rows = window_rows(late, _around(sorted(late.ranked), held.spot))
    assert not _window_has(close_rows, "vanna_text")
    assert not _window_has(close_rows, "charm_text")
    assert not _window_has(close_rows, "score")
    assert not _window_has(late_rows, "vanna_text")
    assert not _window_has(late_rows, "charm_text")
    assert not _window_has(late_rows, "score")


def test_spy_keeps_vanna_until_the_index_close():
    """SPY settles at the index close.

    At 4:10 PM ET the equity-option close has passed
    and the index close has not, so this captured chain's vanna still stands.
    """
    held = SPY_0DTE
    at = datetime(2026, 10, 7, 16, 10, tzinfo=ET)
    chain = read_chain(held.chain)
    on_file = sessions()
    book, _diag = compute_exposures_by_strike(
        chain, spot=held.spot, now=at, sessions=on_file, product=INDEX_OPTIONS
    )
    equity, _diag = compute_exposures_by_strike(chain, spot=held.spot, now=at, sessions=on_file)
    strike = min(book, key=lambda s: abs(s - held.spot))
    assert bucket_metric(book[strike], "net_vanna") is not None
    assert bucket_metric(equity[strike], "net_vanna") is None


def test_a_chain_delivered_after_the_close_still_fills_the_matrix():
    """The page reads the publication.

    SPY's captured 0DTE chain, delivered after the index close, is valued at that close: Schwab's
    own fields fill the matrix (its implied volatility below), and the contracts, settled with no
    time left, have no vanna, charm or score: "-" (operator 2026-11-15).
    """
    held = SPY_0DTE
    tk = "SPY"
    at = datetime(2026, 10, 7, 18, 0, tzinfo=ET)
    expiry = str(held.chain[0]["expirationDate"])[:10]
    try:
        spot = _chain_spot(tk, _AT_CAPTURE[held.ticker])
        snap = server._publish_levels(
            tk, read_chain(held.chain), at.timestamp(), chain_spot=spot, now=at
        )
        body = push_confluence.confluence_payload(tk, expiry, at)
    finally:
        _forget(tk)
    assert snap is not None
    assert body["available"] is True
    assert not _window_has(body["rows"], "vanna_text")
    assert not _window_has(body["rows"], "charm_text")
    assert not _window_has(body["rows"], "score")
    blend = iv_by_strike(
        read_chain([ct for ct in held.chain if str(ct.get("expirationDate"))[:10] == expiry])
    )
    shown = next(r for r in body["rows"] if blend.get(r["strike"]) is not None)
    assert shown["iv_text"] == f"{blend[shown['strike']]:.2f}"


def test_an_expiry_settled_at_the_close_keeps_its_last_known_values_with_their_time():
    """Operator 2026-11-15: "yes the last known value. this gives me data to look at and study".

    SPY's captured 0DTE chain published at 16:12 ET, while it had time left, then delivered again
    after the index close: the 15:59 publication stands, the last values computed while the market
    was open (operator 2026-11-15: "we keep the last known data on the screen until we get new
    data"), its vanna, charm and score with them, and the matrix says CLOSE (current at the 16:15
    close, within two of the daemon's rounds) with the chain's time, 16:12, and its age. Nothing is
    priced after the close, so never a value of a made-up time left.
    """
    held = SPY_0DTE
    tk = "SPY"
    before = datetime(2026, 10, 7, 16, 12, tzinfo=ET)
    after = datetime(2026, 10, 7, 18, 0, tzinfo=ET)
    expiry = str(held.chain[0]["expirationDate"])[:10]
    try:
        spot = _chain_spot(tk, _AT_CAPTURE[held.ticker])
        alive = server._publish_levels(
            tk, read_chain(held.chain), before.timestamp(), chain_spot=spot, now=before
        )
        live_rows = push_confluence.confluence_payload(tk, expiry, before)["rows"]
        settled = server._publish_levels(
            tk, read_chain(held.chain), after.timestamp(), chain_spot=spot, now=after
        )
        body = push_confluence.confluence_payload(tk, expiry, after)
    finally:
        _forget(tk)
    assert _window_has(live_rows, "vanna_text") and _window_has(body["rows"], "vanna_text")
    assert settled is alive
    assert settled.same_day == alive.same_day
    by_strike = {r["strike"]: (r["vanna_text"], r["charm_text"], r["score"]) for r in live_rows}
    for row in body["rows"]:
        if row["strike"] in by_strike:
            assert (row["vanna_text"], row["charm_text"], row["score"]) == by_strike[row["strike"]]
    assert body["status_text"] == (
        f"CLOSE · chain as of {ct_label(before.timestamp())}, "
        f"{age_text(after.timestamp() - before.timestamp())} old"
    )


def test_the_matrix_says_the_levels_word_and_the_chains_time_and_age():
    """AGENTS rule 5: every value is shown with its time, and its age once it has stopped.

    SPY's captured chain, delivered after the index close and read an hour later: the matrix's
    line says CLOSE (the levels' one verdict, push.verdict.terrain_staleness), the chain's time and
    its age.
    """
    tk = "SPY"
    at = datetime(2026, 10, 7, 18, 0, tzinfo=ET)
    later = datetime(2026, 10, 7, 19, 0, tzinfo=ET)
    expiry = str(SPY_0DTE.chain[0]["expirationDate"])[:10]
    try:
        spot = _chain_spot(tk, _AT_CAPTURE[SPY_0DTE.ticker])
        server._publish_levels(
            tk, read_chain(SPY_0DTE.chain), at.timestamp(), chain_spot=spot, now=at
        )
        body = push_confluence.confluence_payload(tk, expiry, later)
        verdict = push_verdict.terrain_staleness(at.timestamp(), tk, now=later.timestamp())
    finally:
        _forget(tk)
    assert verdict["levels_state"] == "CLOSE"
    assert body["status_text"] == f"CLOSE · chain as of {ct_label(at.timestamp())}, " + (
        f"{age_text(3600.0)} old"
    )


def test_a_later_expiry_keeps_its_columns_at_that_expirys_close():
    """TSLA's captured Friday chain, delivered after that Friday's equity close, is valued then.

    It is valued at that close, when its contracts (all Friday's) settle: no time is left, so no
    vanna, charm or score, "-" (operator 2026-11-15). Asked again, the request reads the same
    publication.
    """
    held = TSLA
    tk = "TSLA"
    at = datetime(2026, 10, 9, 18, 0, tzinfo=ET)
    expiry = str(held.chain[0]["expirationDate"])[:10]
    try:
        spot = _chain_spot(tk, _AT_CAPTURE[held.ticker])
        snap = server._publish_levels(
            tk, read_chain(held.chain), at.timestamp(), chain_spot=spot, now=at
        )
        body = push_confluence.confluence_payload(tk, expiry, at)
        again = push_confluence.confluence_payload(tk, expiry, at)
    finally:
        _forget(tk)
    assert snap is not None
    assert expiry == "2026-10-09"
    assert body["available"] is True
    assert not _window_has(body["rows"], "vanna_text")
    assert not _window_has(body["rows"], "charm_text")
    assert not _window_has(body["rows"], "score")
    assert again["rows"] == body["rows"]


def _no_value_quote(chain):
    """Schwab's after-the-close quote: gamma 0, delta -1, volatility the no-value code."""
    poisoned = []
    for ct in chain:
        row = dict(ct)
        row["gamma"] = 0.0
        row["delta"] = -1.0
        row["volatility"] = -999.0
        poisoned.append(row)
    return poisoned


def test_a_no_value_quote_after_the_close_keeps_the_last_reported_greek():
    """SPY's captured chain is published after the index close, valued at that close.

    A later quote that sends Schwab's no-value code does not erase that quote's gamma (net GEX,
    Schwab's gamma as sent). Its contracts, settled at that close with no time left, have no
    vanna, charm or score: "-" both times (operator 2026-11-15).
    """
    held = SPY_0DTE
    after = datetime(2026, 10, 7, 18, 0, tzinfo=ET)
    first, second = _spy_0dte_twice(_no_value_quote(held.chain), after, after, after)
    near = min(first["rows"], key=lambda row: abs(row["strike"] - held.spot))
    kept = (near["net_gex_text"], near["vanna_text"], near["charm_text"], near["score_text"])
    assert kept[0] is not None and kept[1:] == (None, None, None)
    again = min(second["rows"], key=lambda row: abs(row["strike"] - held.spot))
    assert (
        again["net_gex_text"],
        again["vanna_text"],
        again["charm_text"],
        again["score_text"],
    ) == kept


def test_during_the_session_a_no_value_quote_does_not_keep_the_old_greek():
    """During the session Schwab's no-value code is not a greek. It does not keep the older one."""
    held = SPY_0DTE
    session = datetime(2026, 10, 7, 12, 32, tzinfo=ET)
    later = datetime(2026, 10, 7, 12, 40, tzinfo=ET)
    _first, body = _spy_0dte_twice(_no_value_quote(held.chain), session, later, later)
    near = min(body["rows"], key=lambda row: abs(row["strike"] - held.spot))
    assert near["vanna_text"] is None and near["charm_text"] is None and near["score"] is None


def _zero_counts(chain):
    """Return the chain Schwab sends after the close: open interest and volume both zero."""
    zeroed = []
    for ct in chain:
        row = dict(ct)
        row["openInterest"] = 0
        row["totalVolume"] = 0
        zeroed.append(row)
    return zeroed


def test_a_zero_count_after_the_close_keeps_the_last_reported_count():
    """SPY's captured chain is published after the index close: the close values.

    They are the balance until the next open: a later chain that reports zero open interest and
    zero volume does not replace those counts. Its contracts, settled at that close with no time
    left, have no score or vanna: "-" both times (operator 2026-11-15).
    """
    held = SPY_0DTE
    after = datetime(2026, 10, 7, 18, 0, tzinfo=ET)
    first, second = _spy_0dte_twice(_zero_counts(held.chain), after, after, after)
    near = min(first["rows"], key=lambda row: abs(row["strike"] - held.spot))
    kept = (near["oi_text"], near["volume_text"], near["score_text"], near["vanna_text"])
    assert None not in kept[:2] and kept[2:] == (None, None)
    again = min(second["rows"], key=lambda row: abs(row["strike"] - held.spot))
    assert (
        again["oi_text"],
        again["volume_text"],
        again["score_text"],
        again["vanna_text"],
    ) == kept


def _first_chain_keeps_the_capture(now, capture_at):
    """No chain is in memory.

    The delivered chain reports zero counts. The stored capture taken after the close is the
    balance, so put/call volume stays.
    """
    held = SPY_0DTE
    tk = "SPYKEEP"
    expiry = str(held.chain[0]["expirationDate"])[:10]
    fresh = [dict(c) for c in held.chain]
    try:
        spot = _chain_spot(tk, _AT_CAPTURE[held.ticker])
        server._publish_levels(tk, read_chain(fresh), now.timestamp(), chain_spot=spot, now=now)
        first = push_confluence.confluence_payload(tk, expiry, now)
        shown = next(row for row in first["rows"] if row["pc_vol_text"] is not None)
        kept = (shown["oi_text"], shown["volume_text"], shown["pc_vol_text"])
        with level_store._lock:  # a restart: no levels and no captures held
            level_store._levels.pop(tk, None)
        capture_store.clear()
        _store_by_expiry(tk, fresh, held.spot, capture_at)
        server._publish_levels(
            tk, read_chain(_zero_counts(fresh)), now.timestamp(), chain_spot=spot, now=now
        )
        second = push_confluence.confluence_payload(tk, expiry, now)
        again = next(row for row in second["rows"] if row["strike"] == shown["strike"])
        assert (again["oi_text"], again["volume_text"], again["pc_vol_text"]) == kept
    finally:
        _forget(tk)


def test_the_first_chain_after_the_close_keeps_the_stored_counts():
    """A restart after the close has no chain in memory.

    The chain the daemon delivers
    reports zero open interest and zero volume. The stored close capture is the balance, so
    put/call volume stays.
    """
    _first_chain_keeps_the_capture(
        datetime(2026, 10, 7, 18, 0, tzinfo=ET), datetime(2026, 10, 7, 16, 15, tzinfo=ET)
    )


def test_a_chain_before_the_next_open_keeps_the_stored_counts():
    """A delivered chain of zeros does not erase the stored close capture's volume.

    Before the next option window opens.
    """
    _first_chain_keeps_the_capture(
        datetime(2026, 10, 7, 8, 0, tzinfo=ET), datetime(2026, 10, 6, 16, 0, tzinfo=ET)
    )


def _no_value_counts(chain):
    """Return the chain with Schwab's no-value code on open interest and volume."""
    coded = []
    for ct in chain:
        row = dict(ct)
        row["openInterest"] = -999
        row["totalVolume"] = -999
        coded.append(row)
    return coded


def test_a_no_value_count_after_the_close_is_not_the_last_count():
    """A chain after the close, here with Schwab's no-value code for its counts, replaces nothing.

    The last values while the market was open stand (operator 2026-11-15): the 16:10 counts.
    """
    inside = datetime(2026, 10, 7, 16, 10, tzinfo=ET)
    after = datetime(2026, 10, 7, 18, 0, tzinfo=ET)
    first, second = _spy_0dte_twice(_no_value_counts(SPY_0DTE.chain), inside, after, after)
    assert any(row["pc_vol_text"] is not None for row in first["rows"])
    assert second["rows"] == first["rows"]


def test_a_chain_begun_inside_the_window_keeps_its_reported_zero():
    """A chain fetched before the close but reaching the pricing after it is priced no more.

    The last values priced while the market was open stand (operator 2026-11-15): nothing is
    priced after the close.
    """
    inside = datetime(2026, 10, 7, 16, 10, tzinfo=ET)
    after = datetime(2026, 10, 7, 16, 20, tzinfo=ET)
    first, second = _spy_0dte_twice(_zero_counts(SPY_0DTE.chain), inside, inside, after)
    assert any(row["pc_vol_text"] is not None for row in first["rows"])
    assert second["rows"] == first["rows"]


def test_a_close_capture_of_zeros_is_the_balance_not_the_capture_before_it():
    """SPY's chain with its counts stored at 16:00, then one begun after the close with zeros.

    A chain begun after the option close with every count zero, stored before the console hears
    of it, on a console holding no earlier chain: the newest capture after the close is the
    balance, and its reported zeros stand; the 16:00 capture's counts are not carried. Induced
    test condition: one chain stored twice, once with its counts set to 0.
    """
    held = SPY_0DTE
    tk = "SPYOWN"
    fresh = [dict(c) for c in held.chain]
    expiry = str(fresh[0]["expirationDate"])[:10]
    at_close = datetime(2026, 10, 7, 16, 0, tzinfo=ET)
    after = datetime(2026, 10, 7, 16, 20, tzinfo=ET)
    try:
        spot = _chain_spot(tk, _AT_CAPTURE[held.ticker])
        for when, contracts in ((at_close, fresh), (after, _zero_counts(fresh))):
            store_capture(
                server.get_db().db_path,
                ticker=tk,
                expiry=expiry,
                contracts=contracts,
                spot=held.spot,
                chain_spot=held.spot,
                completeness_basis=CAPTURE_BASIS,
                ts_utc=when.timestamp(),
            )
        server._publish_levels(
            tk, read_chain(_zero_counts(fresh)), after.timestamp(), chain_spot=spot, now=after
        )
        served = push_confluence.confluence_payload(tk, expiry, after)
        assert served["rows"] and all(row["pc_vol_text"] is None for row in served["rows"])
    finally:
        _forget(tk)


def test_a_closed_day_zero_book_keeps_the_last_count_through_the_next_open():
    """A day Schwab says is closed is outside every option window.

    Sunday's zero book does not
    replace the balance, the stored close capture; and Monday before the open it still stands.
    """
    held = SPY_0DTE
    tk = "SPYMON"
    fresh = [dict(c) for c in held.chain]
    expiry = str(fresh[0]["expirationDate"])[:10]
    before = datetime(2026, 10, 5, 8, 0, tzinfo=ET)
    try:
        spot = _chain_spot(tk, _AT_CAPTURE[held.ticker])
        server._publish_levels(
            tk, read_chain(fresh), before.timestamp(), chain_spot=spot, now=before
        )
        first = push_confluence.confluence_payload(tk, expiry, before)
        shown = next(row for row in first["rows"] if row["pc_vol_text"] is not None)
        kept = shown["pc_vol_text"]
        with level_store._lock:  # a restart: no levels and no captures held
            level_store._levels.pop(tk, None)
        capture_store.clear()
        _store_by_expiry(tk, fresh, held.spot, datetime(2026, 10, 2, 16, 0, tzinfo=ET))
        closed = datetime(2026, 10, 4, 12, 0, tzinfo=ET)
        server._publish_levels(
            tk, read_chain(_zero_counts(fresh)), closed.timestamp(), chain_spot=spot, now=closed
        )
        held_closed = push_confluence.confluence_payload(tk, expiry, closed)
        assert (
            next(row for row in held_closed["rows"] if row["strike"] == shown["strike"])[
                "pc_vol_text"
            ]
            == kept
        )
        server._publish_levels(
            tk, read_chain(_zero_counts(fresh)), before.timestamp(), chain_spot=spot, now=before
        )
        second = push_confluence.confluence_payload(tk, expiry, before)
        again = next(row for row in second["rows"] if row["strike"] == shown["strike"])
        assert again["pc_vol_text"] == kept
    finally:
        _forget(tk)


def test_a_streamed_zero_before_the_next_open_does_not_replace_the_capture():
    """SPY's 2026-10-19 expiry from the 2026-10-16 close capture, published before Monday's open.

    Published Monday 2026-10-19 before the open: the LEVELONE_OPTIONS messages Schwab sent that
    morning with TOTAL_VOLUME 0, taken in as the daemon received them, are values sent after the
    close: none is put over the capture, and each contract keeps the volume it reported.
    """
    held, messages = _SPY_MONDAY["close"], _SPY_MONDAY["zero_volume_messages"]
    tk = "SPY"
    after = datetime.fromtimestamp(max(m["ts_recv"] for m in messages) + 1.0, ET)
    traded = {ct["symbol"]: ct["totalVolume"] for ct in held["chain"]}
    symbols = [m["symbol"] for m in messages]
    ofls.clear_all_live_state()
    try:
        lmp.record_feed_heartbeat(
            daemon_status(
                after.timestamp(),
                schwab_socket_open=True,
                held={"LEVELONE_EQUITIES": [tk], "LEVELONE_OPTIONS": symbols},
            )
        )
        for m in messages:
            ofs._ingest_pushed(
                f"optquote.{m['symbol']}",
                verbatim_msg(
                    symbol=m["symbol"], content=m["native"], src=m["src"], ts_recv=m["ts_recv"]
                ),
            )
        publish_capture(tk, held["chain"], held["ts_utc"], held["spot"], "2026-10-16", after)
        book = level_store.published_levels(tk)
        overlaid = book.gamma_surface["stream_overlay_contracts"]
        kept = {ct.symbol: ct.volume for ct in book.priced_chain if ct.symbol in traded}
        panel = push_chain.chain(
            tk, after.timestamp(), {"expiry": str(held["chain"][0]["expirationDate"])[:10]}
        )
        shown = {row["symbol"]: row.get("totalVolume") for row in panel["contracts"]}
    finally:
        ofls.clear_all_live_state()
        _forget(tk)
    assert overlaid == 0
    assert all(m["native"]["TOTAL_VOLUME"] == 0 for m in messages)
    assert all(traded[s] > 0 and kept[s] == traded[s] for s in symbols)
    # the chain panel shows the contracts as the levels priced them
    assert all(shown[s] == traded[s] for s in symbols)


def _drop_counts(chain):
    """Return the chain with open interest and volume absent."""
    dropped = []
    for ct in chain:
        row = dict(ct)
        row.pop("openInterest", None)
        row.pop("totalVolume", None)
        dropped.append(row)
    return dropped


def test_a_missing_count_after_the_close_is_not_the_last_count():
    """A chain after the close, here with counts Schwab did not send, replaces nothing.

    The last values while the market was open stand (operator 2026-11-15): the 16:10 counts.
    """
    inside = datetime(2026, 10, 7, 16, 10, tzinfo=ET)
    after = datetime(2026, 10, 7, 18, 0, tzinfo=ET)
    first, second = _spy_0dte_twice(_drop_counts(SPY_0DTE.chain), inside, after, after)
    assert any(row["pc_vol_text"] is not None for row in first["rows"])
    assert second["rows"] == first["rows"]


def test_a_date_with_no_session_keeps_a_reported_zero():
    """A date Schwab has not answered is not outside an option window. A reported zero stays."""
    held = SPY_0DTE
    tk = "SPYNOSN"
    fresh = [dict(c) for c in held.chain]
    expiry = str(fresh[0]["expirationDate"])[:10]
    unknown = datetime(2026, 9, 29, 12, 0, tzinfo=ET)
    try:
        spot = _chain_spot(tk, _AT_CAPTURE[held.ticker])
        _store_by_expiry(tk, fresh, held.spot, datetime(2026, 10, 7, 16, 15, tzinfo=ET))
        server._publish_levels(
            tk, read_chain(_zero_counts(fresh)), unknown.timestamp(), chain_spot=spot, now=unknown
        )
        body = push_confluence.confluence_payload(tk, expiry, unknown)
        assert body["rows"]
        assert all(row["pc_vol_text"] is None for row in body["rows"])
    finally:
        _forget(tk)


def test_a_newer_capture_is_the_count_the_next_chain_keeps():
    """SPY's 2026-10-23 expiry: after 2026-10-22's close, that session's values stand.

    Its 2026-10-21 close capture is read before 2026-10-22's open; the chain priced at 12:32 in
    that session reports zero volume, a reported 0; after the close neither the newer close
    capture nor the chain delivered then replaces it (operator 2026-11-15: the last values while
    the market was open stand). Priced at SPY's quote at the first capture (LAST_PRICE 773.50).
    """
    older, newer = _SPY_TWO_CLOSES["older"], _SPY_TWO_CLOSES["newer"]
    tk = "SPYNEW"
    fresh = [dict(c) for c in older["chain"]]
    later = {ct["symbol"]: ct["totalVolume"] for ct in newer["chain"]}
    target = next(
        ct
        for ct in fresh
        if ct["totalVolume"] > 0 and later.get(ct["symbol"], ct["totalVolume"]) != ct["totalVolume"]
    )
    before = datetime(2026, 10, 22, 8, 0, tzinfo=ET)
    session = datetime(2026, 10, 22, 12, 32, tzinfo=ET)
    after = datetime(2026, 10, 22, 18, 0, tzinfo=ET)

    def store(capture):
        store_capture(
            server.get_db().db_path,
            ticker=tk,
            expiry=_SPY_TWO_CLOSES["expiry"],
            contracts=[dict(c) for c in capture["chain"]],
            spot=capture["spot"],
            chain_spot=capture["spot"],
            completeness_basis=CAPTURE_BASIS,
            ts_utc=capture["ts_utc"],
        )

    try:
        spot = _chain_spot(tk, _SPY_TWO_CLOSES["quote_at_older"])
        store(older)
        server._publish_levels(
            tk, read_chain(_zero_counts(fresh)), before.timestamp(), chain_spot=spot, now=before
        )
        store(newer)
        server._publish_levels(
            tk, read_chain(_zero_counts(fresh)), session.timestamp(), chain_spot=spot, now=session
        )
        server._publish_levels(
            tk, read_chain(_zero_counts(fresh)), after.timestamp(), chain_spot=spot, now=after
        )
        kept = next(
            ct
            for ct in level_store.published_levels(tk).priced_chain
            if ct.symbol == target["symbol"]
        )
    finally:
        _forget(tk)
    assert kept.volume == 0.0 != later[target["symbol"]]


def test_the_close_values_stand_until_the_next_open():
    """SPY's 2026-10-21 close capture, delivered after that close, is the balance.

    Until 2026-10-22's open neither a reprice on a value pushed after the close nor a later
    chain replaces it. Induced test condition: the chain delivered before the open is SPY's
    2026-10-22 close capture, a real chain with other counts.
    """
    older, newer = _SPY_TWO_CLOSES["older"], _SPY_TWO_CLOSES["newer"]
    tk = "SPYBAL"
    after = datetime(2026, 10, 21, 18, 0, tzinfo=ET)
    before = datetime(2026, 10, 22, 8, 0, tzinfo=ET)
    later = {ct["symbol"]: ct["totalVolume"] for ct in newer["chain"]}
    try:
        spot = _chain_spot(tk, _SPY_TWO_CLOSES["quote_at_older"])
        server._publish_levels(
            tk, read_chain(older["chain"]), after.timestamp(), chain_spot=spot, now=after
        )
        balance = level_store.published_levels(tk)
        server._publish_levels(tk, now=before)
        server._publish_levels(
            tk, read_chain(newer["chain"]), before.timestamp(), chain_spot=spot, now=before
        )
        held = level_store.published_levels(tk)
    finally:
        _forget(tk)
    other = [
        ct.symbol
        for ct in balance.priced_chain
        if ct.volume is not None and later.get(ct.symbol, ct.volume) != ct.volume
    ]
    assert other
    assert held is balance


def test_during_the_session_a_zero_count_replaces_the_old_count():
    """During the session a count of zero is the count. It does not keep the older one."""
    held = SPY_0DTE
    session = datetime(2026, 10, 7, 12, 32, tzinfo=ET)
    later = datetime(2026, 10, 7, 12, 40, tzinfo=ET)
    _first, body = _spy_0dte_twice(_zero_counts(held.chain), session, later, later)
    near = min(body["rows"], key=lambda row: abs(row["strike"] - held.spot))
    assert near["score"] is None
    assert "no open interest and no volume" in near["missing"]


def test_an_after_hours_print_keeps_the_close_book():
    """SPY's 2026-10-22 close capture is published at the price Schwab sent in it.

    The capture was begun 16:17:04 ET, after the index close. SPY's after-hours print at 18:00
    ET (LAST_PRICE as the daemon received it), with no new chain, reprices nothing: the strike's
    gamma (Schwab's, as sent), vanna and charm and the publication's price stay the close's. Its
    contracts settled at that close, so vanna and charm are "-" both times (operator 2026-11-15).
    """
    held, print_ = SPY_CLOSE, SPY_AFTER_HOURS_PRINT
    tk = "SPY"
    at = datetime.fromtimestamp(print_["ts_recv"], ET)
    expiry = str(held.chain[0]["expirationDate"])[:10]
    try:
        _publish_close(tk)
        first = push_confluence.confluence_payload(tk, expiry, held.now)
        near = min(first["rows"], key=lambda row: abs(row["strike"] - held.spot))
        close_texts = (near["net_gex_text"], near["vanna_text"], near["charm_text"])
        assert close_texts[0] is not None and close_texts[1:] == (None, None)
        lmp.record_from_level_one_equity(tk, print_["native"], received_ts=print_["ts_recv"])
        lmp.record_feed_heartbeat(
            daemon_status(at.timestamp(), schwab_socket_open=True, held={"LEVELONE_EQUITIES": [tk]})
        )
        second_snap = server._publish_levels(tk, now=at)
        second = push_confluence.confluence_payload(tk, expiry, at)
        again = min(second["rows"], key=lambda row: abs(row["strike"] - held.spot))
    finally:
        _forget(tk)
    assert print_["native"]["LAST_PRICE"] != held.spot
    assert (again["net_gex_text"], again["vanna_text"], again["charm_text"]) == close_texts
    assert second_snap.spot == held.spot and "priced_at_spot" not in second
    assert second["spot"] == print_["native"]["LAST_PRICE"]


#: SPY_0DTE banked after the 2026-10-07 index close
_BANKED_AFTER_CLOSE = datetime(2026, 10, 7, 18, 0, tzinfo=ET)


def _two_day_captures(chain: list) -> list[StoredCapture]:
    """SPY's captured 0DTE `chain`, as the forces read it, banked on two days at its price.

    Once after the 2026-10-07 index close, and once on 2026-10-06 at noon.
    """
    prior = datetime(2026, 10, 6, 12, 0, tzinfo=ET)
    return [
        StoredCapture(
            et_date=day,
            spot=SPY_0DTE.spot,
            spot_ts=at.timestamp(),
            basis=CAPTURE_BASIS,
            contracts=chain,
            ts_utc=at.timestamp(),
        )
        for day, at in (("2026-10-07", _BANKED_AFTER_CLOSE), ("2026-10-06", prior))
    ]


def _published(caps: list[StoredCapture], now: datetime) -> level_store.PublishedLevels:
    """Return the levels published from stored captures `caps` (newest first) at `now`."""
    tk = "SPYFORCES"
    try:
        server._publish_levels(tk, captures=caps, now=now)
        levels = level_store.published_levels(tk)
        assert levels is not None
        return levels
    finally:
        _forget(tk)


def test_a_close_capture_keeps_its_charm_in_the_forces():
    """SPY's captured 0DTE chain, banked after the index close, is valued at that close.

    Its contracts settled at that close with no time left, so they carry no charm: the forces'
    charm sums are "-", never a charm of a made-up time left (operator 2026-11-15).
    """
    caps = _two_day_captures(read_chain(SPY_0DTE.chain))
    forces = _published(caps, _BANKED_AFTER_CLOSE).forces
    assert forces["available"] is True
    assert forces["charm_below"] is None
    assert forces["charm_above"] is None


def test_the_forces_read_the_charm_map_of_the_chain_just_priced():
    """The forces' charm side sums are the charm map of the chain the levels priced now.

    SPY's captured chain valued at its own capture instant, 12:32 ET, has a charm map; the
    forces' sums are the published chain's map, each side of its own price.
    """
    held = SPY_0DTE
    caps = _two_day_captures(read_chain(held.chain))
    caps[0] = replace(  # the newer capture taken at 12:32, in the session
        caps[0], ts_utc=held.now.timestamp(), spot_ts=held.now.timestamp()
    )
    levels = _published(caps, held.now)
    snap, forces = levels.snap, levels.forces
    assert snap.spot is not None and snap.charm_by_strike
    below = sum(v["net_charm"] for k, v in snap.charm_by_strike.items() if k < snap.spot)
    above = sum(v["net_charm"] for k, v in snap.charm_by_strike.items() if k > snap.spot)
    assert (forces["charm_below"], forces["charm_above"]) == (below, above)


def test_a_chain_whose_every_expiry_has_passed_says_so():
    """SPY's 2026-10-22 close capture holds only that day's expiry.

    On Sunday 2026-10-25 the
    matrix says no expiry on the chain is still open.
    """
    sunday = datetime(2026, 10, 25, 12, 0, tzinfo=ET)
    try:
        _publish_close()
        body = push_confluence.confluence_payload("SPY", None, sunday)
    finally:
        level_store._levels.pop("SPY", None)
    assert body["available"] is False
    assert body["reason"] == "no expiry on this chain is still open"


def test_the_matrix_shows_the_live_price_and_the_one_day_move_levels_serves():
    """CRWD's captured chain (2026-10-16 expiry, captured 2026-10-07 10:38:40 ET) and a print.

    The chain is published at the price Schwab sent in that chain answer (its stored capture's
    spot, 269.04), and CRWD's LEVELONE_EQUITIES message the daemon received at 10:38:00 ET
    (LAST_PRICE 269.395), taken in by the plane and made the price row by the daemon's own
    function. The matrix stays ranked at the chain's price; its window, its
    spot, its one-day move and each row's distance are the live price's, the move the same two
    prices the levels panel serves (push.levels.expected_move).
    """
    tk, at = server.ticker_storage_key(CRWD.ticker), CRWD.now
    live = _QUOTE["native"]["LAST_PRICE"]
    lmp.record_from_level_one_equity(tk, _QUOTE["native"], received_ts=_QUOTE["ts_recv"])
    lmp.record_feed_heartbeat(
        daemon_status(at.timestamp(), schwab_socket_open=True, held={"LEVELONE_EQUITIES": [tk]})
    )
    try:
        publish_capture(tk, CRWD.chain, at.timestamp(), CRWD.spot, at.date().isoformat(), at)
        body = push_confluence.confluence_payload(tk, str(CRWD.chain[0]["expirationDate"])[:10], at)
        levels = {r["id"]: r["price"] for r in push_levels.levels_payload(tk, "1", at)["levels"]}
    finally:
        _forget(tk)
    moves = {
        lv["abbrev"]: lv["price"] for lv in _rail_levels(body) if lv["abbrev"] in ("EM+", "EM−")
    }
    listed = sorted({float(c["strikePrice"]) for c in CRWD.chain})
    assert live not in listed
    assert sorted(r["strike"] for r in body["rows"]) == _around(listed, live)
    assert (body["spot"], body["spot_text"]) == (live, f"{live:.2f}")
    assert "priced_at_spot" not in body
    assert body["spot_time_ct"] == ct_label(_QUOTE["native"]["TRADE_TIME_MILLIS"] / 1000.0)
    assert moves == {"EM+": levels["em_up"], "EM−": levels["em_dn"]}
    assert all(abs(float(r["distance_text"]) - (r["strike"] - live)) <= 0.005 for r in body["rows"])
    assert [r["strike"] for r in body["rows"] if r["spot_line"]] == [
        min(r["strike"] for r in body["rows"] if r["strike"] >= live)
    ]
    assert levels["em_up"] - live == live - levels["em_dn"] > 0
