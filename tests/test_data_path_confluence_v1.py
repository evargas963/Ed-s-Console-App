"""Schwab -> the confluence matrix. The score is the chain already priced, ranked once."""
from __future__ import annotations

from datetime import datetime

from confluence_composite import (
    build_matrix, magnitudes, place_markers, score_magnitudes, under_strike, window_strikes,
)
from math_levels import compute_charm_by_strike
from time_et import ET

import server


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


def test_the_matrix_reads_the_priced_book_and_leaves_flow_out():
    """A planted book is the one the matrix ranks. Flow and the change in gamma stay empty,
    and a today expiry's score cannot pass 72."""
    now = datetime(2026, 10, 16, 10, 0, tzinfo=ET)
    tk = "SPY"
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
    contract = {
        "strikePrice": 670.0, "putCall": "CALL", "openInterest": 10, "totalVolume": 3,
        "multiplier": 100, "volatility": 20.0, "expirationDate": "2026-10-16",
        "gamma": 0.01, "delta": 0.5,
    }
    server._terrain_cache[tk] = {
        "spot": 669.5, "computed_ts_utc": now.timestamp(),
        "_valued_ts_utc": now.timestamp(),
        "expiry_dte": {"2026-10-16": 0},
        "_books": {("2026-10-16", 0): ({670.0: bucket}, None)},
        "_priced_chain": [contract],
        "_charm_by_expiry": {"2026-10-16": compute_charm_by_strike([contract], 669.5, now=now)},
    }
    try:
        body = server.confluence_payload(tk, "2026-10-16", now)
    finally:
        server._terrain_cache.pop(tk, None)
    assert body["available"] is True
    assert body["preset"] == "0DTE"
    assert body["ceiling"] == 72
    assert body["weights_in_score"]["FLOWM"] == 0
    assert body["weights_in_score"]["DGEXM"] == 0
    row = body["rows"][0]
    assert row["strike"] == 670.0
    assert row["strike_text"] == "670.00"
    assert row["net_gex_text"] == "+18.00"
    assert row["distance_text"] == "+0.50"
    assert row["gross_text"] == "42.00"
    assert row["flow_text"] is None
    assert row["dgex_text"] is None
    assert body["expiries"][0]["label"] == "0DTE · 2026-10-16"
    assert row["heat_background"].startswith("background:")
    assert "9,166,67" in row["net_style"]


def test_charm_uses_the_book_valuation_time_and_a_zero_book_is_zero_charm():
    """A reprice values charm when the book was priced, not at the older chain stamp.
    Open interest of zero is no charm, not a missing charm."""
    chain_time = datetime(2026, 10, 16, 9, 45, tzinfo=ET)
    valued = datetime(2026, 10, 16, 15, 0, tzinfo=ET)
    tk = "SPY"
    bucket = {
        "dollarized": True, "oi_unreported": 0, "volume_unreported": 0,
        "call_oi": 0.0, "put_oi": 0.0, "call_volume": 4.0, "put_volume": 0.0,
        "call_gex_1pct": 30_000_000.0, "put_gex_1pct": 12_000_000.0, "net_gex_1pct": 18_000_000.0,
        "call_dex_dollars": 0.0, "put_dex_dollars": 0.0, "net_dex_dollars": 0.0,
        "call_vanna": 0.0, "put_vanna": 0.0, "net_vanna": 0.0,
        "call_gamma_unreported": 0, "put_gamma_unreported": 0,
        "call_delta_unreported": 0, "put_delta_unreported": 0,
        "call_vanna_unreported": 0, "put_vanna_unreported": 0,
    }
    contract = {
        "strikePrice": 670.0, "putCall": "CALL", "openInterest": 0, "totalVolume": 4,
        "multiplier": 100, "volatility": 20.0, "expirationDate": "2026-10-16T20:00:00",
        "gamma": 0.01, "delta": 0.5,
    }
    direct = compute_charm_by_strike([contract], 669.5, now=valued)
    assert 670.0 not in direct
    zero = magnitudes(bucket, None, 20.0, 669.5)
    assert zero["CHARMM"] == 0.0
    server._terrain_cache[tk] = {
        "spot": 669.5, "computed_ts_utc": chain_time.timestamp(),
        "_valued_ts_utc": valued.timestamp(),
        "expiry_dte": {"2026-10-16": 0},
        "_books": {("2026-10-16", 0): ({670.0: bucket}, None)},
        "_priced_chain": [contract],
        "call_wall": 669.0,
    }
    try:
        body = server.confluence_payload(tk, "2026-10-16", valued)
    finally:
        server._terrain_cache.pop(tk, None)
    row = body["rows"][0]
    assert row["charm_text"] == "0.00"
    assert row["score"] is not None
    assert row["markers"] == []
    walls = [level for level in body["levels"] if level["abbrev"] == "CW"]
    assert walls[0]["price"] == 669.0
    assert walls[0]["price_text"] == "669.00"
    assert walls[0]["lane"] == "options"


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
    assert [row["strike"] for row in on_spot["rows"] if row["spot_line"]] == [670.0]


def test_a_passed_expiry_is_not_the_one_the_matrix_opens_on():
    """Friday's chain still holds Friday's expiry. On Sunday the matrix opens on the next one."""
    friday = datetime(2026, 10, 16, 15, 15, tzinfo=ET)
    sunday = datetime(2026, 10, 18, 12, 0, tzinfo=ET)
    tk = "SPY"
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
    server._terrain_cache[tk] = {
        "spot": 669.5, "computed_ts_utc": friday.timestamp(),
        "_valued_ts_utc": friday.timestamp(),
        "expiry_dte": {"2026-10-16": 0, "2026-10-19": 3},
        "_books": {
            ("2026-10-16", 0): ({670.0: bucket}, None),
            ("2026-10-19", 3): ({670.0: bucket}, None),
        },
        "_priced_chain": [],
    }
    try:
        opened = server.confluence_payload(tk, None, sunday)
        asked = server.confluence_payload(tk, "2026-10-16", sunday)
        server._terrain_cache[tk]["_books"] = {("2026-10-19", 3): ({670.0: bucket}, None)}
        server._terrain_cache[tk]["expiry_dte"] = {"2026-10-19": 3}
        gone = server.confluence_payload(tk, "2026-10-16", sunday)
    finally:
        server._terrain_cache.pop(tk, None)
    assert opened["available"] is True
    assert opened["expiry"] == "2026-10-19"
    assert [e["expiry"] for e in opened["expiries"]] == ["2026-10-19"]
    assert asked["available"] is True
    assert asked["expiry"] == "2026-10-19"
    assert gone["available"] is True
    assert gone["expiry"] == "2026-10-19"


def test_the_matrix_reads_the_expiry_charm_map_and_does_not_rebuild_it():
    """Charm is the map the book stored for this expiry. A contract Schwab sent with no
    volatility cannot build one, so a number on the matrix is that stored map."""
    chain_time = datetime(2026, 10, 16, 9, 45, tzinfo=ET)
    valued = datetime(2026, 10, 16, 15, 0, tzinfo=ET)
    tk = "SPY"
    bucket = {
        "dollarized": True, "oi_unreported": 0, "volume_unreported": 0,
        "call_oi": 10.0, "put_oi": 0.0, "call_volume": 4.0, "put_volume": 0.0,
        "call_gex_1pct": 30_000_000.0, "put_gex_1pct": 12_000_000.0, "net_gex_1pct": 18_000_000.0,
        "call_dex_dollars": 0.0, "put_dex_dollars": 0.0, "net_dex_dollars": 0.0,
        "call_vanna": 0.0, "put_vanna": 0.0, "net_vanna": 0.0,
        "call_gamma_unreported": 0, "put_gamma_unreported": 0,
        "call_delta_unreported": 0, "put_delta_unreported": 0,
        "call_vanna_unreported": 0, "put_vanna_unreported": 0,
    }
    contract = {
        "strikePrice": 670.0, "putCall": "CALL", "openInterest": 10, "totalVolume": 4,
        "multiplier": 100, "expirationDate": "2026-10-16T20:00:00",
        "gamma": 0.01, "delta": 0.5,
    }
    server._terrain_cache[tk] = {
        "spot": 669.5, "computed_ts_utc": chain_time.timestamp(),
        "_valued_ts_utc": valued.timestamp(),
        "expiry_dte": {"2026-10-16": 0},
        "_books": {("2026-10-16", 0): ({670.0: bucket}, None)},
        "_priced_chain": [contract],
        "_charm_by_expiry": { "2026-10-16": {
            670.0: {"call_charm": 8000.0, "put_charm": 0.0, "net_charm": 8000.0}}},
    }
    try:
        body = server.confluence_payload(tk, "2026-10-16", valued)
    finally:
        server._terrain_cache.pop(tk, None)
    assert body["rows"][0]["charm_text"] == "+8.00"


def test_the_close_keeps_the_vanna_a_settled_clock_drops():
    """After the option close, the book is valued at the close, so the matrix still has
    vanna, charm, and a score. The same contracts priced past settlement have no time
    left, and those three are missing."""
    from confluence_composite import iv_by_strike
    from math_exposure_core import bucket_metric, compute_exposures_by_strike
    from time_et import valuation_instant

    at = datetime(2026, 10, 7, 18, 0, tzinfo=ET)
    valued = valuation_instant(at)
    contract = {
        "strikePrice": 670.0, "putCall": "CALL", "openInterest": 10, "totalVolume": 4,
        "multiplier": 100, "volatility": 20.0, "expirationDate": "2026-10-07",
        "gamma": 0.01, "delta": 0.5, "daysToExpiration": 0,
    }
    at_close, _diag = compute_exposures_by_strike([contract], spot=669.5, now=valued)
    after, _diag = compute_exposures_by_strike([contract], spot=669.5, now=at)
    assert bucket_metric(at_close[670.0], "net_vanna") is not None
    assert bucket_metric(after[670.0], "net_vanna") is None
    iv = iv_by_strike([contract])
    close_row = build_matrix(
        at_close, compute_charm_by_strike([contract], 669.5, now=valued), iv, 669.5, 0.0, [],
    )["rows"][0]
    late_row = build_matrix(
        after, compute_charm_by_strike([contract], 669.5, now=at), iv, 669.5, 0.0, [],
    )["rows"][0]
    assert close_row["vanna_text"] is not None
    assert close_row["charm_text"] is not None
    assert close_row["score"] is not None
    assert late_row["vanna_text"] is None
    assert late_row["charm_text"] is None
    assert late_row["score"] is None


def test_spy_keeps_vanna_until_the_index_close():
    """SPY, QQQ, and IWM settle at the index close. At 4:10 PM ET the equity-option
    close has passed and the index close has not, so their vanna still stands."""
    from math_exposure_core import bucket_metric, compute_exposures_by_strike
    from time_et import INDEX_OPTIONS, valuation_instant

    at = datetime(2026, 10, 7, 16, 10, tzinfo=ET)
    contract = {
        "strikePrice": 670.0, "putCall": "CALL", "openInterest": 10, "totalVolume": 4,
        "multiplier": 100, "volatility": 20.0, "expirationDate": "2026-10-07",
        "gamma": 0.01, "delta": 0.5, "daysToExpiration": 0,
    }
    valued = valuation_instant(at, INDEX_OPTIONS)
    book, _diag = compute_exposures_by_strike(
        [contract], spot=669.5, now=valued, product=INDEX_OPTIONS)
    equity, _diag = compute_exposures_by_strike([contract], spot=669.5, now=at)
    assert bucket_metric(book[670.0], "net_vanna") is not None
    assert bucket_metric(equity[670.0], "net_vanna") is None


def test_a_chain_delivered_after_the_close_still_fills_the_matrix():
    """The page reads the publication. A chain delivered after the close is valued at
    the close, so vanna, charm, and the score are on the matrix."""
    import app.options.order_flow.streaming as ofs

    tk = "META"
    at = datetime(2026, 10, 7, 18, 0, tzinfo=ET)
    contract = {
        "symbol": "META  261007C00670000",
        "strikePrice": 670.0, "putCall": "CALL", "openInterest": 10, "totalVolume": 4,
        "multiplier": 100, "volatility": 20.0, "expirationDate": "2026-10-07",
        "gamma": 0.01, "delta": 0.5, "daysToExpiration": 0,
    }
    ofs._price_rows[tk] = {"ticker": tk, "spot": 669.5, "trade_ts": at.timestamp()}
    try:
        snap = server._publish_levels(tk, [contract], at.timestamp(), now=at)
        body = server.confluence_payload(tk, "2026-10-07", at)
    finally:
        ofs._price_rows.pop(tk, None)
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)
    assert snap is not None
    assert body["available"] is True
    row = body["rows"][0]
    assert row["vanna_text"] is not None
    assert row["charm_text"] is not None
    assert row["score"] is not None


def test_a_chain_whose_every_expiry_has_passed_says_so():
    """Sunday, and the only expiry on the chain is Friday: the matrix says none is still open."""
    friday = datetime(2026, 10, 16, 15, 15, tzinfo=ET)
    sunday = datetime(2026, 10, 18, 12, 0, tzinfo=ET)
    tk = "SPY"
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
    server._terrain_cache[tk] = {
        "spot": 669.5, "computed_ts_utc": friday.timestamp(),
        "_valued_ts_utc": friday.timestamp(),
        "expiry_dte": {"2026-10-16": 0},
        "_books": {("2026-10-16", 0): ({670.0: bucket}, None)},
        "_priced_chain": [],
    }
    try:
        body = server.confluence_payload(tk, None, sunday)
    finally:
        server._terrain_cache.pop(tk, None)
    assert body["available"] is False
    assert body["reason"] == "no expiry on this chain is still open"
