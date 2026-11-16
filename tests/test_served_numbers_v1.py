"""Dollars and counts as the screen shows them, served (AGENTS.md rule 13, ENF-11).

The operator's rule (2026-11-16, "yes use two decimal points"): two decimals in thousands,
millions and billions, whole below a thousand; dollars with "$", a negative with "-". One server
formatter each (numeric_contract.dollars_text, count_text); the page draws the text.

Real data: SPY's levels at a stopped price (2026-10-22) and the two-day SPY and AMZN panels the
browser tests draw (tests/e2e/fixtures/panels_*_two_day.json), made by the real producers. The
expected text is worked here from the operator's rule, apart from the formatter.
"""

from __future__ import annotations

import json
from pathlib import Path

from numeric_contract import count_text, dollars_text

FX = Path(__file__).parent / "fixtures"
E2E = Path(__file__).parent / "e2e" / "fixtures"


def _rule(value: float, dollars: bool) -> str:
    a, sign = abs(value), "-" if value < 0 else ""
    unit = next(((s, u) for s, u in ((1e9, "B"), (1e6, "M"), (1e3, "K")) if a >= s), None)
    digits = f"{a:.0f}" if unit is None else f"{a / unit[0]:.2f}{unit[1]}"
    return sign + ("$" if dollars else "") + digits


def test_spys_net_gamma_and_contracts_are_served_by_the_operators_rule():
    terrain = json.loads(
        (FX / "real_spy_terrain_at_a_stopped_price_2026_10_22.json").read_text(encoding="utf-8")
    )
    assert terrain["net_gex_at_spot"] == -2718991225.452607
    assert terrain["net_gex_at_spot_text"] == "-$2.72B"
    assert (terrain["contracts_used"], terrain["contracts_used_text"]) == (292, "292")


def test_every_strike_row_of_both_tickers_carries_its_numbers_as_the_rule_makes_them():
    for name in ("spy", "amzn"):
        strikes = json.loads((E2E / f"panels_{name}_two_day.json").read_text(encoding="utf-8"))[
            "strikes"
        ]
        rows = [r for sc in ("all", "near", "far") for r in strikes["today"][sc]]
        assert rows, name
        for _k, gex, volume, gex_text, volume_text in rows:
            assert gex_text == (None if gex is None else _rule(gex, dollars=True)), name
            assert volume_text == (None if volume is None else _rule(volume, dollars=False))
    spy = json.loads((E2E / "panels_spy_two_day.json").read_text(encoding="utf-8"))["strikes"]
    assert spy["max_abs_row"] == [775.0, 1503567229.88173, 9877.0, "$1.50B", "9.88K"]
    assert spy["today"]["all"][0][3:] == ["-$177.45M", "65.58K"]
    for _k, today, prior, change, change_text in spy["migration"]["all"]["rows"]:
        want = None if change is None else ("▲" if change >= 0 else "▼") + _rule(abs(change), True)
        assert change_text == want and (change is None) == (today is None or prior is None)


def test_a_value_not_known_has_no_text_and_zero_is_a_value():
    assert (dollars_text(None), count_text(None)) == (None, None)
    assert (dollars_text(0.0), count_text(0)) == ("$0", "0")
