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
