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

import json
from pathlib import Path

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
    # no one-day move at that stopped price: no ATM IV text
    assert terrain["implied_1d_move"] is None and terrain["atm_iv_text"] is None


def test_the_atm_iv_is_served_with_two_decimals():
    """AMZN's levels the browser tests draw: the front expiry's ATM IV, 40.31862554, as 40.32."""
    terrain = json.loads((E2E / "panels_amzn_two_day.json").read_text(encoding="utf-8"))["terrain"]
    assert terrain["implied_1d_move"]["iv_pct_atm"] == 40.31862554
    assert terrain["atm_iv_text"] == "40.32"


def test_every_strike_row_of_both_tickers_carries_its_numbers_as_the_formats_make_them():
    for name in ("spy", "amzn"):
        strikes = json.loads((E2E / f"panels_{name}_two_day.json").read_text(encoding="utf-8"))[
            "strikes"
        ]
        rows = [r for sc in ("all", "near", "far") for r in strikes["today"][sc]]
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
        "value": 1503567229.88173,
        "volume": 9877.0,
        "text": "$1.50B",
        "volume_text": "9,877",
    }
    first = spy["today"]["all"][0]
    assert first["text"] == "-$177.45M"
    # every contract shows: two decimals in thousands showed this as 65.58K
    assert (first["volume"], first["volume_text"]) == (65582.0, "65,582")
    for r in spy["migration"]["all"]["rows"]:
        change = r["change"]
        want = (
            None
            if change is None
            else ("▲" if change >= 0 else "▼") + screen_text(abs(change), "dollars")
        )
        assert r["change_text"] == want
        assert (change is None) == (r["value"] is None or r["prior"] is None)


def test_the_chains_counts_are_whole_and_its_iv_two_decimals():
    """The chain screens and Strike Detail draw each contract's served texts (AMZN)."""
    chain = json.loads((E2E / "panels_amzn_two_day.json").read_text(encoding="utf-8"))["chain"]
    sides = [c for r in chain["ladder"] for c in (r["call"], r["put"]) if c is not None]
    assert sides
    for c in sides:
        for key, text in (("openInterest", "oi_text"), ("totalVolume", "volume_text")):
            value = c.get(key)
            assert c[text] == (None if value is None else f"{round(value):,}"), key
        iv = c.get("volatility")
        assert c["iv_text"] == (None if iv is None else f"{iv:.2f}")


def test_vanna_and_charm_are_compact_with_no_dollar_sign():
    """Vanna and charm are delta-shares (per vol point, per day): estimates, never dollars."""
    panels = json.loads((E2E / "vanna_charm_panels_crwd.json").read_text(encoding="utf-8"))
    for kind in ("vanna", "charm"):
        rows = panels[kind]["rows"]
        assert rows, kind
        for r in rows:
            assert r["text"] == screen_text(r["value"], "compact"), kind


def test_the_books_sizes_are_served_whole():
    """SPY's real books (2026-10-22, offline): its top-5 totals, each level's and each wall's size.

    Every size the order-flow screens draw is served (the page rounds none).
    """
    book = json.loads((E2E / "order_flow_book_offline_payload.json").read_text(encoding="utf-8"))
    five = book["depth"]["5"]
    assert (five["bid_total"], five["bid_total_text"]) == (800.0, "800")
    assert (five["ask_total"], five["ask_total_text"]) == (2160.0, "2,160")
    levels = book["depth_pressure"]["bid"] + book["depth_pressure"]["ask"]
    walls = book["wall_candidates"]
    assert levels and walls
    for row in levels + walls:
        assert row["volume_text"] == screen_text(row["volume"], "count")


def test_the_heatmaps_strikes_are_served_as_listed():
    """SPY's heatmap (2026-10-22): each row's strike to the cent with no trailing zeros, and the
    window's centre the same."""
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
