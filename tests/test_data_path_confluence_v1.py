"""Schwab -> the confluence matrix. The score is the chain already priced, ranked once."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import app.options.order_flow.state as ofls
import live_market_plane as lmp
import live_price_rows
from app.options.order_flow import streaming as ofs
from calibration.complete_chain_capture import CAPTURE_BASIS, persist_complete_chain_capture
from confluence_composite import (
    at_price, build_matrix, iv_by_strike, magnitudes, place_markers, score_magnitudes,
    under_strike, window_strikes,
)
from math_exposure_core import bucket_metric, compute_exposures_by_strike
from math_levels import compute_charm_by_strike
from numeric_contract import price_text
from stream_spine import options_quote_msg
from terrain_engine import compute_terrain
from time_et import ET, INDEX_OPTIONS, ct_label, valuation_instant

import server
from tests.real_chains import CRWD, MRVL, SPY_0DTE, SPY_AFTER_HOURS_PRINT, SPY_CLOSE, TSLA

_QUOTE = json.loads((Path(__file__).resolve().parent / "fixtures" / "real_crwd_quote_2026_10_07.json")
                    .read_text(encoding="utf-8"))


def _store(tk: str, cache: dict) -> None:
    """The publication ranks once. The request then reads that ranking."""
    cache["_matrix_by_expiry"] = server._ranked_matrices(cache)
    server._terrain_cache[tk] = cache


def test_a_missing_gamma_blanks_the_score_and_the_top_is_not_100():
    """The worked example. Strike 795 has charm 8 and no gamma, so its score is absent.
    The highest score is 70, not 100."""
    rows = {
        770.0: {"GEXM": 10.0, "CHARMM": 5.0, "OI": 1.0, "VOL": 1.0},
        775.0: {"GEXM": 30.0, "CHARMM": 5.0, "OI": 1.0, "VOL": 1.0},
        780.0: {"GEXM": 20.0, "CHARMM": 15.0, "OI": 1.0, "VOL": 1.0},
        785.0: {"GEXM": 50.0, "CHARMM": 2.0, "OI": 1.0, "VOL": 1.0},
        790.0: {"GEXM": 40.0, "CHARMM": 9.0, "OI": 1.0, "VOL": 1.0},
        795.0: {"GEXM": None, "CHARMM": 8.0, "OI": 1.0, "VOL": 1.0},
    }
    scored, _flat, _spans = score_magnitudes(rows, {"GEXM": 0.6, "CHARMM": 0.4})
    shown = {strike: None if row["score"] is None else int(round(row["score"]))
             for strike, row in scored.items()}
    assert shown[795.0] is None
    assert "net gamma" in scored[795.0]["missing"]
    assert shown[770.0] == 8
    assert shown[775.0] == 38
    assert shown[780.0] == 53
    assert shown[785.0] == 60
    assert shown[790.0] == 70
    assert max(v for v in shown.values() if v is not None) == 70


def test_a_missing_factor_is_not_called_flat():
    """A strike that is missing charm blanks its score. Strikes that have charm at one
    value do not make the note say charm does not vary."""
    rows = {
        770.0: {"GEXM": 10.0, "CHARMM": None, "OI": 1.0, "VOL": 1.0},
        775.0: {"GEXM": 10.0, "CHARMM": 0.0, "OI": 0.0, "VOL": 1.0},
    }
    scored, flat, _spans = score_magnitudes(rows, {"GEXM": 0.5, "CHARMM": 0.5})
    assert "CHARMM" not in flat
    assert scored[770.0]["score"] is None
    assert "charm" in scored[770.0]["missing"]


def _publish_close(tk: str = "SPY") -> dict:
    """SPY's 2026-10-22 close capture, published as the stored capture it is, at Schwab's price."""
    server._publish_levels(tk, captures=[{"contracts": [dict(c) for c in SPY_CLOSE.chain],
                                          "ts_utc": SPY_CLOSE.now.timestamp(), "spot": SPY_CLOSE.spot,
                                          "et_date": SPY_CLOSE.now.date().isoformat(),
                                          "basis": CAPTURE_BASIS, "spot_ts": None}], now=SPY_CLOSE.now)
    with server._terrain_cache_lock:
        return server._terrain_cache[tk]


def test_the_matrix_reads_the_priced_book_and_leaves_flow_out():
    """SPY's 2026-10-22 close capture, its same-day expiry: the matrix ranks the book the
    publication priced, each row's net and gross gamma that book's own numbers (millions, two
    decimals, net signed), flow and the change in gamma empty, and a same-day expiry's score
    cannot pass 72."""
    try:
        live = _publish_close()
        book = live["_books"][("2026-10-22", 0.0)][0]
        body = server.confluence_payload("SPY", "2026-10-22", SPY_CLOSE.now)
    finally:
        server._terrain_cache.pop("SPY", None)
    assert body["available"] is True
    assert (body["preset"], body["ceiling"]) == ("0DTE", 72)
    assert body["weights_in_score"]["FLOWM"] == 0 and body["weights_in_score"]["DGEXM"] == 0
    assert body["expiries"][0]["label"] == "0DTE · 2026-10-22"
    checked = grossed = 0
    for row in body["rows"]:
        bucket = book[row["strike"]]
        assert row["strike_text"] == price_text(row["strike"])
        assert row["flow_text"] is None and row["dgex_text"] is None
        net = bucket_metric(bucket, "net_gex_1pct")
        call, put = bucket_metric(bucket, "call_gex_1pct"), bucket_metric(bucket, "put_gex_1pct")
        if net is not None and abs(net) >= 5_000:
            assert row["net_gex_text"] == f"{net / 1e6:+.2f}"
            assert row["heat_background"].startswith("background:")
            checked += 1
        if call is not None and put is not None and call >= 0 and put >= 0:
            assert row["gross_text"] == f"{(call + put) / 1e6:.2f}"
            grossed += 1
    assert checked > 5 and grossed > 5


def test_a_zero_book_is_zero_charm_and_the_wall_is_drawn_at_its_own_price():
    """SPY's 2026-10-22 close capture: a strike whose every contract Schwab sent with open interest
    0 has no charm entry, and its book's charm magnitude is 0, not missing. The publication's call
    wall is a level at its own price, in the options lane, its text two decimals."""
    zero_oi = sorted(k for k in {c["strikePrice"] for c in SPY_CLOSE.chain}
                     if all(c["openInterest"] == 0 for c in SPY_CLOSE.chain if c["strikePrice"] == k))
    strike = zero_oi[0]
    inside = datetime(2026, 10, 22, 15, 0, tzinfo=ET)       # before the close: charm has time
    legs = [dict(c) for c in SPY_CLOSE.chain if c["strikePrice"] == strike]
    assert strike not in compute_charm_by_strike(legs, SPY_CLOSE.spot, now=inside)
    try:
        live = _publish_close()
        bucket = live["_books"][("2026-10-22", 0.0)][0][strike]
        body = server.confluence_payload("SPY", "2026-10-22", SPY_CLOSE.now)
    finally:
        server._terrain_cache.pop("SPY", None)
    assert magnitudes(bucket, None, None, SPY_CLOSE.spot)["CHARMM"] == 0.0
    walls = [level for level in body["levels"] if level["abbrev"] == "CW"]
    assert [(w["price"], w["price_text"], w["lane"]) for w in walls] == [
        (live["call_wall"], price_text(live["call_wall"]), "options")]


def test_a_served_strike_with_no_open_interest_shows_zero_charm_and_says_why_it_is_unscored():
    """SPY's 2026-10-14 expiry as the console served it 2026-10-01 08:59:47 ET
    (tests/fixtures/real_spy_2026_10_14_chain_oi_zero.json): strikes 761 to 764, inside the window,
    have open interest 0 on both legs and no volume. Each one's charm on the matrix is 0.00, not
    missing; with no open interest and no volume the strike is not scored, and says why."""
    fx = json.loads((Path(__file__).resolve().parent / "fixtures" / "real_spy_2026_10_14_chain_oi_zero.json")
                    .read_text(encoding="utf-8"))
    at = datetime.fromtimestamp(fx["chain_as_of_ts_utc"], ET)
    zero = {k for k in {c["strikePrice"] for c in fx["contracts"]}
            if all(c["openInterest"] == 0 for c in fx["contracts"] if c["strikePrice"] == k)}
    try:
        server._publish_levels("SPY", captures=[{"contracts": [dict(c) for c in fx["contracts"]],
                                                 "ts_utc": fx["chain_as_of_ts_utc"], "spot": fx["priced_at_spot"],
                                                 "et_date": at.date().isoformat(), "basis": CAPTURE_BASIS, "spot_ts": None}], now=at)
        body = server.confluence_payload("SPY", fx["expiry"], at)
    finally:
        server._terrain_cache.pop("SPY", None)
    shown = [r for r in body["rows"] if r["strike"] in zero]
    assert len(shown) >= 4
    assert all(r["charm_text"] == "0.00" and r["charm_reason"] is None for r in shown)
    assert all(r["score"] is None and r["missing"] == ["no open interest and no volume"] for r in shown)


def test_the_window_is_five_strikes_each_side_of_the_price():
    """Five listed strikes below the price, five above, and the strike on the price."""
    strikes = [float(n) for n in range(100, 121)]
    assert window_strikes(strikes, 110.0) == [float(n) for n in range(105, 116)]


def test_a_level_on_a_listed_strike_sits_on_that_strike():
    """A call wall that is itself a listed strike is that row, including the highest strike.
    The spot line uses the same rule."""
    strikes = [665.0, 670.0, 675.0]
    assert under_strike(670.0, strikes) == 670.0
    assert under_strike(675.0, strikes) == 675.0
    assert under_strike(669.0, strikes) == 670.0
    assert under_strike(680.0, strikes) is None
    bucket = {
        "dollarized": True, "oi_unreported": 0, "volume_unreported": 0,
        "call_oi": 10.0, "put_oi": 4.0, "call_volume": 3.0, "put_volume": 1.0,
        "call_gex_1pct": 30_000_000.0, "put_gex_1pct": 12_000_000.0, "net_gex_1pct": 18_000_000.0,
        "call_dex_dollars": 5.0, "put_dex_dollars": 2.0, "net_dex_dollars": 3.0,
        "call_vanna": 1.0, "put_vanna": 0.0, "net_vanna": 1.0,
        "call_gamma_unreported": 0, "put_gamma_unreported": 0,
        "call_delta_unreported": 0, "put_delta_unreported": 0,
        "call_vanna_unreported": 0, "put_vanna_unreported": 0,
    }
    exposures = {strike: bucket for strike in strikes}
    placed = place_markers([
        {"label": "Call wall", "price": 670.0},
        {"label": "Put wall", "price": 675.0},
        {"label": "Above", "price": 680.0},
    ], strikes)
    body = build_matrix(exposures, {}, {}, 669.0, 0, placed)
    by_strike = {row["strike"]: row for row in body["rows"]}
    assert "Call wall" in by_strike[670.0]["markers"]
    assert "Call wall" not in by_strike[675.0]["markers"]
    assert "Put wall" in by_strike[675.0]["markers"]
    assert [item["label"] for item in body["offscreen"]] == ["Above"]
    assert body["offscreen"][0]["price_text"] == "680.00"
    on_spot = build_matrix(exposures, {}, {}, 670.0, 0, [])
    at_price(on_spot["rows"], on_spot["strikes"], 670.0)
    assert [row["strike"] for row in on_spot["rows"] if row["spot_line"]] == [670.0]


def test_a_passed_expiry_is_not_the_one_the_matrix_opens_on():
    """MRVL's full chain captured Wednesday 2026-10-07 still holds Friday's 2026-10-09 expiry. On
    Sunday the matrix opens on the next one, and a request for Friday's opens there too."""
    tk = "MRVL"
    sunday = datetime(2026, 10, 11, 12, 0, tzinfo=ET)
    listed = sorted({str(c["expirationDate"])[:10] for c in MRVL.chain})
    try:
        server._publish_levels(tk, captures=[{"contracts": [dict(c) for c in MRVL.chain],
                                              "ts_utc": MRVL.now.timestamp(), "spot": MRVL.spot,
                                              "et_date": MRVL.now.date().isoformat(),
                                              "basis": CAPTURE_BASIS, "spot_ts": None}], now=MRVL.now)
        opened = server.confluence_payload(tk, None, sunday)
        asked = server.confluence_payload(tk, listed[0], sunday)
    finally:
        server._terrain_cache.pop(tk, None)
    assert listed[:2] == ["2026-10-09", "2026-10-16"]
    assert (opened["available"], opened["expiry"]) == (True, "2026-10-16")
    assert "2026-10-09" not in [e["expiry"] for e in opened["expiries"]]
    assert (asked["available"], asked["expiry"]) == (True, "2026-10-16")


def test_the_matrix_reads_the_expiry_charm_map_and_does_not_rebuild_it():
    """Charm is the map the book stored for this expiry. SPY's captured 0DTE chain valued an hour
    before its capture is a different charm map than the chain valued at its capture would build;
    stored with the book, it is the charm on the matrix (thousands, two decimals, signed)."""

    held = SPY_0DTE
    expiry = str(held.chain[0]["expirationDate"])[:10]
    book, _diag = compute_exposures_by_strike(
        held.chain, spot=held.spot, now=held.now, product=INDEX_OPTIONS)
    earlier = compute_charm_by_strike(held.chain, held.spot, now=held.now - timedelta(hours=1),
                                      product=INDEX_OPTIONS)
    at_capture = compute_charm_by_strike(held.chain, held.spot, now=held.now, product=INDEX_OPTIONS)
    strike = min(book, key=lambda s: abs(s - held.spot))
    _store("SPY", {
        "spot": held.spot, "computed_ts_utc": held.now.timestamp(),
        "_valued_ts_utc": held.now.timestamp(),
        "expiry_dte": {expiry: 0},
        "_books": {(expiry, 0): (book, None)},
        "_priced_chain": held.chain,
        "_charm_by_expiry": {expiry: earlier},
    })
    try:
        body = server.confluence_payload("SPY", expiry, held.now)
    finally:
        server._terrain_cache.pop("SPY", None)
    row = next(r for r in body["rows"] if r["strike"] == strike)
    assert earlier[strike]["net_charm"] != at_capture[strike]["net_charm"]
    assert row["charm_text"] == f"{earlier[strike]['net_charm'] / 1000:+.2f}"


def test_the_matrix_reads_the_expiry_volatility_blend_and_does_not_rebuild_it():
    """The volatility column is the blend the book stored for this expiry. The blend of SPY's
    2026-10-22 close chain, stored with SPY's 2026-10-07 0DTE book, is not the blend that chain
    would build; it is the volatility on the matrix (one decimal)."""

    held = SPY_0DTE
    expiry = str(held.chain[0]["expirationDate"])[:10]
    book, _diag = compute_exposures_by_strike(
        held.chain, spot=held.spot, now=held.now, product=INDEX_OPTIONS)
    puts = iv_by_strike(SPY_CLOSE.chain)
    whole = iv_by_strike(held.chain)
    strike = min(book, key=lambda s: abs(s - held.spot))
    _store("SPY", {
        "spot": held.spot, "computed_ts_utc": held.now.timestamp(),
        "_valued_ts_utc": held.now.timestamp(),
        "expiry_dte": {expiry: 0},
        "_books": {(expiry, 0): (book, None)},
        "_priced_chain": held.chain,
        "_iv_by_expiry": {expiry: puts},
    })
    try:
        body = server.confluence_payload("SPY", expiry, held.now)
    finally:
        server._terrain_cache.pop("SPY", None)
    differ = [r for r in body["rows"] if r["strike"] in puts and r["strike"] in whole
              and f"{puts[r['strike']]:.1f}" != f"{whole[r['strike']]:.1f}"]
    assert differ and all(r["iv_text"] == f"{puts[r['strike']]:.1f}" for r in differ)


def test_the_matrix_request_returns_the_ranking_stored_with_the_book():
    """The request does not rank again. The ranking of SPY's 2026-10-22 close book, stored with
    SPY's 2026-10-07 chain, is not a ranking that chain could produce; the request returns it."""

    held = SPY_0DTE
    expiry = str(held.chain[0]["expirationDate"])[:10]
    try:
        other = _publish_close()["_matrix_by_expiry"]["2026-10-22"]
        server._terrain_cache["SPY"] = {
            "spot": held.spot, "computed_ts_utc": held.now.timestamp(),
            "_valued_ts_utc": held.now.timestamp(),
            "expiry_dte": {expiry: 0},
            "_books": {(expiry, 0): ({held.spot: {}}, None)},
            "_priced_chain": held.chain,
            "_matrix_by_expiry": {expiry: other},
        }
        body = server.confluence_payload("SPY", expiry, held.now)
    finally:
        server._terrain_cache.pop("SPY", None)
    assert [r["strike"] for r in body["rows"]] == [r["strike"] for r in other["rows"]]
    assert [(r["score_text"], r["iv_text"], r["charm_text"]) for r in body["rows"]] == [
        (r["score_text"], r["iv_text"], r["charm_text"]) for r in other["rows"]]


def _window_has(rows: list, key: str) -> bool:
    return any(row.get(key) is not None for row in rows)


def test_the_close_keeps_the_vanna_a_settled_clock_drops():
    """SPY's captured 0DTE chain, valued at the index close, still has vanna, charm, and a
    score. The same chain priced after that close has no time left, and those three are missing."""

    held = SPY_0DTE
    at = datetime(2026, 10, 7, 18, 0, tzinfo=ET)
    valued = valuation_instant(at, INDEX_OPTIONS)
    at_close, _diag = compute_exposures_by_strike(
        held.chain, spot=held.spot, now=valued, product=INDEX_OPTIONS)
    after, _diag = compute_exposures_by_strike(
        held.chain, spot=held.spot, now=at, product=INDEX_OPTIONS)
    strike = min(at_close, key=lambda s: abs(s - held.spot))
    assert bucket_metric(at_close[strike], "net_vanna") is not None
    assert bucket_metric(after[strike], "net_vanna") is None
    iv = iv_by_strike(held.chain)
    charm_close = compute_charm_by_strike(held.chain, held.spot, now=valued, product=INDEX_OPTIONS)
    charm_late = compute_charm_by_strike(held.chain, held.spot, now=at, product=INDEX_OPTIONS)
    close_rows = build_matrix(at_close, charm_close, iv, held.spot, 0.0, [])["rows"]
    late_rows = build_matrix(after, charm_late, iv, held.spot, 0.0, [])["rows"]
    assert _window_has(close_rows, "vanna_text")
    assert _window_has(close_rows, "charm_text")
    assert _window_has(close_rows, "score")
    assert not _window_has(late_rows, "vanna_text")
    assert not _window_has(late_rows, "charm_text")
    assert not _window_has(late_rows, "score")


def test_spy_keeps_vanna_until_the_index_close():
    """SPY settles at the index close. At 4:10 PM ET the equity-option close has passed
    and the index close has not, so this captured chain's vanna still stands."""

    held = SPY_0DTE
    at = datetime(2026, 10, 7, 16, 10, tzinfo=ET)
    book, _diag = compute_exposures_by_strike(
        held.chain, spot=held.spot, now=at, product=INDEX_OPTIONS)
    equity, _diag = compute_exposures_by_strike(held.chain, spot=held.spot, now=at)
    strike = min(book, key=lambda s: abs(s - held.spot))
    assert bucket_metric(book[strike], "net_vanna") is not None
    assert bucket_metric(equity[strike], "net_vanna") is None


def test_a_chain_delivered_after_the_close_still_fills_the_matrix():
    """The page reads the publication. SPY's captured chain, delivered after the index
    close, is valued at that close, so vanna, charm, and the score are on the matrix."""

    held = SPY_0DTE
    tk = "SPY"
    at = datetime(2026, 10, 7, 18, 0, tzinfo=ET)
    expiry = str(held.chain[0]["expirationDate"])[:10]
    ofs._price_rows[tk] = {"ticker": tk, "spot": held.spot, "trade_ts": at.timestamp()}
    try:
        snap = server._publish_levels(tk, held.chain, at.timestamp(), chain_spot=(held.spot, None), now=at)
        body = server.confluence_payload(tk, expiry, at)
    finally:
        ofs._price_rows.pop(tk, None)
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)
    assert snap is not None
    assert body["available"] is True
    assert _window_has(body["rows"], "vanna_text")
    assert _window_has(body["rows"], "charm_text")
    assert _window_has(body["rows"], "score")
    blend = iv_by_strike(
        [ct for ct in held.chain if str(ct.get("expirationDate"))[:10] == expiry])
    shown = next(r for r in body["rows"] if blend.get(r["strike"]) is not None)
    assert shown["iv_text"] == f"{blend[shown['strike']]:.1f}"


def test_a_later_expiry_keeps_its_columns_at_that_expirys_close():
    """TSLA's captured Friday chain, delivered after that Friday's equity close, is valued
    at that close. The same publication fills vanna, charm, and the score. The request reads it."""

    held = TSLA
    tk = "TSLA"
    at = datetime(2026, 10, 9, 18, 0, tzinfo=ET)
    expiry = str(held.chain[0]["expirationDate"])[:10]
    ofs._price_rows[tk] = {"ticker": tk, "spot": held.spot, "trade_ts": at.timestamp()}
    try:
        snap = server._publish_levels(tk, held.chain, at.timestamp(), chain_spot=(held.spot, None), now=at)
        body = server.confluence_payload(tk, expiry, at)
        again = server.confluence_payload(tk, expiry, at)
    finally:
        ofs._price_rows.pop(tk, None)
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)
    assert snap is not None
    assert expiry == "2026-10-09"
    assert body["available"] is True
    assert _window_has(body["rows"], "vanna_text")
    assert _window_has(body["rows"], "charm_text")
    assert _window_has(body["rows"], "score")
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
    """SPY's captured chain is published after the index close, valued at that close. A later
    quote that sends Schwab's no-value code does not erase that quote's gamma, vanna, or charm."""

    held = SPY_0DTE
    tk = "SPY"
    after = datetime(2026, 10, 7, 18, 0, tzinfo=ET)
    expiry = str(held.chain[0]["expirationDate"])[:10]
    ofs._price_rows[tk] = {"ticker": tk, "spot": held.spot, "trade_ts": after.timestamp()}
    try:
        server._publish_levels(tk, [dict(c) for c in held.chain], after.timestamp(), chain_spot=(held.spot, None), now=after)
        first = server.confluence_payload(tk, expiry, after)
        near = min(first["rows"], key=lambda row: abs(row["strike"] - held.spot))
        kept = (near["net_gex_text"], near["vanna_text"], near["charm_text"], near["score_text"])
        assert None not in kept
        server._publish_levels(tk, _no_value_quote(held.chain), after.timestamp(), chain_spot=(held.spot, None), now=after)
        second = server.confluence_payload(tk, expiry, after)
        again = min(second["rows"], key=lambda row: abs(row["strike"] - held.spot))
        assert (again["net_gex_text"], again["vanna_text"], again["charm_text"], again["score_text"]) == kept
    finally:
        ofs._price_rows.pop(tk, None)
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)


def test_during_the_session_a_no_value_quote_does_not_keep_the_old_greek():
    """During the session Schwab's no-value code is not a greek. It does not keep the older one."""

    held = SPY_0DTE
    tk = "SPY"
    session = datetime(2026, 10, 7, 12, 32, tzinfo=ET)
    later = datetime(2026, 10, 7, 12, 40, tzinfo=ET)
    expiry = str(held.chain[0]["expirationDate"])[:10]
    ofs._price_rows[tk] = {"ticker": tk, "spot": held.spot, "trade_ts": session.timestamp()}
    try:
        server._publish_levels(tk, [dict(c) for c in held.chain], session.timestamp(), chain_spot=(held.spot, None), now=session)
        server._publish_levels(tk, _no_value_quote(held.chain), later.timestamp(), chain_spot=(held.spot, None), now=later)
        body = server.confluence_payload(tk, expiry, later)
        near = min(body["rows"], key=lambda row: abs(row["strike"] - held.spot))
        assert near["vanna_text"] is None and near["charm_text"] is None and near["score"] is None
    finally:
        ofs._price_rows.pop(tk, None)
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)


def _zero_counts(chain):
    """The chain Schwab sends after the close: open interest and volume both zero."""
    zeroed = []
    for ct in chain:
        row = dict(ct)
        row["openInterest"] = 0
        row["totalVolume"] = 0
        zeroed.append(row)
    return zeroed


def test_a_zero_count_after_the_close_keeps_the_last_reported_count():
    """SPY's captured chain is published after the index close. A later chain that reports
    zero open interest and zero volume does not erase those counts, or the score they carry."""

    held = SPY_0DTE
    tk = "SPY"
    after = datetime(2026, 10, 7, 18, 0, tzinfo=ET)
    expiry = str(held.chain[0]["expirationDate"])[:10]
    ofs._price_rows[tk] = {"ticker": tk, "spot": held.spot, "trade_ts": after.timestamp()}
    try:
        server._publish_levels(tk, [dict(c) for c in held.chain], after.timestamp(), chain_spot=(held.spot, None), now=after)
        first = server.confluence_payload(tk, expiry, after)
        near = min(first["rows"], key=lambda row: abs(row["strike"] - held.spot))
        kept = (near["oi_text"], near["volume_text"], near["score_text"], near["vanna_text"])
        assert None not in kept
        server._publish_levels(tk, _zero_counts(held.chain), after.timestamp(), chain_spot=(held.spot, None), now=after)
        second = server.confluence_payload(tk, expiry, after)
        again = min(second["rows"], key=lambda row: abs(row["strike"] - held.spot))
        assert (again["oi_text"], again["volume_text"], again["score_text"], again["vanna_text"]) == kept
    finally:
        ofs._price_rows.pop(tk, None)
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)


def _first_chain_keeps_the_capture(now, capture_at):
    """No chain is in memory. The delivered chain reports zero counts. The stored capture
    is the last count, so put/call volume stays."""

    held = SPY_0DTE
    tk = "SPYKEEP"
    expiry = str(held.chain[0]["expirationDate"])[:10]
    fresh = [dict(c) for c in held.chain]
    ofs._price_rows[tk] = {"ticker": tk, "spot": held.spot, "trade_ts": now.timestamp()}
    try:
        server._publish_levels(tk, [dict(c) for c in fresh], now.timestamp(), chain_spot=(held.spot, None), now=now)
        first = server.confluence_payload(tk, expiry, now)
        shown = next(row for row in first["rows"] if row["pc_vol_text"] is not None)
        kept = (shown["oi_text"], shown["volume_text"], shown["pc_vol_text"])
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)
        by_expiry: dict = {}
        for ct in fresh:
            by_expiry.setdefault(str(ct["expirationDate"])[:10], []).append(ct)
        for exp, cts in by_expiry.items():
            persist_complete_chain_capture(
                server.get_db().db_path, ticker=tk, expiry=exp,
                contracts=[dict(c) for c in cts], spot=held.spot,
                completeness_basis=CAPTURE_BASIS, ts_utc=capture_at.timestamp())
        server._publish_levels(tk, _zero_counts(fresh), now.timestamp(), chain_spot=(held.spot, None), now=now)
        second = server.confluence_payload(tk, expiry, now)
        again = next(row for row in second["rows"] if row["strike"] == shown["strike"])
        assert (again["oi_text"], again["volume_text"], again["pc_vol_text"]) == kept
    finally:
        ofs._price_rows.pop(tk, None)
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)


def test_the_first_chain_after_the_close_keeps_the_stored_counts():
    """A restart after the close has no chain in memory. The chain the daemon delivers
    reports zero open interest and zero volume. The stored close capture is the last
    count, so put/call volume stays."""
    _first_chain_keeps_the_capture(
        datetime(2026, 10, 7, 18, 0, tzinfo=ET),
        datetime(2026, 10, 7, 16, 15, tzinfo=ET))


def test_a_chain_before_the_next_open_keeps_the_stored_counts():
    """Before the next option window opens, a delivered chain of zeros does not erase
    the stored close capture's volume."""
    _first_chain_keeps_the_capture(
        datetime(2026, 10, 7, 8, 0, tzinfo=ET),
        datetime(2026, 10, 6, 16, 0, tzinfo=ET))


def test_a_closed_day_keeps_a_reported_zero():
    """A day with no option window keeps a reported zero. The stored capture does not fill it."""

    held = SPY_0DTE
    tk = "SPYCLOSED"
    closed = datetime(2026, 10, 4, 12, 0, tzinfo=ET)
    expiry = str(held.chain[0]["expirationDate"])[:10]
    fresh = [dict(c) for c in held.chain]
    ofs._price_rows[tk] = {"ticker": tk, "spot": held.spot, "trade_ts": closed.timestamp()}
    try:
        by_expiry: dict = {}
        for ct in fresh:
            by_expiry.setdefault(str(ct["expirationDate"])[:10], []).append(ct)
        for exp, cts in by_expiry.items():
            persist_complete_chain_capture(
                server.get_db().db_path, ticker=tk, expiry=exp,
                contracts=[dict(c) for c in cts], spot=held.spot,
                completeness_basis=CAPTURE_BASIS,
                ts_utc=datetime(2026, 10, 2, 16, 0, tzinfo=ET).timestamp())
        server._publish_levels(tk, _zero_counts(fresh), closed.timestamp(), chain_spot=(held.spot, None), now=closed)
        body = server.confluence_payload(tk, expiry, closed)
        assert body["rows"]
        assert all(row["pc_vol_text"] is None for row in body["rows"])
    finally:
        ofs._price_rows.pop(tk, None)
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)


def _no_value_counts(chain):
    """The chain with Schwab's no-value code on open interest and volume."""
    coded = []
    for ct in chain:
        row = dict(ct)
        row["openInterest"] = -999
        row["totalVolume"] = -999
        coded.append(row)
    return coded


def test_a_no_value_count_after_the_close_is_not_the_last_count():
    """Schwab's no-value code is not a reported zero. It does not keep the last count."""

    held = SPY_0DTE
    tk = "SPY"
    after = datetime(2026, 10, 7, 18, 0, tzinfo=ET)
    expiry = str(held.chain[0]["expirationDate"])[:10]
    ofs._price_rows[tk] = {"ticker": tk, "spot": held.spot, "trade_ts": after.timestamp()}
    try:
        server._publish_levels(tk, [dict(c) for c in held.chain], after.timestamp(), chain_spot=(held.spot, None), now=after)
        first = server.confluence_payload(tk, expiry, after)
        assert any(row["pc_vol_text"] is not None for row in first["rows"])
        server._publish_levels(tk, _no_value_counts(held.chain), after.timestamp(), chain_spot=(held.spot, None), now=after)
        second = server.confluence_payload(tk, expiry, after)
        assert all(row["pc_vol_text"] is None for row in second["rows"])
    finally:
        ofs._price_rows.pop(tk, None)
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)


def test_a_chain_begun_inside_the_window_keeps_its_reported_zero():
    """A chain fetched before the close and priced after it keeps the zero it reported."""

    held = SPY_0DTE
    tk = "SPY"
    inside = datetime(2026, 10, 7, 16, 10, tzinfo=ET)
    after = datetime(2026, 10, 7, 16, 20, tzinfo=ET)
    expiry = str(held.chain[0]["expirationDate"])[:10]
    ofs._price_rows[tk] = {"ticker": tk, "spot": held.spot, "trade_ts": inside.timestamp()}
    try:
        server._publish_levels(tk, [dict(c) for c in held.chain], inside.timestamp(), chain_spot=(held.spot, None), now=inside)
        first = server.confluence_payload(tk, expiry, inside)
        assert any(row["pc_vol_text"] is not None for row in first["rows"])
        server._publish_levels(tk, _zero_counts(held.chain), inside.timestamp(), chain_spot=(held.spot, None), now=after)
        second = server.confluence_payload(tk, expiry, after)
        assert all(row["pc_vol_text"] is None for row in second["rows"])
    finally:
        ofs._price_rows.pop(tk, None)
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)


def test_a_closed_day_zero_does_not_hide_the_capture_before_the_open():
    """Monday before the open, Saturday's zero book is not the last count. The capture is."""

    held = SPY_0DTE
    tk = "SPYMON"
    fresh = [dict(c) for c in held.chain]
    expiry = str(fresh[0]["expirationDate"])[:10]
    before = datetime(2026, 10, 5, 8, 0, tzinfo=ET)
    ofs._price_rows[tk] = {"ticker": tk, "spot": held.spot, "trade_ts": before.timestamp()}
    try:
        server._publish_levels(tk, [dict(c) for c in fresh], before.timestamp(), chain_spot=(held.spot, None), now=before)
        first = server.confluence_payload(tk, expiry, before)
        shown = next(row for row in first["rows"] if row["pc_vol_text"] is not None)
        kept = shown["pc_vol_text"]
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)
        by_expiry: dict = {}
        for ct in fresh:
            by_expiry.setdefault(str(ct["expirationDate"])[:10], []).append(ct)
        for exp, cts in by_expiry.items():
            persist_complete_chain_capture(
                server.get_db().db_path, ticker=tk, expiry=exp,
                contracts=[dict(c) for c in cts], spot=held.spot,
                completeness_basis=CAPTURE_BASIS,
                ts_utc=datetime(2026, 10, 2, 16, 0, tzinfo=ET).timestamp())
        closed = datetime(2026, 10, 4, 12, 0, tzinfo=ET)
        server._publish_levels(tk, _zero_counts(fresh), closed.timestamp(), chain_spot=(held.spot, None), now=closed)
        wiped = server.confluence_payload(tk, expiry, closed)
        assert all(row["pc_vol_text"] is None for row in wiped["rows"])
        server._publish_levels(tk, _zero_counts(fresh), before.timestamp(), chain_spot=(held.spot, None), now=before)
        second = server.confluence_payload(tk, expiry, before)
        again = next(row for row in second["rows"] if row["strike"] == shown["strike"])
        assert again["pc_vol_text"] == kept
    finally:
        ofs._price_rows.pop(tk, None)
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)


def test_a_streamed_zero_after_the_close_does_not_replace_the_capture():
    """Publishing the stored capture after the close keeps its volume when the stream says 0."""

    held = SPY_0DTE
    tk = "SPY"
    after = datetime(2026, 10, 7, 18, 0, tzinfo=ET)
    capture_at = datetime(2026, 10, 7, 16, 15, tzinfo=ET)
    fresh = [dict(c) for c in held.chain]
    target = next(ct for ct in fresh if isinstance(ct.get("totalVolume"), (int, float))
                  and ct["totalVolume"] > 0 and ct.get("symbol"))
    ofls.clear_all_live_state()
    ofs._price_rows[tk] = {"ticker": tk, "spot": held.spot, "trade_ts": after.timestamp()}
    try:
        symbols = [ct["symbol"] for ct in fresh if ct.get("symbol")]
        lmp.record_feed_heartbeat({"ts": after.timestamp(), "schwab_socket_open": True,
                                   "held": {"LEVELONE_EQUITIES": [tk], "LEVELONE_OPTIONS": symbols}})
        for sym in symbols:
            ofs._ingest_pushed(
                f"optquote.{sym}",
                options_quote_msg(symbol=sym, content={"key": sym, "TOTAL_VOLUME": 0},
                                  src="schwab_options_l1", ts_recv=after.timestamp()))
        server._publish_levels(tk, captures=[{
            "contracts": fresh, "ts_utc": capture_at.timestamp(), "spot": held.spot,
            "basis": CAPTURE_BASIS, "spot_ts": None, "et_date": "2026-10-07"}], now=after)
        book = server.terrain_cache_get(tk, after.timestamp())
        assert book["_gamma_surface"]["stream_overlay_contracts"]
        kept = next(ct for ct in book["_priced_chain"] if ct.get("symbol") == target["symbol"])
        assert kept["totalVolume"] == target["totalVolume"]
    finally:
        ofls.clear_all_live_state()
        lmp.record_feed_down()
        ofs._price_rows.pop(tk, None)
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)


def _drop_counts(chain):
    """The chain with open interest and volume absent."""
    dropped = []
    for ct in chain:
        row = dict(ct)
        row.pop("openInterest", None)
        row.pop("totalVolume", None)
        dropped.append(row)
    return dropped


def test_a_missing_count_after_the_close_is_not_the_last_count():
    """A count Schwab did not send is not a reported zero. It does not keep the last count."""

    held = SPY_0DTE
    tk = "SPY"
    after = datetime(2026, 10, 7, 18, 0, tzinfo=ET)
    expiry = str(held.chain[0]["expirationDate"])[:10]
    ofs._price_rows[tk] = {"ticker": tk, "spot": held.spot, "trade_ts": after.timestamp()}
    try:
        server._publish_levels(tk, [dict(c) for c in held.chain], after.timestamp(), chain_spot=(held.spot, None), now=after)
        first = server.confluence_payload(tk, expiry, after)
        assert any(row["pc_vol_text"] is not None for row in first["rows"])
        server._publish_levels(tk, _drop_counts(held.chain), after.timestamp(), chain_spot=(held.spot, None), now=after)
        second = server.confluence_payload(tk, expiry, after)
        assert all(row["pc_vol_text"] is None for row in second["rows"])
    finally:
        ofs._price_rows.pop(tk, None)
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)


def test_a_date_with_no_session_keeps_a_reported_zero():
    """A date Schwab has not answered is not outside an option window. A reported zero stays."""

    held = SPY_0DTE
    tk = "SPYNOSN"
    fresh = [dict(c) for c in held.chain]
    expiry = str(fresh[0]["expirationDate"])[:10]
    unknown = datetime(2026, 9, 29, 12, 0, tzinfo=ET)
    ofs._price_rows[tk] = {"ticker": tk, "spot": held.spot, "trade_ts": unknown.timestamp()}
    try:
        by_expiry: dict = {}
        for ct in fresh:
            by_expiry.setdefault(str(ct["expirationDate"])[:10], []).append(ct)
        for exp, cts in by_expiry.items():
            persist_complete_chain_capture(
                server.get_db().db_path, ticker=tk, expiry=exp,
                contracts=[dict(c) for c in cts], spot=held.spot,
                completeness_basis=CAPTURE_BASIS,
                ts_utc=datetime(2026, 10, 7, 16, 15, tzinfo=ET).timestamp())
        server._publish_levels(tk, _zero_counts(fresh), unknown.timestamp(), chain_spot=(held.spot, None), now=unknown)
        body = server.confluence_payload(tk, expiry, unknown)
        assert body["rows"]
        assert all(row["pc_vol_text"] is None for row in body["rows"])
    finally:
        ofs._price_rows.pop(tk, None)
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)


def test_a_newer_capture_is_the_count_the_next_chain_keeps():
    """The capture read before the open is not kept once a newer one is stored."""

    held = SPY_0DTE
    tk = "SPYNEW"
    fresh = [dict(c) for c in held.chain]
    target = next(ct for ct in fresh if ct.get("symbol") and isinstance(ct.get("totalVolume"), (int, float))
                  and ct["totalVolume"] > 0)
    bumped = []
    for ct in fresh:
        row = dict(ct)
        if row.get("symbol") == target["symbol"]:
            row["totalVolume"] = ct["totalVolume"] + 777
        bumped.append(row)
    before = datetime(2026, 10, 7, 8, 0, tzinfo=ET)
    session = datetime(2026, 10, 7, 12, 32, tzinfo=ET)
    after = datetime(2026, 10, 7, 18, 0, tzinfo=ET)
    ofs._price_rows[tk] = {"ticker": tk, "spot": held.spot, "trade_ts": before.timestamp()}

    def store(contracts, when):
        by_expiry: dict = {}
        for ct in contracts:
            by_expiry.setdefault(str(ct["expirationDate"])[:10], []).append(ct)
        for exp, cts in by_expiry.items():
            persist_complete_chain_capture(
                server.get_db().db_path, ticker=tk, expiry=exp,
                contracts=[dict(c) for c in cts], spot=held.spot,
                completeness_basis=CAPTURE_BASIS, ts_utc=when.timestamp())

    try:
        store(fresh, datetime(2026, 10, 6, 16, 0, tzinfo=ET))
        server._publish_levels(tk, _zero_counts(fresh), before.timestamp(), chain_spot=(held.spot, None), now=before)
        store(bumped, datetime(2026, 10, 7, 16, 15, tzinfo=ET))
        server._publish_levels(tk, _zero_counts(fresh), session.timestamp(), chain_spot=(held.spot, None), now=session)
        server._publish_levels(tk, _zero_counts(fresh), after.timestamp(), chain_spot=(held.spot, None), now=after)
        book = server.terrain_cache_get(tk, after.timestamp())
        kept = next(ct for ct in book["_priced_chain"] if ct.get("symbol") == target["symbol"])
        assert kept["totalVolume"] == target["totalVolume"] + 777
    finally:
        ofs._price_rows.pop(tk, None)
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)


def test_during_the_session_a_zero_count_replaces_the_old_count():
    """During the session a count of zero is the count. It does not keep the older one."""

    held = SPY_0DTE
    tk = "SPY"
    session = datetime(2026, 10, 7, 12, 32, tzinfo=ET)
    later = datetime(2026, 10, 7, 12, 40, tzinfo=ET)
    expiry = str(held.chain[0]["expirationDate"])[:10]
    ofs._price_rows[tk] = {"ticker": tk, "spot": held.spot, "trade_ts": session.timestamp()}
    try:
        server._publish_levels(tk, [dict(c) for c in held.chain], session.timestamp(), chain_spot=(held.spot, None), now=session)
        server._publish_levels(tk, _zero_counts(held.chain), later.timestamp(), chain_spot=(held.spot, None), now=later)
        body = server.confluence_payload(tk, expiry, later)
        near = min(body["rows"], key=lambda row: abs(row["strike"] - held.spot))
        assert near["score"] is None
        assert "no open interest and no volume" in near["missing"]
    finally:
        ofs._price_rows.pop(tk, None)
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)


def test_an_after_hours_print_keeps_the_close_book():
    """SPY's 2026-10-22 close capture (begun 16:17:04 ET, after the index close) is published at
    the price Schwab sent in it. SPY's after-hours print at 18:00 ET (LAST_PRICE as the daemon
    received it), with no new chain, reprices nothing: the strike's gamma, vanna and charm and the
    publication's price stay the close's."""
    held, print_ = SPY_CLOSE, SPY_AFTER_HOURS_PRINT
    tk = "SPY"
    at = datetime.fromtimestamp(print_["ts_recv"], ET)
    expiry = str(held.chain[0]["expirationDate"])[:10]
    try:
        server._publish_levels(tk, captures=[{"contracts": [dict(c) for c in held.chain],
                                              "ts_utc": held.now.timestamp(), "spot": held.spot,
                                              "et_date": held.now.date().isoformat(),
                                              "basis": CAPTURE_BASIS, "spot_ts": None}], now=held.now)
        first = server.confluence_payload(tk, expiry, held.now)
        near = min(first["rows"], key=lambda row: abs(row["strike"] - held.spot))
        close_texts = (near["net_gex_text"], near["vanna_text"], near["charm_text"])
        assert None not in close_texts
        lmp.record_from_level_one_equity(tk, print_["native"], received_ts=print_["ts_recv"])
        lmp.record_feed_heartbeat({"ts": at.timestamp(), "schwab_socket_open": True,
                                   "held": {"LEVELONE_EQUITIES": [tk]}})
        ofs._price_rows[tk] = live_price_rows.price_row(tk, at.timestamp())
        second_snap = server._publish_levels(tk, now=at)
        second = server.confluence_payload(tk, expiry, at)
        again = min(second["rows"], key=lambda row: abs(row["strike"] - held.spot))
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)
        ofs._price_rows.pop(tk, None)
        lmp._by_ticker.pop(tk, None)
        lmp._fields_by_ticker.pop(tk, None)
        lmp.record_feed_heartbeat({"ts": at.timestamp(), "schwab_socket_open": True, "held": {}})
        lmp.record_feed_down()
    assert print_["native"]["LAST_PRICE"] != held.spot
    assert (again["net_gex_text"], again["vanna_text"], again["charm_text"]) == close_texts
    assert second_snap.spot == held.spot and second["priced_at_spot"] == held.spot
    assert second["spot"] == print_["native"]["LAST_PRICE"]


def test_a_close_capture_keeps_its_charm_in_the_forces():
    """SPY's captured 0DTE chain, banked after the index close, is valued at that close.
    The forces charm sums include it."""

    held = SPY_0DTE
    after = datetime(2026, 10, 7, 18, 0, tzinfo=ET)
    prior = datetime(2026, 10, 6, 12, 0, tzinfo=ET)
    caps = [
        {"et_date": "2026-10-07", "spot": held.spot, "contracts": held.chain,
         "ts_utc": after.timestamp()},
        {"et_date": "2026-10-06", "spot": held.spot, "contracts": held.chain,
         "ts_utc": prior.timestamp()},
    ]
    forces = server._forces_from_captures("SPY", caps)
    assert forces["charm_below"] is not None
    assert forces["charm_above"] is not None


def test_the_forces_read_the_charm_map_of_the_capture_just_priced():
    """The side sums are the charm map priced with that capture. SPY's captured chain,
    valued at the index close, sums to the same charm either way. The same chain's charm valued
    at its own capture instant, 12:32 ET, is a different map, and the sums are that map's."""

    held = SPY_0DTE
    after = datetime(2026, 10, 7, 18, 0, tzinfo=ET)
    prior = datetime(2026, 10, 6, 12, 0, tzinfo=ET)
    valued = valuation_instant(after, INDEX_OPTIONS)
    snap = compute_terrain("SPY", held.chain, held.spot, now=valued)
    caps = [
        {"et_date": "2026-10-07", "spot": held.spot, "contracts": held.chain,
         "ts_utc": after.timestamp()},
        {"et_date": "2026-10-06", "spot": held.spot, "contracts": held.chain,
         "ts_utc": prior.timestamp()},
    ]
    fresh = server._forces_from_captures("SPY", caps)
    from_book = server._forces_from_captures("SPY", caps, snap.charm_by_strike)
    assert from_book["charm_below"] == fresh["charm_below"]
    assert from_book["charm_above"] == fresh["charm_above"]
    midday = compute_charm_by_strike(held.chain, held.spot, now=held.now, product=INDEX_OPTIONS)
    read = server._forces_from_captures("SPY", caps, midday)
    below = sum(v["net_charm"] for k, v in midday.items() if k < held.spot and v.get("net_charm") is not None)
    above = sum(v["net_charm"] for k, v in midday.items() if k > held.spot and v.get("net_charm") is not None)
    assert (below, above) != (fresh["charm_below"], fresh["charm_above"])
    assert (read["charm_below"], read["charm_above"]) == (below, above)


def test_a_chain_whose_every_expiry_has_passed_says_so():
    """SPY's 2026-10-22 close capture holds only that day's expiry. On Sunday 2026-10-25 the
    matrix says no expiry on the chain is still open."""
    sunday = datetime(2026, 10, 25, 12, 0, tzinfo=ET)
    try:
        _publish_close()
        body = server.confluence_payload("SPY", None, sunday)
    finally:
        server._terrain_cache.pop("SPY", None)
    assert body["available"] is False
    assert body["reason"] == "no expiry on this chain is still open"


def test_the_matrix_shows_the_live_price_and_the_one_day_move_levels_serves():
    """CRWD's captured chain (2026-10-16 expiry, captured 2026-10-07 10:38:40 ET), published at the
    price Schwab sent in that chain answer (its stored capture's spot, 269.04), and CRWD's
    LEVELONE_EQUITIES message the daemon received at 10:38:00 ET (LAST_PRICE 269.395), taken in by
    the plane and made the price row by the daemon's own function. The matrix stays ranked at the
    chain's price (priced_at_spot); its spot, its one-day move and each row's distance are the
    live price's, the move the same two prices /api/levels serves (server.expected_move)."""
    tk, at = server.ticker_storage_key(CRWD.ticker), CRWD.now
    live = _QUOTE["native"]["LAST_PRICE"]
    lmp.record_from_level_one_equity(tk, _QUOTE["native"], received_ts=_QUOTE["ts_recv"])
    lmp.record_feed_heartbeat({"ts": at.timestamp(), "schwab_socket_open": True,
                               "held": {"LEVELONE_EQUITIES": [tk]}})
    ofs._price_rows[tk] = live_price_rows.price_row(tk, at.timestamp())
    try:
        server._publish_levels(tk, captures=[{"contracts": CRWD.chain, "ts_utc": at.timestamp(),
                                              "spot": CRWD.spot, "et_date": at.date().isoformat(),
                                              "basis": server.CAPTURE_BASIS, "spot_ts": None}], now=at)
        body = server.confluence_payload(tk, str(CRWD.chain[0]["expirationDate"])[:10], at)
        levels = {r["id"]: r["price"] for r in server.levels_payload(tk, "1", at)["levels"]}
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)
        ofs._price_rows.pop(tk, None)
        lmp._by_ticker.pop(tk, None)
        lmp._fields_by_ticker.pop(tk, None)
        lmp.record_feed_heartbeat({"ts": at.timestamp(), "schwab_socket_open": True, "held": {}})
        lmp.record_feed_down()
    moves ={lv["abbrev"]: lv["price"] for lv in body["levels"] if lv["abbrev"] in ("EM+", "EM−")}
    assert (body["spot"], body["spot_text"], body["priced_at_spot"]) == (live, f"{live:.2f}", CRWD.spot)
    assert body["spot_time_ct"] == ct_label(_QUOTE["native"]["TRADE_TIME_MILLIS"] / 1000.0)
    assert moves == {"EM+": levels["em_up"], "EM−": levels["em_dn"]}
    assert all(abs(float(r["distance_text"]) - (r["strike"] - live)) <= 0.005 for r in body["rows"])
    assert [r["strike"] for r in body["rows"] if r["spot_line"]] == [min(
        r["strike"] for r in body["rows"] if r["strike"] >= live)]
    assert levels["em_up"] - live == live - levels["em_dn"] > 0
