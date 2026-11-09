"""compute_exposures_by_strike's contract multiplier must come from the real chain data.

Never a hardcoded/default multiplier -- a wrong default silently mis-scales every exposure
computed from that contract.

Real data: CRWD's 2026-10-16 expiry captured 2026-10-07 10:38:40 ET (tests/real_chains.py), its
first call (strike 45, open interest 8, Schwab's multiplier 100). Induced (named): a field taken
out of that real contract, as Schwab leaves a field out.
"""

from __future__ import annotations

from math_exposure_core import bucket_metric, compute_exposures_by_strike
from option_contract import read_chain
from tests.real_chains import CRWD

_SENT = CRWD.chain[0]
STRIKE = _SENT["strikePrice"]


def _contract(without: str | None = None) -> dict:
    ct = dict(_SENT)
    if without:
        del ct[without]
    return ct


def _exposures(ct: dict):
    return compute_exposures_by_strike(read_chain([ct]), spot=CRWD.spot, now=CRWD.now)


def test_exposures_use_schwab_multiplier_without_defaulting_to_100():
    assert _SENT["putCall"] == "CALL" and _SENT["openInterest"] > 0
    exposures, diag = _exposures(_contract())

    bucket = exposures[STRIKE]
    assert diag.contracts_used == 1
    assert bucket["call_oi_mult"] == _SENT["openInterest"] * _SENT["multiplier"]
    assert bucket["call_delta"] == _SENT["delta"] * _SENT["openInterest"] * _SENT["multiplier"]


def test_a_missing_multiplier_leaves_the_exposure_unknown_and_keeps_the_open_interest():
    """No silent 100: the contract's exposure is not known, its leg's sums are absent.

    Its open interest and volume, which Schwab sent, are kept (M-14: the contract used to be
    dropped).
    """
    exposures, diag = _exposures(_contract(without="multiplier"))

    bucket = exposures[STRIKE]
    assert diag.contracts_used == 0
    assert diag.greeks_missing == 1
    assert bucket["call_oi"] == _SENT["openInterest"]
    assert bucket["call_volume"] == _SENT["totalVolume"]
    for key in ("call_gex_1pct", "net_gex_1pct", "call_dex_dollars", "net_vanna", "call_oi_mult"):
        assert bucket_metric(bucket, key) is None, key


def test_exposures_preserve_missing_total_volume_instead_of_silent_zero():
    exposures, diag = _exposures(_contract(without="totalVolume"))

    assert diag.contracts_used == 1
    assert exposures[STRIKE]["call_volume"] is None


def test_exposures_preserve_missing_open_interest_instead_of_silent_zero():
    exposures, diag = _exposures(_contract(without="openInterest"))

    assert diag.contracts_used == 0
    assert exposures[STRIKE]["oi_unreported"] == 1
    assert exposures[STRIKE]["call_oi"] is None
    assert bucket_metric(exposures[STRIKE], "net_gex_1pct") is None
