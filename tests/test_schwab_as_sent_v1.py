"""AGENTS.md rule 2: a Schwab field as sent. Not a number: absent, -999, text, NaN or infinity, and
a negative volume, size or open interest. Everything else is taken as sent; a reported 0 is 0."""
import math

import pytest

from numeric_contract import schwab_count, schwab_number


@pytest.mark.parametrize("v", [None, -999, -999.0, "12.5", "", True, False, math.nan, math.inf, -math.inf, [1], {}])
def test_not_a_number(v):
    assert schwab_number(v) is None and schwab_count(v) is None


@pytest.mark.parametrize("v", [0, 0.0, -0.37, 12, 772.04, -998.99, 1e9])
def test_numbers_are_taken_as_sent(v):
    assert schwab_number(v) == float(v)


def test_counts_keep_zero_and_refuse_negatives():
    assert schwab_count(0) == 0.0 and schwab_count(1200) == 1200.0
    assert schwab_count(-1) is None


# ── Real captured data through the real readers ─────────────────────────────────────────────
import copy
import json
from pathlib import Path

_FX = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(autouse=True)
def _at_capture(pin_clock):
    """Valued at the CRWD chain's capture (2026-09-02)."""
    return pin_clock(2026, 9, 2, 12, 0)


def _load(name):
    return json.loads((_FX / name).read_text(encoding="utf-8"))


def test_a_reported_zero_open_interest_is_reported_not_missing():
    """Real CRWD chain: 122 of 218 contracts carry openInterest 0 -- reported, so no strike
    counts them as unreported."""
    from math_exposure_core import compute_exposures_by_strike
    fx = _load("real_crwd_complete_chain_quarter.json")
    assert sum(1 for c in fx["chain"] if c["openInterest"] == 0) == 122
    books, _ = compute_exposures_by_strike(fx["chain"], spot=fx["spot"])
    assert sum(b["oi_unreported"] for b in books.values()) == 0


def test_minus_999_open_interest_is_unreported():
    """Stand-in: no captured contract has carried -999 open interest (0 of 108 million captured
    messages, measured 2026-09-27), so one real CRWD contract has it set to -999."""
    from math_exposure_core import compute_exposures_by_strike
    fx = _load("real_crwd_complete_chain_quarter.json")
    chain = copy.deepcopy(fx["chain"])
    chain[0]["openInterest"] = -999
    books, _ = compute_exposures_by_strike(chain, spot=fx["spot"])
    assert books[chain[0]["strikePrice"]]["oi_unreported"] == 1


def test_a_strike_whose_open_interest_is_all_zero_shows_zero_not_absent():
    """Operator ruling 2026-09-27 (take what Schwab sends): a strike whose every contract reports
    openInterest 0 has OI 0 and exposure 0, not "—". Real CRWD chain."""
    from math_exposure_core import bucket_metric, compute_exposures_by_strike
    fx = _load("real_crwd_complete_chain_quarter.json")
    by_strike = {}
    for c in fx["chain"]:
        by_strike.setdefault(c["strikePrice"], []).append(c["openInterest"])
    all_zero = [k for k, ois in by_strike.items() if all(o == 0 for o in ois)]
    assert all_zero
    books, _ = compute_exposures_by_strike(fx["chain"], spot=fx["spot"])
    for k in all_zero:
        assert books[k]["call_oi"] in (0.0, None) and books[k]["put_oi"] in (0.0, None)
        for key in ("net_gex_1pct", "net_dex_dollars", "net_vanna"):
            assert bucket_metric(books[k], key) == 0.0, (k, key)
