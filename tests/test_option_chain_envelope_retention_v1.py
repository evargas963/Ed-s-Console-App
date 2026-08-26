"""OPTIONS FLOW FOUNDATION — the chain ENVELOPE must survive the capture (2026-08-26).

WHAT WAS OBSERVED: Schwab returns 18 envelope keys on every /chains response alongside the two
expiry maps. The wide morning capture flattened the response to a contract LIST and the envelope
died with the local variable — so `interestRate` and `dividendYield` (the vendor's own r and q,
which math_levels.bs_gamma hardcodes to 0.0) and `isChainTruncated` (the vendor stating outright
that it cut the chain) were received on every fetch and thrown away before any persister saw them.
Verified at the time: `chain_json` decoded to a bare list of 2308 contracts, no envelope anywhere.

These tests pin the SEMANTICS the foundation depends on, not a schema shape:
  * NATIVE values pass through byte-exact — no derivation, no unit change, no defaulting;
  * ABSENCE stays legible — a key the vendor omitted must NOT come back as 0/None, because the
    whole point is being able to tell "vendor omitted r" from "vendor said r is zero";
  * the contract list is UNCHANGED, so every existing reader (load_wide_chains, the span and
    sign studies) sees exactly what it saw before.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from calibration.option_chain_morning_full import ENVELOPE_SCALAR_KEYS, envelope_scalars


def test_native_envelope_values_pass_through_byte_exact():
    """The vendor's r and q must arrive as the vendor sent them — this is the whole point."""
    resp = {
        "symbol": "SPY", "status": "SUCCESS", "interestRate": 4.283, "dividendYield": 1.1917,
        "volatility": 29.0, "underlyingPrice": 766.44, "numberOfContracts": 2660,
        "isChainTruncated": True, "isDelayed": False, "isIndex": False,
        "callExpDateMap": {"huge": "map"}, "putExpDateMap": {"huge": "map"},
    }
    out = envelope_scalars(resp)
    assert out["interestRate"] == 4.283, "vendor r must not be rounded, rescaled or defaulted"
    assert out["dividendYield"] == 1.1917, "vendor q must not be rounded, rescaled or defaulted"
    assert out["isChainTruncated"] is True, "the vendor's own truncation flag must survive verbatim"
    assert out["underlyingPrice"] == 766.44
    # the expiry MAPS must NOT be duplicated into the envelope — contracts already persist separately
    assert "callExpDateMap" not in out and "putExpDateMap" not in out


def test_absent_keys_stay_absent_rather_than_becoming_zero():
    """`r absent` and `r == 0` are different facts. Conflating them is the confusion this ends."""
    out = envelope_scalars({"symbol": "SPY", "status": "SUCCESS"})
    assert out is not None
    assert "interestRate" not in out, "an omitted key must not be materialised as 0/None"
    assert "dividendYield" not in out
    # and a response carrying none of the tracked keys yields None, not an empty dict masquerading
    assert envelope_scalars({"callExpDateMap": {}}) is None


def test_no_envelope_is_none_never_a_fabricated_row():
    """A caller with nothing to give writes NULL. Fabricating an envelope would invent vendor truth."""
    assert envelope_scalars(None) is None
    assert envelope_scalars("not a dict") is None
    assert envelope_scalars([]) is None


def test_the_two_load_bearing_keys_are_actually_tracked():
    """Guard against a future edit quietly dropping r/q from the projection: the unproven_register
    entry on r/q sensitivity depends on these being retained."""
    assert "interestRate" in ENVELOPE_SCALAR_KEYS
    assert "dividendYield" in ENVELOPE_SCALAR_KEYS
    assert "isChainTruncated" in ENVELOPE_SCALAR_KEYS


def test_projection_is_pure_and_does_not_mutate_the_response():
    resp = {"symbol": "SPY", "interestRate": 4.283}
    before = dict(resp)
    envelope_scalars(resp)
    assert resp == before, "projection must not mutate the vendor response it is handed"
