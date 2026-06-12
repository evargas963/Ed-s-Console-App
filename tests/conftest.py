"""
Pytest: allow EdDB against temp paths (non-canonical) without per-call flags.

Production processes must NOT set ED_CONSOLE_ALLOW_NONCANONICAL_DB globally.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("ED_CONSOLE_ALLOW_NONCANONICAL_DB", "1")


@pytest.fixture(autouse=True)
def _no_fusion_temperature_calibration(monkeypatch):
    """Hermetic tests: never read the operator's live fusion calibration artifact.

    models/calibration/fusion_temperature.json is machine-fit operator state; with
    it present, every bundle-path test would change behavior by environment. Tests
    that exercise the serve hook monkeypatch _applied_fusion_temperatures themselves
    (their setattr runs after this fixture and wins).
    """
    import multi_horizon_ml_bundle as mhb

    monkeypatch.setattr(mhb, "_applied_fusion_temperatures", lambda: {})


@pytest.fixture(autouse=True)
def _equal_mh_pool_weights(monkeypatch):
    """Hermetic tests: never read the operator's live calibration DB for ALL-card
    pool weights. Equal weights = unweighted log opinion pool (the fail-closed
    default). Tests exercising skill weighting pass pool_weights explicitly or
    monkeypatch after this fixture (their setattr wins)."""
    import multi_horizon_decision as mhd

    monkeypatch.setattr(
        mhd,
        "_horizon_skill_weights_cached",
        lambda: ({h: 1.0 / len(mhd.PRODUCT_HORIZONS) for h in mhd.PRODUCT_HORIZONS}, True),
    )
