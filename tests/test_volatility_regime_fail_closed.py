"""volatility_regime classification guards and threshold wiring."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from tests.mvp_test_fixtures import minimal_mvp_features
from volatility_regime import (
    VOL_COMPRESSION,
    VOL_REGIME_THRESHOLDS,
    VolRegimePayload,
    VolRegimeThresholds,
    _garch_trend,
    normalize_vol_decimal,
    vol_percent_to_decimal,
    schwab_iv_percent_to_decimal,
    classify_volatility_regime,
)


def _inp(**kwargs):
    base = dict(
        realized_vol=0.15,
        atr=1.0,
        iv_level=0.20,
        iv_direction="expanding",
        vix_level=22.0,
        vix_vs_prev=0.5,
        garch_sigma_bars=[0.2, 0.21, 0.22, 0.23, 0.24, 0.25],
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_normalize_vol_decimal_warns_above_heuristic(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    out = normalize_vol_decimal(18.0, field="iv_level")
    assert out == pytest.approx(0.18)
    assert any("percentage" in r.message.lower() for r in caplog.records)


def test_schwab_iv_percent_to_decimal_silent(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    assert vol_percent_to_decimal(18.52987037055019) == pytest.approx(0.1852987037055019)
    assert vol_percent_to_decimal(0.20) == pytest.approx(0.20)
    assert vol_percent_to_decimal(6.15) == pytest.approx(0.0615)
    assert vol_percent_to_decimal(None) is None
    assert schwab_iv_percent_to_decimal(18.0) == pytest.approx(0.18)
    assert not caplog.records


def test_classify_volatility_regime_no_warn_on_decimal_iv_rv(caplog: pytest.LogCaptureFixture) -> None:
    """Production path: market_state stamps decimal; classify must not re-normalize."""
    caplog.set_level(logging.WARNING)
    out = classify_volatility_regime(
        _inp(iv_level=0.186, realized_vol=0.061),
        mvp_features=minimal_mvp_features(zone="pin_bull"),
    )
    assert out.vol_regime in ("compression", "expansion", "unstable", "unknown")
    assert not any("percentage" in r.message.lower() for r in caplog.records)


def test_blend_garch_sigma_realized_vol_must_be_decimal() -> None:
    """Server passes vol_percent_to_decimal(realized_vol) before blend — percent inflates RV bar."""
    from math_volatility import blend_garch_sigma

    garch = [0.001]
    with_decimal_rv = blend_garch_sigma(
        garch, iv=0.20, realized_vol=0.0615, spot=500.0, bar_minutes=1.0)[0]
    with_percent_rv = blend_garch_sigma(
        garch, iv=0.20, realized_vol=6.15, spot=500.0, bar_minutes=1.0)[0]
    assert with_percent_rv > with_decimal_rv * 5


def test_blend_garch_sigma_bar_interval_must_be_stated_and_is_honoured() -> None:
    """RC-334 unit contract: the de-annualization interval is the caller's to state.

    `bar_minutes` was hardcoded to 5.0 while the only production caller supplies
    one-minute closes, so the IV and RV terms — 40% of the blend — entered sqrt(5) too
    large and Monte Carlo consumed the result directly as per-minute sigma. Measured
    overstatement on a realistic SPY input: 1.3981x.
    """
    import math

    import pytest as _pytest

    from math_volatility import (
        GARCH_BLEND_GARCH,
        GARCH_BLEND_IV,
        GARCH_BLEND_RV,
        TRADING_DAYS_PER_YEAR,
        TRADING_HOURS_PER_DAY,
        blend_garch_sigma,
    )

    # 1. The interval cannot be omitted, and cannot be nonsense.
    with _pytest.raises(TypeError):
        blend_garch_sigma([0.001], iv=0.2, realized_vol=0.1, spot=500.0)
    with _pytest.raises(ValueError):
        blend_garch_sigma([0.001], iv=0.2, realized_vol=0.1, spot=500.0, bar_minutes=0)

    # 2. It is actually USED: the IV/RV terms must scale as sqrt(bar_minutes).
    mpy = TRADING_DAYS_PER_YEAR * TRADING_HOURS_PER_DAY * 60
    g = 0.20 / math.sqrt(mpy)
    iv, rv = 0.15, 0.13
    got = blend_garch_sigma([g], iv, rv, 500.0, bar_minutes=1.0)[0]
    sq1 = math.sqrt(1.0 / mpy)
    want = max(GARCH_BLEND_GARCH * g + GARCH_BLEND_IV * (iv * sq1) + GARCH_BLEND_RV * (rv * sq1),
               (rv * sq1) * 0.5)
    # blend_garch_sigma rounds its output to 8 decimals, so the tolerance must sit above
    # that rounding rather than below it; the error this guards against is sqrt(5) = 2.24x.
    assert got == _pytest.approx(want, rel=1e-6), (
        f"one-minute blend is {got}, expected {want} — the stated interval is not honoured")

    five = blend_garch_sigma([g], iv, rv, 500.0, bar_minutes=5.0)[0]
    assert five > got, "a longer bar must not produce a smaller per-bar sigma"

    # 3. The production chain agrees end to end: server builds these on 1-minute closes and
    #    Monte Carlo consumes them at BAR_MINUTES, so the two constants must match.
    import monte_carlo

    assert float(monte_carlo.BAR_MINUTES) == 1.0, (
        "monte_carlo.BAR_MINUTES moved away from the 1-minute closes server.py feeds GARCH; "
        "the GARCH sigmas would be per-minute under a different name (RC-334)")


def test_garch_trend_warns_on_non_float_entries(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    _garch_trend(["bad", 0.1, 0.2, 0.3, 0.4, 0.5], thresholds=VOL_REGIME_THRESHOLDS, context="test")
    assert any("skipped" in r.message for r in caplog.records)


def test_compression_via_thresholds() -> None:
    t = VolRegimeThresholds(compression_min_score=2, compression_vix_max=20.0)
    out = classify_volatility_regime(
        _inp(iv_direction="contracting", vix_level=14.0, realized_vol=0.10, iv_level=0.18),
        mvp_features=minimal_mvp_features(zone="pin_bull"),
        thresholds=t,
    )
    assert out.vol_regime == VOL_COMPRESSION


def test_vol_regime_payload_is_frozen() -> None:
    p = VolRegimePayload(
        vol_regime="unknown",
        breakout_bias=0.6,
        continuation_bias=0.6,
        reversal_bias=0.5,
        conviction_multiplier=0.95,
        risk_multiplier=1.05,
        trade_permissive=False,
        summary="x",
    )
    with pytest.raises(AttributeError):
        p.trade_permissive = True  # type: ignore[misc]


def test_unknown_default_not_trade_permissive() -> None:
    out = classify_volatility_regime(
        _inp(realized_vol=None, atr=None, iv_level=None, vix_level=None, garch_sigma_bars=None),
        mvp_features=minimal_mvp_features(zone="pin_bull"),
    )
    assert out.vol_regime == "unknown"
    assert out.trade_permissive is False


# ── FORMULA_P1A_REALIZED_VOL_ANNUALIZATION_FIX_V1 — timeframe-aware RV locks ──


def _rv_closes(n: int = 40) -> list[float]:
    # Deterministic alternating log-return series with nonzero variance.
    closes = [100.0]
    for i in range(1, n):
        closes.append(closes[-1] * (1.001 if i % 2 else 0.999))
    return closes


def _rv_per_bar_unrounded(closes: list[float]) -> float:
    import numpy as np

    prices = np.array(closes, dtype=np.float64)
    return float(np.std(np.diff(np.log(prices)), ddof=1))


def test_realized_vol_1m_annualizes_with_252x390():
    import math

    from math_volatility import compute_realized_vol

    closes = _rv_closes()
    expected = _rv_per_bar_unrounded(closes) * math.sqrt(252 * 390) * 100.0
    rv_1m = compute_realized_vol(closes, bar_minutes=1.0)
    assert rv_1m is not None
    assert rv_1m == pytest.approx(expected, rel=0.001)


def test_realized_vol_5m_preserves_252x78():
    import math

    from math_volatility import compute_realized_vol

    closes = _rv_closes()
    expected = _rv_per_bar_unrounded(closes) * math.sqrt(252 * 78) * 100.0
    rv_5m = compute_realized_vol(closes, bar_minutes=5.0)
    assert rv_5m is not None
    assert rv_5m == pytest.approx(expected, rel=0.001)


def test_realized_vol_sqrt5_underscale_regression_lock():
    """The old defect: 1m closes annualized with the 5m factor = sqrt(5) under-scale."""
    import math

    from math_volatility import compute_realized_vol

    closes = _rv_closes()
    rv_1m = compute_realized_vol(closes, bar_minutes=1.0)
    # RC-345 / F17: bar_minutes is now REQUIRED (the silent 5.0 default is gone); pass 5m
    # explicitly to keep exercising the 1m-vs-5m sqrt(5) relationship this lock guards.
    rv_5m = compute_realized_vol(closes, bar_minutes=5.0)
    assert rv_1m is not None and rv_5m is not None
    assert rv_1m == pytest.approx(rv_5m * math.sqrt(5.0), rel=0.01)
    assert rv_1m > rv_5m  # the corrected 1m value is strictly larger


def test_realized_vol_invalid_bar_minutes_fails_closed():
    from math_volatility import compute_realized_vol

    closes = _rv_closes()
    assert compute_realized_vol(closes, bar_minutes=0) is None
    assert compute_realized_vol(closes, bar_minutes=-1.0) is None


def test_server_realized_vol_call_site_passes_1m_interval():
    """Source lock: the 1m candle path must pass bar_minutes=1.0."""
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")
    assert "compute_realized_vol(_closes, bar_minutes=1.0)" in src
    assert "compute_realized_vol(_closes)\n" not in src


# ── VOL_INPUT_CONTRACT 1.0.0 (lane V1) — MSD-001 rapid-branch restoration ────


def test_rapid_vix_change_branch_fires_with_stamped_vix_vs_prev():
    """Pre-fix the live route stamped vix_vs_prev=None (market_state.py stamp),
    making this branch unreachable live. With the per-cycle vol context stamped,
    a governed |change| > rapid_vix_change_abs at vix > min_level fires it."""
    t = VOL_REGIME_THRESHOLDS
    inp = _inp(
        vix_level=t.rapid_vix_change_min_level + 6.0,   # 26.0 — below extreme_vix
        vix_vs_prev=t.rapid_vix_change_abs + 0.5,        # 3.5
        iv_direction="flat",
    )
    assert inp.vix_level < t.extreme_vix
    out = classify_volatility_regime(inp, mvp_features=minimal_mvp_features())
    assert out.vol_regime == "unstable"
    assert "rising fast" in out.summary.lower()


def test_rapid_vix_change_branch_never_fires_from_missing_change():
    """Missing change stays None and is never treated as a rapid move —
    absence is not directional evidence (contract missing-state rule)."""
    inp = _inp(vix_level=26.0, vix_vs_prev=None, iv_direction="flat")
    out = classify_volatility_regime(inp, mvp_features=minimal_mvp_features())
    assert "rising fast" not in out.summary.lower()
