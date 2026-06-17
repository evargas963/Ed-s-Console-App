"""Layer 5 regime_mvp_context chunk-1: contract locks + FIND-MVP2 mvp_net_gamma coerce."""

from __future__ import annotations

import pytest

from features.regime_mvp_context import (
    RegimeMvpInputError,
    mvp_net_gamma,
    mvp_spot,
    require_mvp_features,
)


def test_require_mvp_features_raises_on_none():
    with pytest.raises(RegimeMvpInputError):
        require_mvp_features(None, context="test")


def test_require_mvp_features_raises_on_non_dict():
    with pytest.raises(RegimeMvpInputError):
        require_mvp_features("not a dict", context="test")


def test_require_mvp_features_passes_empty_dict():
    assert require_mvp_features({}, context="test") == {}


def test_mvp_spot_none_when_missing():
    assert mvp_spot({}) is None


def test_mvp_spot_none_when_value_none():
    assert mvp_spot({"price.spot": None}) is None


def test_mvp_spot_none_when_non_numeric():
    assert mvp_spot({"price.spot": "garbage"}) is None


def test_mvp_spot_none_when_non_positive():
    assert mvp_spot({"price.spot": -10}) is None
    assert mvp_spot({"price.spot": 0}) is None


def test_mvp_spot_valid_positive():
    assert mvp_spot({"price.spot": 450.0}) == 450.0


def test_mvp_net_gamma_none_when_missing():
    assert mvp_net_gamma({}) is None


def test_mvp_net_gamma_none_when_non_numeric():
    assert mvp_net_gamma({"structure.net_gamma": "garbage"}) is None


def test_mvp_net_gamma_valid_positive():
    assert mvp_net_gamma({"structure.net_gamma": 1000.0}) == 1000.0


def test_mvp_net_gamma_valid_negative():
    assert mvp_net_gamma({"structure.net_gamma": -500}) == -500.0
