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
    with_decimal_rv = blend_garch_sigma(garch, iv=0.20, realized_vol=0.0615, spot=500.0)[0]
    with_percent_rv = blend_garch_sigma(garch, iv=0.20, realized_vol=6.15, spot=500.0)[0]
    assert with_percent_rv > with_decimal_rv * 5


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
    rv_legacy_default = compute_realized_vol(closes)  # legacy 5m default factor
    assert rv_1m is not None and rv_legacy_default is not None
    assert rv_1m == pytest.approx(rv_legacy_default * math.sqrt(5.0), rel=0.01)
    assert rv_1m > rv_legacy_default  # the corrected 1m value is strictly larger


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
