"""DFR-017 repo-wide: every chain multiplier consumer fails closed (no silent 100)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Production modules that read Schwab chain ``multiplier``.




def test_compute_exposures_skips_missing_multiplier():
    from math_exposure_core import compute_exposures_by_strike

    # institutional-synthetic-ok: fail-closed test omits multiplier to prove the contract is skipped.
    ct = {
        "strikePrice": 500.0,
        "putCall": "CALL",
        "openInterest": 10,
        "delta": 0.5,
        "gamma": 0.1,
    }
    exposures, diag = compute_exposures_by_strike([ct], spot=500.0)
    assert exposures == {}
    assert diag.contracts_used == 0
