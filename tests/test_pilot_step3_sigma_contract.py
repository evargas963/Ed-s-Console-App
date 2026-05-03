"""CUSUM sigma contract: continuous EWM + causal relative floor (prereg-driven)."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np

_ET = ZoneInfo("America/New_York")


def test_prereg_v1_content_hash_validates():
    from research.pilot_step3 import pilot_config

    prereg = pilot_config.load_prereg()
    assert prereg["candidate_generator"]["sigma_contract"]["contract_id"] == "CONTINUOUS_EWM_REL_FLOOR_V1"


def test_build_sigma_strictly_causal():
    from research.pilot_step3.event_generation import build_sigma_for_cusum

    np.random.seed(42)
    n = 80
    t0 = datetime(2024, 8, 1, 12, 0, tzinfo=_ET).timestamp()
    starts = np.array([t0 + i * 60.0 for i in range(n)], dtype=float)
    closes = 100.0 + np.cumsum(np.random.randn(n) * 0.02)
    cg = {
        "ewm_span_bars": 15,
        "sigma_contract": {
            "ewm_span_bars": 15,
            "relative_floor": {"enabled": True, "M": 25, "phi": 0.3},
        },
    }
    s0 = build_sigma_for_cusum(closes, starts, cg)
    closes2 = closes.copy()
    closes2[35:] += 5.0
    s1 = build_sigma_for_cusum(closes2, starts, cg)
    # Index 35+ depends on rets[35] (uses close[35]); indices <35 depend only on closes[:35].
    np.testing.assert_allclose(s0[:35], s1[:35], rtol=0, atol=1e-12)


def test_session_open_sigma_comparable_no_z_spike_synthetic():
    """σ at first bar of second ET session is not ~1e-8; |z| stays bounded on mild tape."""
    from research.pilot_step3.data_loader import Bar1m
    from research.pilot_step3.event_generation import build_sigma_for_cusum

    bars: list[Bar1m] = []
    d1 = datetime(2024, 9, 3, 11, 0, tzinfo=_ET)
    for i in range(50):
        c = 500.0 + 0.01 * np.sin(i / 5.0)
        ts = (d1 + timedelta(minutes=i)).timestamp()
        bars.append(Bar1m(ts, ts + 60.0, c, c + 0.05, c - 0.05, c, 1.0))
    d2 = datetime(2024, 9, 4, 11, 0, tzinfo=_ET)
    for i in range(50):
        c = 500.0 + 0.01 * np.sin((50 + i) / 5.0)
        ts = (d2 + timedelta(minutes=i)).timestamp()
        bars.append(Bar1m(ts, ts + 60.0, c, c + 0.05, c - 0.05, c, 1.0))

    closes = np.array([b.close for b in bars], dtype=float)
    starts = np.array([b.bar_start_ts_utc for b in bars], dtype=float)
    cg = {
        "ewm_span_bars": 20,
        "sigma_contract": {
            "ewm_span_bars": 20,
            "relative_floor": {"enabled": True, "M": 40, "phi": 0.25},
        },
    }
    sigma = build_sigma_for_cusum(closes, starts, cg)
    idx = 50
    assert sigma[idx] > 1e-7, sigma[idx]
    assert sigma[idx] / max(sigma[idx - 1], 1e-12) < 100.0

    zmax = 0.0
    for i in range(1, len(bars)):
        sig = sigma[i]
        if not np.isfinite(sig) or sig <= 0:
            continue
        r = (closes[i] - closes[i - 1]) / max(closes[i - 1], 1e-12)
        z = r / sig
        zmax = max(zmax, abs(z))
    assert zmax < 100.0, zmax


def test_no_fixed_clock_z_explosion_on_staging_if_db_present():
    """Regression: |z|>100 should not all pile on minute 570 (requires local DB)."""
    from pathlib import Path

    from research.pilot_step3 import pilot_config
    from research.pilot_step3.data_loader import load_spy_1m_bars
    from research.pilot_step3.event_generation import (
        _et_minute_of_day_from_start,
        build_sigma_for_cusum,
    )

    try:
        from db import DB_PATH
    except Exception:
        DB_PATH = None  # type: ignore[misc, assignment]
    db = DB_PATH
    if not db or not Path(str(db)).is_file():
        return
    prereg = pilot_config.load_prereg()
    rep = load_spy_1m_bars(
        str(db),
        ticker=prereg["instrument"]["ticker"],
        source_table="price_bars_1m_staging",
        batch_id="spy_staging_pilot_30d_v1",
    )
    if rep.n_rth_rows < 1000:
        return
    closes = np.array([b.close for b in rep.bars], dtype=float)
    starts = np.array([b.bar_start_ts_utc for b in rep.bars], dtype=float)
    sigma = build_sigma_for_cusum(closes, starts, prereg["candidate_generator"])
    z_gt_100_mods: list[int] = []
    for i in range(1, len(rep.bars)):
        sig = sigma[i]
        if not np.isfinite(sig) or sig <= 0:
            continue
        r = (closes[i] - closes[i - 1]) / max(closes[i - 1], 1e-12)
        z = r / sig
        if abs(z) > 100:
            z_gt_100_mods.append(_et_minute_of_day_from_start(starts[i]))
    if not z_gt_100_mods:
        return
    frac_570 = sum(1 for m in z_gt_100_mods if m == 570) / len(z_gt_100_mods)
    assert frac_570 < 0.95, f"minute-570 concentration {frac_570:.2%}"
