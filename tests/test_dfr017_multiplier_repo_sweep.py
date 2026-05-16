"""DFR-017 repo-wide: every chain multiplier consumer fails closed (no silent 100)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Production modules that read Schwab chain ``multiplier``.
_MULTIPLIER_CONSUMER_FILES = (
    "math_exposure_core.py",
    "backfill_flow_imbalance.py",
    "debug_flow_snapshot.py",
    "v2_decision/post_trade_attribution.py",
)


def test_multiplier_consumers_have_no_or_100_default_in_source():
    """Regression: grep-class audit encoded as test (fails if synthetic 100 reappears)."""
    offenders: list[str] = []
    for rel in _MULTIPLIER_CONSUMER_FILES:
        text = (ROOT / rel).read_text(encoding="utf-8")
        if 'get("multiplier")' not in text and "get('multiplier')" not in text:
            continue
        for line in text.splitlines():
            if 'get("multiplier")' not in line and "get('multiplier')" not in line:
                continue
            if "or 100" in line or "* 100.0" in line or "default 100" in line.lower():
                offenders.append(f"{rel}: {line.strip()[:80]}")
                break
    assert offenders == [], f"DFR-017 violation in: {offenders}"


def test_compute_exposures_skips_missing_multiplier():
    from math_exposure_core import compute_exposures_by_strike

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
