"""Schwab -> the confluence matrix: the chain already priced, read per strike once."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import app.options.order_flow.state as ofls
import live_market_plane as lmp
import live_price_rows
import server
from calc.confluence_composite import (
    NOT_HELD,
    Shades,
    at_price,
    build_matrix,
    iv_by_strike,
    readings,
    under_strike,
    window_rows,
)
from calc.math_exposure_core import bucket_metric, compute_exposures_by_strike
from calc.math_levels import (
    compute_charm_by_strike,
    contract_inputs,
    expiry_gamma,
    gamma_at_strikes,
)
from calibration.complete_chain_capture import CAPTURE_BASIS
from numeric_contract import price_text
from option_contract import read_chain
from push import chain as push_chain
from push import confluence as push_confluence
from push import strike_rows
from push import verdict as push_verdict
from state import capture_store, level_store
from stream_spine import verbatim_msg
from tests.capture_store import store_capture
from tests.conftest import MARKETS_ANSWERS
from tests.feed_live_helper import (
    ROUND_SEC,
    daemon_status,
    mark_feed_down,
    publish_capture,
    pushed,
    repriced,
)
from tests.real_chains import (
    CRWD,
    MRVL,
    NFLX,
    SPY_0DTE,
    SPY_AFTER_HOURS_PRINT,
    SPY_CLOSE,
    SPY_PRINT_A_STRIKE_AWAY,
    TSLA,
    gamma_here_worked_out,
)
from tests.shared_helpers import fixture_json, rail_levels
from tests.test_order_flow_book_payload_v1 import _same
from tests.test_served_numbers_v1 import screen_text
from time_et import (
    ET,
    INDEX_OPTIONS,
    age_text,
    ct_label,
    option_close_product,
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
    mark_feed_down()


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

    The request reads the expiry it shows on them (push.confluence._matrix).
    """
    level_store.publish("SPY", replace(levels, snap=replace(levels.snap, **snap_fields)))


def _published_matrix(tk: str, fx_chain: list, ts_utc: float, spot: float, expiry: str):
    """One expiry of `tk`'s captured chain, published by the levels producer, as its matrix.

    Every strike's readings and Composite, read on the published snapshot (no prior day, no
    session's visits held).
    """
    at = datetime.fromtimestamp(ts_utc, ET)
    try:
        publish_capture(tk, fx_chain, ts_utc, spot, at.date().isoformat(), at)
        published = level_store.published_levels(tk)
    finally:
        _forget(tk)
    live = published.snap
    book = next(b for (e, _d), (b, _x) in live.books.items() if e == expiry)
    gamma, _unpriced = expiry_gamma(
        [c for c in published.priced_chain if c.expiry == expiry],
        live.valued_at,
        sessions=sessions(),
        product=option_close_product(tk),
    )
    return build_matrix(
        book,
        live.charm_by_expiry[expiry],
        live.iv_by_expiry[expiry],
        spot,
        gamma,
        None,
        {},
        {},
    )


def test_a_gamma_schwab_did_not_send_leaves_the_strike_with_no_composite():
    """NFLX's 2027-12-17 expiry (tests/real_chains.py NFLX, captured 2026-10-07).

    Strikes where Schwab sent no gamma (-999) on a contract with open interest have no net gamma,
    so no family is measured there and the strike has no Composite, with why; every strike with
    a net gamma and a gamma there has one, its strength the definition's.
    """
    m = _published_matrix("NFLX", NFLX.chain, NFLX.now.timestamp(), NFLX.spot, "2027-12-17")
    blank = [s for s, r in m.readings.items() if r.net_gex is None]
    known = [s for s, r in m.readings.items() if r.net_gex is not None and r.gamma_here is not None]
    assert blank and len(known) > 10
    assert all(m.composites[s] is None for s in blank)
    rows = {r["strike"]: r for r in window_rows(m, blank)}
    assert all(r["composite_text"] is None and r["composite_reason"] for r in rows.values())
    peak = max(abs(m.readings[s].net_gex) for s in known)
    for s in known:
        c = m.composites[s]
        assert c is not None and c.measured == ("positioning",)
        assert c.strength == pytest.approx(100.0 * abs(m.readings[s].net_gex) / peak, rel=1e-12)


def test_the_matrix_says_which_contracts_its_gamma_could_not_price():
    """NFLX's 2027-12-17 expiry (tests/real_chains.py NFLX, captured 2026-10-07).

    Schwab sent -999 for the volatility of some of its contracts with open interest: the gamma
    if the price were at each strike cannot price them, and the matrix's notes say how many it
    left out and why (AGENTS.md rule 7), counted on the raw chain.
    """
    expiry = "2027-12-17"
    sent_none = [
        ct
        for ct in NFLX.chain
        if str(ct["expirationDate"])[:10] == expiry
        and ct["volatility"] == -999
        and ct["openInterest"] > 0
    ]
    at = NFLX.now
    try:
        publish_capture("NFLX", NFLX.chain, at.timestamp(), NFLX.spot, at.date().isoformat(), at)
        body = push_confluence.confluence_payload("NFLX", expiry, at)
    finally:
        _forget("NFLX")
    assert sent_none
    assert (
        f"The gamma curve leaves out {len(sent_none)} contracts it cannot price: "
        f"{len(sent_none)} with no volatility."
    ) in body["notes"], body["notes"]


def test_an_am_settled_expiry_past_the_year_has_its_readings():
    """$SPX's AM-settled 2027-12-17 expiry, captured 2026-10-07.

    The expiry is past the year Schwab's /markets answers: each strike with open interest has
    its charm, its vanna, its gamma if the price were there, and so its Composite.
    """
    fx = fixture_json("real_spx_chain_2026_10_07_2027_12_17.json")
    tk = server.ticker_storage_key(fx["ticker"])
    m = _published_matrix(tk, fx["chain"], fx["ts_utc"], fx["spot"], "2027-12-17")
    held = [s for s, r in m.readings.items() if r.oi]
    assert len(held) > 10
    for s in held:
        r = m.readings[s]
        assert r.charm is not None and r.vanna is not None and r.gamma_here is not None
        assert m.composites[s] is not None


#: the sign of a gamma in the industry's words, and short in the Composite cell
_GAMMA_WORDS = {-1: "Negative gamma", 1: "Positive gamma"}
_GAMMA_SHORT = {-1: "Neg. gamma", 1: "Pos. gamma"}


def _sign(x: float) -> int:
    return (x > 0) - (x < 0)


def test_each_strike_is_the_expirys_gamma_if_the_price_were_there():
    """SPY's captured 0DTE chain (SPY_0DTE), one expiry, published by the levels producer.

    Each strike's gamma reading is the expiry's net GEX if the price were at that strike, worked
    out from the raw chain outside the program (tests/real_chains.gamma_here_worked_out): the
    producer's map at the snapshot's valuation instant and every shown row, its words the sign's,
    a model with the convention said on hover.
    """
    held = SPY_0DTE
    expiry = str(held.chain[0]["expirationDate"])[:10]
    assert {str(c["expirationDate"])[:10] for c in held.chain} == {expiry}
    try:
        live = _published_0dte()
        body = push_confluence.confluence_payload("SPY", expiry, held.now)
    finally:
        _forget("SPY")
    expected = gamma_here_worked_out(held)
    assert live.snap.valued_at == held.now
    produced, unpriced = expiry_gamma(
        live.priced_chain, held.now, sessions=sessions(), product=option_close_product("SPY")
    )
    assert produced == pytest.approx(expected, rel=1e-9)
    assert unpriced == {} and body["notes"] == [strike_rows.WINDOW_NO_PRICE]
    assert len(body["rows"]) == 11
    for row in body["rows"]:
        g = expected[row["strike"]]
        assert row["gamma_here"] == pytest.approx(g, rel=1e-9)
        assert row["gamma_here_text"] == _GAMMA_WORDS[_sign(g)]
        assert "dealers long calls, short puts" in row["gamma_here_hover"]
        assert row["gamma_here_reason"] is None


def test_the_composite_is_the_sign_there_and_the_families_equal_vote():
    """SPY's captured 0DTE chain: each strike's Composite, worked out from the definition.

    Its condition is the sign of the expiry's gamma if the price were at the strike (worked out
    from the raw chain); its strength 100 times the mean of the families measured there, each its
    size against the expiry's largest: positioning, |net GEX| over the largest |net GEX| of the
    expiry's book (decision 56: one equal vote a family). With no look-back held, positioning is
    the one family measured, which the hover says.
    """
    held = SPY_0DTE
    expiry = str(held.chain[0]["expirationDate"])[:10]
    try:
        live = _published_0dte()
        body = push_confluence.confluence_payload("SPY", expiry, held.now)
    finally:
        _forget("SPY")
    book = next(b for (e, _d), (b, _x) in live.snap.books.items() if e == expiry)
    nets = {s: bucket_metric(b, "net_gex_1pct") for s, b in book.items()}
    peak = max(abs(v) for v in nets.values() if v is not None)
    gamma = gamma_here_worked_out(held)
    for row in body["rows"]:
        strength = 100.0 * abs(nets[row["strike"]]) / peak
        sign = _sign(gamma[row["strike"]])
        assert row["composite"] == pytest.approx(sign * strength / 100.0, rel=1e-9)
        assert row["composite_text"] == f"{_GAMMA_SHORT[sign]} {strength:.0f}"
        assert "1 of 4 families measured here (positioning)" in row["composite_hover"]
        assert row["composite_reason"] is None


def _matrix_of(tk: str, contracts: list, spot: float, at: datetime):
    """Return the matrix of one expiry's contracts as the levels producer prices them.

    Its book, charm map, volatility blend and gamma profile at Schwab's `spot`, valued at `at`
    for `tk`'s option close; no prior day and no session's visits held.
    """
    chain, product = read_chain(contracts), option_close_product(tk)
    book, _diag = compute_exposures_by_strike(
        chain, spot=spot, now=at, sessions=sessions(), product=product
    )
    charm = compute_charm_by_strike(chain, spot, now=at, sessions=sessions(), product=product)
    priced, _unpriced = contract_inputs(chain, at, sessions=sessions(), product=product)
    gamma = gamma_at_strikes(priced, book)
    return build_matrix(book, charm, iv_by_strike(chain), spot, gamma, None, {}, {})


def _expiry(held, expiry: str) -> list:
    return [c for c in held.chain if str(c["expirationDate"])[:10] == expiry]


#: each column the matrix shows: its text, and the reason served beside it when it is missing
_REASONS = {
    "net_gex_text": ("net_reason", "net gamma is missing"),
    "oi_text": ("oi_reason", "open interest is missing"),
    "pc_vol_text": ("pc_vol_reason", "put/call volume is missing"),
    "vol_oi_text": ("vol_oi_reason", "volume/open interest is missing"),
    "dex_text": ("dex_reason", "delta exposure is missing"),
    "vanna_text": ("vanna_reason", "vanna is missing"),
    "iv_text": ("iv_reason", "implied volatility is missing"),
    "charm_text": ("charm_reason", "charm is missing"),
}


def test_each_missing_column_says_why_and_an_unreported_count_is_not_called_zero():
    """Every row of two books: a column with no value serves its reason, one with a value none.

    NFLX's 2027-12-17 expiry (tests/real_chains.py NFLX), where Schwab sent -999 for some
    contracts' Greeks; and SPY's 2026-10-22 close capture (SPY_CLOSE) with, INDUCED until a
    capture holds it, the totalVolume of the call at the lowest strike with no open interest and
    no volume left out, and the openInterest of the call at the next such strike. Those two show
    "-" for the count not reported, never 0; the other untraded strikes show the 0 Schwab sent.
    """
    untraded = sorted(
        {
            c["strikePrice"]
            for c in SPY_CLOSE.chain
            if all(
                d["openInterest"] == 0 and d["totalVolume"] == 0
                for d in SPY_CLOSE.chain
                if d["strikePrice"] == c["strikePrice"]
            )
        }
    )
    no_volume, no_oi = untraded[0], untraded[1]
    spy = []
    for c in _expiry(SPY_CLOSE, "2026-10-22"):
        row = dict(c)
        if row["putCall"] == "CALL" and row["strikePrice"] == no_volume:
            row.pop("totalVolume")
        if row["putCall"] == "CALL" and row["strikePrice"] == no_oi:
            row.pop("openInterest")
        spy.append(row)
    nflx = _matrix_of("NFLX", _expiry(NFLX, "2027-12-17"), NFLX.spot, NFLX.now)
    close = _matrix_of("SPY", spy, SPY_CLOSE.spot, SPY_CLOSE.now)
    rows = [*window_rows(nflx, nflx.strikes), *window_rows(close, close.strikes)]
    for row in rows:
        for text, (reason, words) in _REASONS.items():
            assert row[reason] == (words if row[text] is None else None), (row["strike"], text)
    for text in _REASONS:
        assert any(r[text] is None for r in rows) and any(r[text] is not None for r in rows), text
    counts = {
        r["strike"]: (r["oi_text"], r["volume_hover"])
        for r in window_rows(close, close.strikes)
        if r["strike"] in untraded
    }
    zero = "Today: calls 0 · puts 0"
    assert counts == {
        s: (None, zero) if s == no_oi else ("0", None) if s == no_volume else ("0", zero)
        for s in untraded
    }


def test_a_negative_gamma_is_taken_as_sent_in_both_legs():
    """SPY's captured 0DTE chain (SPY_0DTE), the call at the strike nearest the price INDUCED.

    Its gamma made negative (no capture holds a negative gamma; Schwab's -999 stays not sent
    in the reader). AGENTS rule 2: a gamma is taken as sent whatever its size, so that strike's
    net gamma, and its size in the Composite, come from both legs as sent: each leg gamma x open
    interest x multiplier x price^2 x 1%, worked out here from the raw chain.
    """
    held = SPY_0DTE
    strike = min({c["strikePrice"] for c in held.chain}, key=lambda k: abs(k - held.spot))
    chain = []
    for c in held.chain:
        row = dict(c)
        if row["strikePrice"] == strike and row["putCall"] == "CALL":
            row["gamma"] = -abs(row["gamma"])
        chain.append(row)
    legs = {
        side: sum(
            c["gamma"] * c["openInterest"] * c["multiplier"] * held.spot * held.spot * 0.01
            for c in chain
            if c["strikePrice"] == strike and c["putCall"] == side
        )
        for side in ("CALL", "PUT")
    }
    call, put = legs["CALL"], legs["PUT"]
    assert call < 0 < put
    matrix = _matrix_of("SPY", chain, held.spot, held.now)
    readings = matrix.readings[strike]
    assert readings.net_gex == pytest.approx(call - put, rel=1e-12)
    peak = max(abs(r.net_gex) for r in matrix.readings.values() if r.net_gex is not None)
    composite = matrix.composites[strike]
    assert composite is not None
    assert composite.strength == pytest.approx(100.0 * abs(call - put) / peak, rel=1e-12)
    row = window_rows(matrix, [strike])[0]
    assert row["net_gex"] == pytest.approx(call - put, rel=1e-12)
    assert row["net_gex_text"] == screen_text(call - put, "dollars")
    assert row["net_reason"] is None and row["composite_reason"] is None


def _publish_close(tk: str = "SPY") -> level_store.PublishedLevels:
    """SPY's 2026-10-22 close capture, published as the stored capture it is, at Schwab's price."""
    held = SPY_CLOSE
    publish_capture(
        tk, held.chain, held.now.timestamp(), held.spot, held.now.date().isoformat(), held.now
    )
    return level_store.published_levels(tk)


def test_the_matrix_reads_the_priced_book_and_the_open_interest_as_sent():
    """SPY's 2026-10-22 close capture, its same-day expiry.

    The matrix reads the book the publication priced, each row's net gamma that book's own
    number (millions, two decimals, signed), and its open interest the calls' and the puts'
    as Schwab sent them, the two on hover.
    """
    try:
        live = _publish_close()
        book = live.snap.books[("2026-10-22", 0.0)][0]
        body = push_confluence.confluence_payload("SPY", "2026-10-22", SPY_CLOSE.now)
    finally:
        level_store._levels.pop("SPY", None)
    assert body["available"] is True
    assert body["expiry"] == "2026-10-22"
    sent = {
        (c["strikePrice"], c["putCall"]): c["openInterest"]
        for c in SPY_CLOSE.chain
        if str(c["expirationDate"])[:10] == "2026-10-22"
    }
    checked = held = 0
    for row in body["rows"]:
        bucket = book[row["strike"]]
        assert row["strike_text"] == price_text(row["strike"])
        net = bucket_metric(bucket, "net_gex_1pct")
        if net is not None and abs(net) >= 5_000:
            assert row["net_gex_text"] == screen_text(net, "dollars")
            assert row["net_gex"] == net and abs(net) <= body["peaks"]["net_gex"]
            checked += 1
        calls, puts = sent[(row["strike"], "CALL")], sent[(row["strike"], "PUT")]
        assert row["oi"] == calls + puts
        assert row["oi_hover"] == f"Open interest: calls {calls:,} · puts {puts:,}"
        held += calls + puts > 0
    assert checked > 5 and held > 5


def test_each_key_level_is_a_tag_on_the_row_of_its_nearest_strike():
    """SPY's 2026-10-22 close capture: the server, not the page, places each level.

    Each key level inside the shown strikes is a tag on the row of the strike nearest its price
    (the lower on a tie, decision 64 O-5), saying its own price, the option levels with "no record
    yet" for a hold rate; a level above the highest strike or below the lowest is listed past
    them. An answer with no chain has no rows and no levels.
    """
    try:
        live = _publish_close()
        body = push_confluence.confluence_payload("SPY", "2026-10-22", SPY_CLOSE.now)
    finally:
        level_store._levels.pop("SPY", None)
    top, bottom = body["rows"][0]["strike"], body["rows"][-1]["strike"]
    assert top > bottom, "the rows run highest strike first"
    assert all(lv["price"] > top for lv in body["levels_above"])
    assert all(lv["price"] < bottom for lv in body["levels_below"])
    strikes = [r["strike"] for r in body["rows"]]
    tagged = {r["strike"]: [t["text"] for t in r["tags"]] for r in body["rows"]}
    # this close's key levels all sit inside its strikes; one past them is
    # tests/test_matrix_key_levels_v1.py's (SPY's and AMZN's 2026-11-12)
    call = live.snap.call_wall
    assert bottom <= call <= top
    nearest = min(strikes, key=lambda s: (abs(s - call), s))
    assert f"Gamma Call {price_text(call)}" in tagged[nearest]
    for row in body["rows"]:
        for tag in row["tags"]:
            price = float(tag["text"].rsplit(" ", 1)[1])
            assert row["strike"] == min(strikes, key=lambda s: (abs(s - price), s))
            if tag["lane"] == "options":
                assert tag["hover"].endswith("hold rate: no record yet")
    _forget("ZZNOCHAIN")
    none = push_confluence.confluence_payload("ZZNOCHAIN", None, SPY_CLOSE.now)
    assert none["available"] is False and "rows" not in none
    assert none["levels_above"] == none["levels_below"] == []


def test_a_zero_book_is_zero_charm_and_the_wall_is_drawn_at_its_own_price():
    """SPY's 2026-10-22 close capture: a strike with open interest 0 everywhere has charm 0.

    A strike whose every contract Schwab sent with open interest 0 is 0 on the charm map (its
    one producer), and its charm reading is that 0; with no charm entry it is not known. The
    publication's largest call gamma strike is a level at its own price, in the options lane,
    its text two decimals.
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

    def charm_of(c):
        return readings(bucket, c, None, SPY_CLOSE.spot, None, None, False, None, NOT_HELD).charm

    assert charm_of(charm[strike]) == 0.0
    assert charm_of(None) is None
    walls = [tag for tag in rail_levels(body) if tag["text"].startswith("Gamma Call ")]
    assert [(w["text"], w["lane"]) for w in walls] == [
        (f"Gamma Call {price_text(live.snap.call_wall)}", "options")
    ]


def test_a_served_strike_with_no_open_interest_shows_zero_charm_and_zero_counts():
    """SPY's 2026-10-14 expiry as the console served it 2026-10-01 08:59:47 ET.

    From tests/fixtures/real_spy_2026_10_14_chain_oi_zero.json: strikes 761 to 764, inside the
    window, have open interest 0 on both legs and no volume. Each one's charm on the matrix is
    0.00, not missing, and its open interest, volume and net gamma the 0 Schwab sent, values,
    never "-". The served chain carries no interest rate or dividend yield, so the gamma if the
    price were there is not known, and no strike has a Composite: "-" with why.
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
        r["oi_text"] == "0" and r["volume_hover"] == "Today: calls 0 · puts 0" for r in shown
    )
    assert all(r["net_gex"] == 0 and r["net_gex_text"] is not None for r in shown)
    assert all(c.get("interestRate") is None for c in fx["contracts"])
    assert all(r["gamma_here"] is None and r["gamma_here_reason"] for r in body["rows"])
    assert all(r["composite_text"] is None and r["composite_reason"] for r in body["rows"])


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
    assert "priced_at_spot" not in body and "spot" not in body  # the price is the price row's
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
    assert "priced_at_spot" not in body and "spot" not in body  # the price is the price row's
    assert (
        sorted(r["strike"] for r in body["rows"])
        == _around(listed, live)
        != _around(listed, SPY_CLOSE.spot)
    )


def test_a_price_on_a_listed_strike_puts_the_spot_line_on_that_strike():
    """SPY's 2026-10-22 close capture, and SPY's first print after it on one of its strikes.

    The print (LAST_PRICE 764.00, received 16:33:27 ET) is taken in by the plane and made the
    price row by the daemon's own function: the window is that strike and the five listed
    strikes each side of it, and the spot line is that strike's row, not the one above it. Each
    row's distance is its strike less the price, signed, and that strike's 0.00 unsigned, also
    for a price a rounding above it (INDUCED), whose spot line is the strike above.
    """
    quote = _SPY_PRINT_ON_A_STRIKE
    on = quote["native"]["LAST_PRICE"]
    body = _close_then_print(quote)
    listed = _close_strikes()
    k = listed.index(on)
    assert k >= 5
    assert sorted(r["strike"] for r in body["rows"]) == listed[k - 5 : k + 6]
    assert [r["strike"] for r in body["rows"] if r["spot_line"]] == [on]
    assert [r["distance_text"] for r in body["rows"]] == [
        "0.00" if r["strike"] == on else f"{r['strike'] - on:+.2f}" for r in body["rows"]
    ]
    # each row's heading, whole: its strike and its distance (AGENTS.md rule 4)
    assert [r["heading_said"] for r in body["rows"]] == [
        f"{r['strike_text']} · {r['distance_text']} points from the price" for r in body["rows"]
    ]
    # INDUCED: no live price, so no distance: the heading is the strike alone, never "-" inside
    unpriced = at_price(body["rows"], listed, None, None)
    assert [r["heading_said"] for r in unpriced] == [r["strike_text"] for r in unpriced]
    above = on + 0.004  # INDUCED: a LAST_PRICE a rounding above the strike (four decimals sent)
    nudged = at_price(body["rows"], listed, above, None)
    assert [r["distance_text"] for r in nudged] == [
        "0.00" if r["strike"] == on else f"{r['strike'] - above:+.2f}" for r in nudged
    ]
    assert [r["strike"] for r in nudged if r["spot_line"]] == [listed[k + 1]]


def test_a_price_above_every_listed_strike_has_no_spot_line():
    """SPY's 2026-10-07 chain as captured here and SPY's first kept print above all its strikes.

    The chain's 20 strikes nearest the price, 767 to 786, and SPY's first kept print above all
    of them (LAST_PRICE 787.5169, received 2026-10-23 17:09:50 ET): no listed strike is at or
    above the price, so no row carries the spot line; every row's distance is from that price.
    """
    held, price = SPY_0DTE, _SPY_PRINT_ABOVE["native"]["LAST_PRICE"]
    chain = read_chain(held.chain)
    book, _diag = compute_exposures_by_strike(
        chain, spot=held.spot, now=held.now, sessions=sessions(), product=INDEX_OPTIONS
    )
    matrix = build_matrix(book, {}, iv_by_strike(chain), held.spot, {}, None, {}, {})
    rows = window_rows(matrix, _around(matrix.strikes, price))
    assert price > max(matrix.strikes)
    assert under_strike(price, matrix.strikes) is None
    shown = at_price(rows, matrix.strikes, price, None)
    assert [r["distance_text"] for r in shown] == [f"{r['strike'] - price:+.2f}" for r in rows]
    assert shown and not any(r["spot_line"] for r in shown)
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
    mark_feed_down()
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
    assert set(front["peaks"]) == Shades.__required_keys__
    # the regime on its card, as the screen says it: served, the page picks no words
    regime = next(c for c in front["cards"] if c["label"] == "GAMMA REGIME")
    assert (regime["value"], regime["tone"]) == ("Positive gamma", "pos")
    assert any(r["net_gex"] is not None and r["net_gex"] < 0 for r in front["rows"])


def test_a_passed_expiry_is_not_the_one_the_matrix_opens_on():
    """MRVL's full chain captured Wednesday 2026-10-07 still holds Friday's 2026-10-09 expiry.

    On Sunday, with no expiry chosen (All Expirations), the matrix ranks the front one still
    open: the matrix ranks one expiry, its preset set by that expiry's days to expiration. Friday's
    expiry chosen is said, never answered with the next one's ranking.
    """
    tk = "MRVL"
    listed = sorted({str(c["expirationDate"])[:10] for c in MRVL.chain})
    try:
        _publish_mrvl()
        opened = push_confluence.confluence(tk, _SUNDAY, {"expiry": None, "centre": None})
        asked = push_confluence.confluence(tk, _SUNDAY, {"expiry": listed[0], "centre": None})
        unread = push_confluence.confluence(tk, _SUNDAY, {})
        uncentred = push_confluence.confluence(tk, _SUNDAY, {"expiry": None})
        miscentred = push_confluence.confluence(tk, _SUNDAY, {"expiry": None, "centre": "305"})
    finally:
        level_store._levels.pop(tk, None)
    assert listed[:2] == ["2026-10-09", "2026-10-16"]
    assert (opened["available"], opened["expiry"]) == (True, "2026-10-16")
    assert "expiries" not in opened  # the page's one dropdown lists them, not the matrix
    assert (asked["available"], asked["expiry"]) == (False, "2026-10-09")
    assert asked["reason"] == "the chain lists no open contracts for 2026-10-09"
    assert "rows" not in asked
    assert unread["reason"] == "the request names no expiry"
    # a centre not sent is not a centre of None; one that is no strike is said (centre_asked)
    assert (uncentred["available"], uncentred["reason"]) == (False, "the window names no centre")
    assert miscentred["reason"] == "centre '305' is not a strike"


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


def test_a_strike_whose_volatilities_differ_and_a_weight_is_not_known_has_no_blend():
    """A strike's blend weighs every contract by its open interest plus its volume.

    Contracts carrying one volatility give it whatever their weights. Where they differ, one
    contract's open interest not known leaves the blend unknown ("-"), never the other contracts'
    alone. INDUCED: SPY's captured 0DTE strike nearest the price, its put's open interest withheld,
    the put's volatility first the call's, then a point below it.
    """
    chain = read_chain(SPY_0DTE.chain)
    strike = min(
        {c.strike for c in chain if c.strike is not None}, key=lambda k: abs(k - SPY_0DTE.spot)
    )
    call = next(c for c in chain if c.strike == strike and c.side == "CALL")
    put = next(c for c in chain if c.strike == strike and c.side == "PUT")
    assert call.volatility is not None and call.open_interest and put.open_interest
    assert call.volume is not None and put.volume is not None
    unweighted = replace(put, open_interest=None)
    same = replace(unweighted, volatility=call.volatility)
    lower = replace(unweighted, volatility=call.volatility - 1)
    assert iv_by_strike([call, same])[strike] == call.volatility
    assert iv_by_strike([call, lower])[strike] is None
    weighted = replace(lower, open_interest=put.open_interest)
    w_call = call.open_interest + call.volume
    w_put = put.open_interest + put.volume
    assert iv_by_strike([call, weighted])[strike] == (
        w_call * call.volatility + w_put * (call.volatility - 1)
    ) / (w_call + w_put)


def _window_has(rows: list, key: str) -> bool:
    return any(row.get(key) is not None for row in rows)


def test_the_close_keeps_the_vanna_a_settled_clock_drops():
    """SPY's captured 0DTE chain settles at the index close: no time left, no vanna or charm.

    Operator 2026-11-15: no floor of ours on the time left ("yes the formula needs to account for
    time"), and a settled value is "-" like every value not known ("no settled just a dash"). At
    the close and after it alike, vanna, charm and the gamma if the price were there (a model
    that needs time left), so the Composite, are missing.
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
    gamma_close = gamma_at_strikes(
        contract_inputs(chain, valued, sessions=on_file, product=INDEX_OPTIONS)[0], at_close
    )
    gamma_late = gamma_at_strikes(
        contract_inputs(chain, at, sessions=on_file, product=INDEX_OPTIONS)[0], after
    )
    assert gamma_close == gamma_late == {}
    close = build_matrix(at_close, charm_close, iv, held.spot, gamma_close, None, {}, {})
    late = build_matrix(after, charm_late, iv, held.spot, gamma_late, None, {}, {})
    close_rows = window_rows(close, _around(close.strikes, held.spot))
    late_rows = window_rows(late, _around(late.strikes, held.spot))
    assert not _window_has(close_rows, "vanna_text")
    assert not _window_has(close_rows, "charm_text")
    assert not _window_has(close_rows, "composite")
    assert not _window_has(late_rows, "vanna_text")
    assert not _window_has(late_rows, "charm_text")
    assert not _window_has(late_rows, "composite")


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
    time left, have no vanna, charm or Composite: "-" (operator 2026-11-15).
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
    assert not _window_has(body["rows"], "composite")
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
    data"), its vanna, charm and Composite with them, and the matrix says CLOSE (current at the
    16:15 close, within two of the daemon's rounds) with the chain's time, 16:12, and its age.
    Nothing is priced after the close, so never a value of a made-up time left.
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
    by_strike = {r["strike"]: (r["vanna_text"], r["charm_text"], r["composite"]) for r in live_rows}
    assert _window_has(live_rows, "composite")
    for row in body["rows"]:
        if row["strike"] in by_strike:
            kept = (row["vanna_text"], row["charm_text"], row["composite"])
            assert kept == by_strike[row["strike"]]
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
    vanna, charm or Composite, "-" (operator 2026-11-15). Asked again, the request reads the same
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
    assert not _window_has(body["rows"], "composite")
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
    vanna, charm or Composite: "-" both times (operator 2026-11-15).
    """
    held = SPY_0DTE
    after = datetime(2026, 10, 7, 18, 0, tzinfo=ET)
    first, second = _spy_0dte_twice(_no_value_quote(held.chain), after, after, after)
    near = min(first["rows"], key=lambda row: abs(row["strike"] - held.spot))
    kept = (near["net_gex_text"], near["vanna_text"], near["charm_text"], near["composite_text"])
    assert kept[0] is not None and kept[1:] == (None, None, None)
    again = min(second["rows"], key=lambda row: abs(row["strike"] - held.spot))
    assert (
        again["net_gex_text"],
        again["vanna_text"],
        again["charm_text"],
        again["composite_text"],
    ) == kept


def test_during_the_session_a_no_value_quote_does_not_keep_the_old_greek():
    """During the session Schwab's no-value code is not a greek. It does not keep the older one."""
    held = SPY_0DTE
    session = datetime(2026, 10, 7, 12, 32, tzinfo=ET)
    later = datetime(2026, 10, 7, 12, 40, tzinfo=ET)
    _first, body = _spy_0dte_twice(_no_value_quote(held.chain), session, later, later)
    near = min(body["rows"], key=lambda row: abs(row["strike"] - held.spot))
    assert near["vanna_text"] is None and near["charm_text"] is None
    assert near["composite"] is None and near["gamma_here_text"] is None


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
    left, have no Composite or vanna: "-" both times (operator 2026-11-15).
    """
    held = SPY_0DTE
    after = datetime(2026, 10, 7, 18, 0, tzinfo=ET)
    first, second = _spy_0dte_twice(_zero_counts(held.chain), after, after, after)
    near = min(first["rows"], key=lambda row: abs(row["strike"] - held.spot))
    kept = (near["oi_text"], near["volume_hover"], near["composite_text"], near["vanna_text"])
    assert None not in kept[:2] and kept[2:] == (None, None)
    again = min(second["rows"], key=lambda row: abs(row["strike"] - held.spot))
    assert (
        again["oi_text"],
        again["volume_hover"],
        again["composite_text"],
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
        kept = (shown["oi_text"], shown["volume_hover"], shown["pc_vol_text"])
        with level_store._lock:  # a restart: no levels and no captures held
            level_store._levels.pop(tk, None)
        capture_store.clear()
        _store_by_expiry(tk, fresh, held.spot, capture_at)
        server._publish_levels(
            tk, read_chain(_zero_counts(fresh)), now.timestamp(), chain_spot=spot, now=now
        )
        second = push_confluence.confluence_payload(tk, expiry, now)
        again = next(row for row in second["rows"] if row["strike"] == shown["strike"])
        assert (again["oi_text"], again["volume_hover"], again["pc_vol_text"]) == kept
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
            pushed(
                f"optquote.{m['symbol']}",
                verbatim_msg(
                    symbol=m["symbol"], content=m["native"], src=m["src"], ts_recv=m["ts_recv"]
                ),
            )
        publish_capture(tk, held["chain"], held["ts_utc"], held["spot"], "2026-10-16", after)
        book = level_store.published_levels(tk)
        overlaid = repriced(book)
        kept = {ct.symbol: ct.volume for ct in book.priced_chain if ct.symbol in traded}
        panel = push_chain.chain(
            tk, after.timestamp(), {"expiry": str(held["chain"][0]["expirationDate"])[:10]}
        )
        shown = {
            c["symbol"]: c["volume_text"]
            for r in panel["ladder"]
            for c in (r["call"], r["put"])
            if c
        }
    finally:
        ofls.clear_all_live_state()
        _forget(tk)
    assert overlaid == []
    assert all(m["native"]["TOTAL_VOLUME"] == 0 for m in messages)
    assert all(traded[s] > 0 and kept[s] == traded[s] for s in symbols)
    # the chain panel shows the contracts as the levels priced them
    assert all(shown[s] == f"{traded[s]:,.0f}" for s in symbols)


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
    # before 07:30 ET, the option pre-market Schwab answered on 2026-10-22 itself
    before = datetime(2026, 10, 22, 7, 0, tzinfo=ET)
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
    assert (near["oi_text"], near["volume_hover"]) == ("0", "Today: calls 0 · puts 0")
    assert near["oi"] == 0


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
    # the distances are from the print, the live price
    live = print_["native"]["LAST_PRICE"]
    rows = second["rows"]
    assert all(abs(float(r["distance_text"]) - (r["strike"] - live)) <= 0.005 for r in rows)


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


def test_the_matrix_shows_the_live_price():
    """CRWD's captured chain (2026-10-16 expiry, captured 2026-10-07 10:38:40 ET) and a print.

    The chain is published at the price Schwab sent in that chain answer (its stored capture's
    spot, 269.04), and CRWD's LEVELONE_EQUITIES message the daemon received at 10:38:00 ET
    (LAST_PRICE 269.395), taken in by the plane and made the price row by the daemon's own
    function. The matrix stays ranked at the chain's price; its window and each row's distance
    are the live price's. The price itself, its time and whether it is live are the price row's,
    which the page draws (one producer): the matrix serves no copy of them.
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
    finally:
        _forget(tk)
    listed = sorted({float(c["strikePrice"]) for c in CRWD.chain})
    assert live not in listed
    assert sorted(r["strike"] for r in body["rows"]) == _around(listed, live)
    assert "priced_at_spot" not in body
    copies = {"spot", "spot_text", "spot_time_ct", "spot_not_live_text", "spot_as_of_ts_utc"}
    assert not copies & body.keys(), copies & body.keys()
    # the SPOT card is the price row's place: no value of the matrix's own
    (spot,) = [c for c in body["cards"] if c.get("live_price")]
    assert (spot["label"], spot["value"], spot["sub"]) == ("SPOT", None, None)
    assert all(abs(float(r["distance_text"]) - (r["strike"] - live)) <= 0.005 for r in body["rows"])
    assert [r["strike"] for r in body["rows"] if r["spot_line"]] == [
        min(r["strike"] for r in body["rows"] if r["strike"] >= live)
    ]


def test_the_rows_hold_while_the_price_moves_among_them_and_follow_it_out():
    """CRWD's captured chain (2026-10-16 expiry, captured 2026-10-07 10:38:40 ET) and its print.

    The rows are centred on the strike nearest CRWD's print (LAST_PRICE 269.395). Asked again
    with that centre, as the page sends back the one it was served, they hold while the price
    moves among them, as a trading ladder's rows do, even past the middle of the next strike
    (INDUCED: the price two strikes higher), and are centred on the price again once it has left
    them (INDUCED: a price above the top row). Each answer's rows are every row's distance from
    the price of its own moment.
    """
    tk, at = server.ticker_storage_key(CRWD.ticker), CRWD.now
    expiry = str(CRWD.chain[0]["expirationDate"])[:10]
    listed = sorted({float(c["strikePrice"]) for c in CRWD.chain})

    def asked(last: float, n: int, centre: float | None) -> dict:
        native = {**_QUOTE["native"], "LAST_PRICE": last}
        lmp.record_from_level_one_equity(tk, native, received_ts=_QUOTE["ts_recv"] + n)
        params = {"expiry": expiry, "lookback": "5", "centre": centre}
        return push_confluence.confluence(tk, at, params)

    live = _QUOTE["native"]["LAST_PRICE"]
    lmp.record_feed_heartbeat(
        daemon_status(at.timestamp(), schwab_socket_open=True, held={"LEVELONE_EQUITIES": [tk]})
    )
    try:
        publish_capture(tk, CRWD.chain, at.timestamp(), CRWD.spot, at.date().isoformat(), at)
        first = asked(live, 0, None)
        held = first["view"]["centre"]
        strikes = sorted(r["strike"] for r in first["rows"])
        moved = listed[listed.index(held) + 2]  # two strikes up, still among the rows
        among = asked(moved, 1, held)
        out = max(strikes) + 1.0  # past the top row
        left = asked(out, 2, held)
    finally:
        _forget(tk)
    assert strikes == _around(listed, live) and held == min(listed, key=lambda s: abs(s - live))
    assert min(strikes) < moved < max(strikes)
    assert sorted(r["strike"] for r in among["rows"]) == strikes != _around(listed, moved)
    assert among["view"]["centre"] == held
    rows = among["rows"]
    assert all(abs(float(r["distance_text"]) - (r["strike"] - moved)) <= 0.005 for r in rows)
    assert sorted(r["strike"] for r in left["rows"]) == _around(listed, out) != strikes
    assert left["view"]["centre"] == min(listed, key=lambda s: abs(s - out))
