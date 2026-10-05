"""AGENTS.md rule 2 on the -999 Schwab actually sent: a -999 is not a number. Real chains
(tests/fixtures/real_chains_greeks_minus_999.json, captured read-only from complete_chain_captures)
through the reader every exposure is built from (math_exposure_core.compute_exposures_by_strike),
each valued at its own capture time. Schwab has sent -999 for Greeks and volatility, never for open
interest (no instance in any capture since 2026-09-28: the fixture's provenance note)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from math_exposure_core import bucket_metric, compute_exposures_by_strike
from numeric_contract import schwab_count, schwab_number
from time_et import ET

_FX = json.loads((Path(__file__).resolve().parent / "fixtures" / "real_chains_greeks_minus_999.json")
                 .read_text(encoding="utf-8"))
_ROWS = {r["ticker"]: r for r in _FX["rows"]}
_GREEKS = ("gamma", "delta", "volatility")


def _books(row):
    return compute_exposures_by_strike(row["chain"], spot=row["spot"],
                                       now=datetime.fromtimestamp(row["ts_utc"], ET))[0]


def _sent_minus_999(c) -> bool:
    return any(c[g] == -999 for g in _GREEKS)


@pytest.mark.parametrize("ticker", sorted(_ROWS))
def test_a_minus_999_schwab_sent_is_not_a_number(ticker):
    sent = [c[g] for c in _ROWS[ticker]["chain"] for g in _GREEKS if c[g] == -999]
    assert sent
    assert all(schwab_number(v) is None and schwab_count(v) is None for v in sent)


@pytest.mark.parametrize("ticker", sorted(_ROWS))
def test_open_interest_is_taken_as_sent_beside_minus_999_greeks(ticker):
    """Every strike's open interest per side is the sum of Schwab's openInterest as sent; a
    contract's -999 Greeks never make its open interest unreported."""
    row = _ROWS[ticker]
    books = _books(row)
    for k, b in books.items():
        assert b["oi_unreported"] == 0, k
        for side in ("CALL", "PUT"):
            ois = [c["openInterest"] for c in row["chain"] if c["strikePrice"] == k and c["putCall"] == side]
            assert b[f"{side.lower()}_oi"] == (float(sum(ois)) if ois else None), (k, side)


@pytest.mark.parametrize("ticker", sorted(_ROWS))
def test_a_leg_with_minus_999_on_open_interest_has_no_gamma_and_otherwise_its_sum(ticker):
    """A leg holding a contract with open interest whose gamma, delta or volatility Schwab sent as
    -999 has no gamma exposure (absent, never 0); a -999 contract with open interest 0 adds a known
    0; every other leg's gamma exposure is the sum of gamma x openInterest x multiplier as sent."""
    row = _ROWS[ticker]
    books = _books(row)
    seen = {"absent": 0, "known_beside_minus_999": 0}
    for k, b in books.items():
        for side in ("CALL", "PUT"):
            leg = [c for c in row["chain"] if c["strikePrice"] == k and c["putCall"] == side]
            if not leg:
                continue
            got = bucket_metric(b, f"{side.lower()}_gamma")
            if any(_sent_minus_999(c) and c["openInterest"] > 0 for c in leg):
                assert got is None, (k, side)
                seen["absent"] += 1
                continue
            want = sum(c["gamma"] * c["openInterest"] * c["multiplier"] for c in leg if not _sent_minus_999(c))
            assert got == pytest.approx(want, rel=1e-12, abs=1e-12), (k, side)
            seen["known_beside_minus_999"] += any(_sent_minus_999(c) for c in leg)
    # the capture exercises its case: TSLA's -999s all sit on open interest 0, CIFR's on open interest
    assert seen["known_beside_minus_999"] if ticker == "TSLA" else seen["absent"], seen
