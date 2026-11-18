"""The gamma flip reprices each contract with Schwab's own rate and dividend yield.

The flip is the price where the book's dealer gamma (+call / -put), each contract's gamma
recomputed at that price, changes sign (SqueezeMetrics, SpotGamma). Each contract's gamma there
is the Black-Scholes-Merton gamma (Hull, Options, Futures and Other Derivatives, ch. 19):
e^(-qT) * phi(d1) / (S * sigma * sqrt(T)), d1 = (ln(S/K) + (r - q + sigma^2 / 2) T) /
(sigma * sqrt(T)), with Schwab's volatility, and r and q the chain's interestRate
(docs/schwab/schwab_market_data_api_spec.pdf p. 27, OptionChain) and dividendYield as Schwab sent
them, percents. The expected flip is worked out here, independently of the program's curve: the
same sum on a grid ten times finer, each crossing found by bisection, the one nearest the
price. T is the program's one time to expiry (time_et.time_to_expiry_years), tested on its own.

Real chains: CRWD, TSLA, MRVL and SPY's same-day chain of 2026-10-07 and SPY's whole chain of
2026-11-09, each valued at its capture.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from calc.math_levels import contract_inputs
from calc.terrain_engine import compute_terrain
from option_contract import read_chain
from tests.real_chains import CRWD, MRVL, SPY_0DTE, SPY_FULL, TSLA, gamma_flip_worked_out
from time_et import ET, sessions
from tools import check_end_to_end as cee


@pytest.mark.parametrize(
    "book", [CRWD, TSLA, MRVL, SPY_0DTE, SPY_FULL], ids=lambda b: f"{b.ticker}-{b.now.date()}"
)
def test_the_flip_reprices_with_schwabs_rate_and_dividend_yield(book):
    snap = compute_terrain(
        book.ticker, read_chain(book.chain), book.spot, now=book.now, sessions=sessions()
    )
    expected = gamma_flip_worked_out(book)
    assert expected is not None
    # the program's curve is computed again between the two strikes it changes sign between:
    # its crossing is within a few hundred-thousandths of the price of the true one
    assert snap.gamma_flip == pytest.approx(expected, rel=5e-5)


def test_no_product_file_reads_the_stock_streams_dividend_yield():
    """The options are priced with the yield sent with their own chain, in every file.

    Schwab also pushes a Dividend Yield with the stock's quote (LEVELONE_EQUITIES field 23), a
    different field with a different value (operator 2026-11-12: the chain's own is the one
    source). No product file names the pushed one.
    """
    repo = Path(__file__).resolve().parent.parent
    # every product Python file the repository tracks, as check_end_to_end defines product
    files = subprocess.run(
        ["git", "ls-files", "*.py"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.split()
    product = [repo / f for f in files if cee.is_product(f)]
    assert len(product) > 40, "every product file is read"
    assert [p.name for p in product if "DIVIDEND_YIELD" in p.read_text(encoding="utf-8")] == []


def test_a_contract_schwab_sent_without_its_rate_is_not_priced():
    """SPY's same-day chain as captured 2026-09-22, before each contract carried the chain's rate.

    tests/fixtures/real_spy_0dte_chain.json carries no interestRate or dividendYield (the capture
    kept them from 2026-09-27): no contract is priced, they are counted "no_rate", and no flip is
    drawn. Nothing stands in for the rate Schwab's answer held but the capture did not keep.
    """
    held = json.loads(
        (Path(__file__).parent / "fixtures" / "real_spy_0dte_chain.json").read_text(
            encoding="utf-8"
        )
    )
    chain = read_chain(held["chain"])
    assert all(c.interest_rate is None and c.dividend_yield is None for c in chain)
    now = datetime.fromtimestamp(held["ts_utc"], ET)
    snap = compute_terrain("SPY", chain, float(held["spot"]), now=now, sessions=sessions())
    assert contract_inputs(chain, now, sessions=sessions())[1]["no_rate"] > 0
    assert snap.gamma_flip is None and snap.profile == []
