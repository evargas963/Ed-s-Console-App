"""Numbers as the screen shows them, served (AGENTS.md rule 13, ENF-11).

The operator's formats (2026-11-16, "approved, go with your recommendation"): a count (shares,
contracts, open interest, volume) whole with thousands separators, so every unit it moves by
shows; dollars with "$", two decimals in thousands, millions and billions, whole below a
thousand; an estimate in delta-shares (vanna, charm) the same, with no "$"; implied volatility
two decimals; a negative with "-". One server formatter each (numeric_contract.count_text,
dollars_text, compact_text, iv_text); the page draws the text.

Real data: SPY's levels at a stopped price (2026-10-22) and the panels the browser tests draw
(tests/e2e/fixtures), made by the real producers. The expected text is worked here from the
operator's formats, apart from the formatters.
"""

from __future__ import annotations

import gzip
import json
import re
from pathlib import Path

from calc.terrain_engine import OPTION_LEVELS
from numeric_contract import compact_text, count_text, dollars_text, iv_text, strike_text

FX = Path(__file__).parent / "fixtures"
E2E = Path(__file__).parent / "e2e" / "fixtures"


def screen_text(value: float, kind: str) -> str:
    """Return a number as the operator's format for `kind` shows it, worked apart from the code.

    kind: "count" (whole, separators), "dollars" or "compact" (two decimals in K, M, B).
    """
    if kind == "count":
        return f"{round(value):,}"
    a, sign = abs(value), "-" if value < 0 else ""
    unit = next(((s, u) for s, u in ((1e9, "B"), (1e6, "M"), (1e3, "K")) if a >= s), None)
    digits = f"{a:.0f}" if unit is None else f"{a / unit[0]:.2f}{unit[1]}"
    return sign + ("$" if kind == "dollars" else "") + digits


def test_spys_net_gamma_and_contracts_are_served_by_the_operators_formats():
    terrain = json.loads(
        (FX / "real_spy_terrain_at_a_stopped_price_2026_10_22.json").read_text(encoding="utf-8")
    )
    assert terrain["net_gex_at_spot"] == -2718991225.452607
    assert terrain["net_gex_at_spot_text"] == "-$2.72B"
    assert (terrain["contracts_used"], terrain["contracts_used_text"]) == (292, "292")


def test_every_strike_row_of_both_tickers_carries_its_numbers_as_the_formats_make_them():
    for name in ("spy", "amzn"):
        panels = json.loads((E2E / f"panels_{name}_two_day.json").read_text(encoding="utf-8"))
        strikes = panels["strikes"]
        # every expiry's rows and one expiry's chosen
        rows = [r for key in ("strikes", "strikes_second_expiry") for r in panels[key]["today"]]
        assert rows, name
        for r in rows:
            gex, volume = r["value"], r["volume"]
            assert r["text"] == (None if gex is None else screen_text(gex, "dollars")), name
            assert r["volume_text"] == (None if volume is None else screen_text(volume, "count"))
        # the chart's DEX in dollars, its open interest a count
        for m, kind in (("dex", "dollars"), ("oi", "count")):
            for r in strikes["measures"][m]["rows"]:
                assert r["text"] == screen_text(r["value"], kind), (name, m)
    spy = json.loads((E2E / "panels_spy_two_day.json").read_text(encoding="utf-8"))["strikes"]
    assert spy["max_abs_row"] == {
        "strike": 775.0,
        "strike_text": "775",
        "value": 1503567229.88173,
        "volume": 9877.0,
        "text": "$1.50B",
        "volume_text": "9,877",
        "marks": [{"kind": "call", "label": "Call wall"}],  # SPY's call wall, 775
    }
    terrain = json.loads((E2E / "panels_spy_two_day.json").read_text(encoding="utf-8"))["terrain"]
    assert terrain["call_wall"] == spy["max_abs_row"]["strike"]
    first = spy["today"][0]
    assert first["text"] == "-$177.45M"
    # every contract shows: two decimals in thousands showed this as 65.58K
    assert (first["volume"], first["volume_text"]) == (65582.0, "65,582")
    for r in spy["migration"]["rows"]:
        change = r["change"]
        want = (
            None
            if change is None
            else ("▲" if change >= 0 else "▼") + screen_text(abs(change), "dollars")
        )
        assert r["change_text"] == want
        assert (change is None) == (r["value"] is None or r["prior"] is None)


def test_the_chains_counts_are_whole_and_its_iv_two_decimals():
    """The chain screens and Strike Detail draw each contract's served texts (AMZN).

    The open interest is the chain's, as Schwab sent it in the capture the panel was made of
    (_sent). The IV is the contract's quote's, or for a contract Schwab streams the one the sweep
    wrote on its row. The volume is the quote's or the stream's, so its text is read by its form.
    """
    chain = json.loads((E2E / "panels_amzn_two_day.json").read_text(encoding="utf-8"))["chain"]
    sides = [c for r in chain["ladder"] for c in (r["call"], r["put"]) if c is not None]
    assert sides
    sent = _sent("amzn")
    for c in sides:
        row = sent[c["symbol"]]
        assert c["oi_text"] == screen_text(row["openInterest"], "count")
        assert re.fullmatch(r"\d{1,3}(,\d{3})*", c["volume_text"]), c["volume_text"]
        assert c["iv_text"] == f"{(row.get('quote') or row)['volatility']:.2f}"


def test_vanna_and_charm_are_compact_with_no_dollar_sign():
    """Vanna and charm are delta-shares (per vol point, per day): estimates, never dollars."""
    panels = json.loads((E2E / "vanna_charm_panels_crwd.json").read_text(encoding="utf-8"))
    for kind in ("vanna", "charm"):
        rows = panels[kind]["rows"]
        assert rows, kind
        for r in rows:
            assert r["text"] == screen_text(r["value"], "compact"), kind


def test_the_books_sizes_are_served_whole():
    """SPY's real books (2026-10-22, offline): its top-5 totals and each level's size.

    Every size the order-flow screens draw is served (the page rounds none).
    """
    book = json.loads((E2E / "order_flow_book_offline_payload.json").read_text(encoding="utf-8"))
    five = book["depth"]["5"]
    assert (five["bid_total"], five["bid_total_text"]) == (800.0, "800")
    assert (five["ask_total"], five["ask_total_text"]) == (2160.0, "2,160")
    levels = book["depth_pressure"]["bid"] + book["depth_pressure"]["ask"]
    assert levels
    for row in levels:
        assert row["volume_text"] == screen_text(row["volume"], "count")


def price(value: float | None) -> str | None:
    """Return a price as the operator's format shows it, two decimals, worked apart from code."""
    return None if value is None else f"{value:.2f}"


def listed(value: float | None) -> str | None:
    """Return a strike as listed, to the cent with no trailing zeros, worked apart from the code."""
    return None if value is None else f"{value:.2f}".rstrip("0").rstrip(".")


def _panels(name: str) -> dict:
    return json.loads((E2E / f"panels_{name}_two_day.json").read_text(encoding="utf-8"))


def _sent(name: str) -> dict:
    """Schwab's contracts by symbol, as sent in the capture the ticker's panels were made of.

    real_<name>_two_day_captures_2026_11_12.json.gz, its second capture: each /chains row, with
    its /quotes answer (`quote`) unless Schwab streams the contract.
    """
    capture = json.loads(
        gzip.decompress((FX / f"real_{name}_two_day_captures_2026_11_12.json.gz").read_bytes())
    )["captures"][-1]
    return {c["symbol"]: c for row in capture["rows"] for c in row["contracts"]}


def test_every_price_the_levels_panels_draw_is_served_with_two_decimals():
    """SPY's and AMZN's levels: the spot, each level, each 0DTE pair, the POC and the zones."""
    for name in ("spy", "amzn"):
        p = _panels(name)
        for tf, lv in p["levels"].items():
            assert lv["spot_text"] == price(lv["spot"]), (name, tf)
            assert lv["levels"], (name, tf)
            for r in lv["levels"]:
                assert r["price_text"] == price(r["price"]), (name, tf, r["id"])
            for r in lv["zero_dte"]:
                assert (r["price_text"], r["carried_text"]) == (
                    price(r["price"]),
                    price(r["carried"]),
                )
            vp = lv["volume_profile"]
            # the profile's POC is the TODAY_POC level, drawn with its served label
            texts = {r["id"]: r["price_text"] for r in lv["levels"]}
            assert vp is None or texts["TODAY_POC"] == price(vp["poc"])
            assert vp is None or vp["poc_label"] == "POC est " + texts["TODAY_POC"]
            # the prior session's value area and the VWAP, in the words their switches show
            pva = lv["prior_value_area"]
            assert pva is None or pva["text"] == (f"VA {price(pva['low'])} – {price(pva['high'])}")
            assert lv["vwap_text"] == texts.get("VWAP")
        zones = p["liquidity"]["zones"]
        assert zones, name
        for z in zones:
            assert (z["zone_low_text"], z["zone_high_text"]) == (
                price(z["zone_low"]),
                price(z["zone_high"]),
            )
            for s in z["source_levels"]:
                assert s["value_text"] == price(s["value"])


def test_every_option_level_and_ratio_of_the_terrain_is_served():
    """SPY's and AMZN's terrain levels and ratios are served as text.

    Each option level, each on the 0DTE basis, and the put/call ratios (two decimals).
    """
    for name in ("spy", "amzn"):
        t = _panels(name)["terrain"]
        for level, _label in OPTION_LEVELS:
            assert t[f"{level}_text"] == price(t[level]), (name, level)
        assert t["same_day_text"] == {k: price(v) for k, v in t["same_day"].items()}
        assert t["pcr_all_text"] == price(t["pcr_all"])
        assert t["pcr_by_expiry_text"] == {k: price(v) for k, v in t["pcr_by_expiry"].items()}
    spy = _panels("spy")["terrain"]
    assert (spy["call_wall_text"], spy["gamma_flip_text"], spy["pcr_all_text"]) == (
        "775.00",
        "761.22",
        "1.83",
    )


def test_the_charts_bars_and_the_books_prices_are_served_with_two_decimals():
    """SPY's and AMZN's bars and book prices are served with two decimals.

    The bars at each timeframe, and each venue's top of book, mark, spread and levels; each
    depth's imbalance three decimals.
    """
    for name in ("spy", "amzn"):
        p = _panels(name)
        for tf, bars in p["bars"].items():
            assert bars["bars"], (name, tf)
            for b in bars["bars"]:
                assert [b[f"{k}_text"] for k in "ohlc"] == [price(b[k]) for k in "ohlc"]
        for venue, book in p["book"].items():
            tob = book["top_of_book"]
            assert (tob["bid_text"], tob["ask_text"]) == (price(tob["bid"]), price(tob["ask"]))
            for k in ("mark", "microprice", "spread_pts"):
                assert book[f"{k}_text"] == price(book[k]), (name, venue, k)
            for d in book["depth"].values():
                im = d["imbalance"]
                assert d["imbalance_text"] == (None if im is None else f"{im:.3f}")
            for r in book["depth_pressure"]["bid"] + book["depth_pressure"]["ask"]:
                assert r["price_text"] == price(r["price"])


def test_the_strikes_and_their_moves_are_served_as_listed():
    """SPY's chain ladder, per-strike rows, window centre and day-over-day level moves.

    The strikes that grew and traded most, as listed.
    """
    p = _panels("spy")
    sent = _sent("spy")
    quoted = 0
    for r in p["chain"]["ladder"]:
        assert r["strike_text"] == listed(r["strike"])
        for c in (r["call"], r["put"]):
            if c is None:
                continue
            # a quoted contract's bid and ask are its quote's; one Schwab streams shows the
            # stream's, which the capture does not hold: read by their form
            quote = sent[c["symbol"]].get("quote")
            shown = (c["bid_text"], c["ask_text"])
            if quote:
                quoted += 1
                assert shown == (price(quote["bidPrice"]), price(quote["askPrice"]))
            else:
                assert all(re.fullmatch(r"\d+\.\d\d", text) for text in shown), shown
    assert quoted == 200  # of the expiry's 258 contracts; Schwab streams the other 58
    assert p["chain"]["spot_text"] == price(p["chain"]["spot"])
    strikes = p["strikes"]
    # at All Expirations and at the expiry chosen
    for body in (strikes, p["strikes_second_expiry"]):
        for r in body["today"]:
            assert r["strike_text"] == listed(r["strike"])
        assert body["view"]["centre_text"] == listed(body["view"]["centre"])
        m = body["migration"]
        assert m["grew_text"] == "/".join(map(listed, m["grew"]))
        assert m["busiest_text"] == "–".join(map(listed, m["busiest"]))
    # SPY's walls and flip, 2026-11-11 to 2026-11-12: the call wall moved up 15, the put wall
    # stood, the flip rose 0.45
    assert [
        (v["prior_text"], v["today_text"], v["change_text"]) for v in strikes["level_moves"]
    ] == [
        ("760", "775", "+15"),
        ("760", "760", "unchanged"),
        ("760.77", "761.22", "+0.45"),
    ]


def test_the_heatmaps_strikes_are_served_as_listed():
    """SPY's heatmap (2026-10-22) serves each strike as listed.

    Each row's strike to the cent with no trailing zeros, and the window's centre the same.
    """
    surface = json.loads(
        (FX / "real_spy_gamma_surface_at_a_stopped_price_2026_10_22.json").read_text(
            encoding="utf-8"
        )
    )
    rows = surface["cells"]
    assert rows
    for row in rows:
        k = row["strike"]
        assert row["strike_text"] == (str(int(k)) if k == int(k) else f"{k:g}")
    centre = surface["view"]["centre"]
    assert surface["view"]["centre_text"] == (None if centre is None else f"{centre:g}")
    assert (strike_text(397.5), strike_text(400.0), strike_text(6812.25)) == (
        "397.5",
        "400",
        "6812.25",
    )


def test_a_count_shows_every_unit_it_moves_by():
    """Open interest or volume ticking up from 20,000: each step shows."""
    assert [count_text(v) for v in (20000, 20001, 20010, 20100)] == [
        "20,000",
        "20,001",
        "20,010",
        "20,100",
    ]
    assert (count_text(1234567.0), count_text(-1200)) == ("1,234,567", "-1,200")


def test_a_value_not_known_has_no_text_and_zero_is_a_value():
    assert (dollars_text(None), count_text(None), compact_text(None), iv_text(None)) == (
        None,
        None,
        None,
        None,
    )
    assert (dollars_text(0.0), count_text(0), compact_text(0), iv_text(0)) == (
        "$0",
        "0",
        "0",
        "0.00",
    )
