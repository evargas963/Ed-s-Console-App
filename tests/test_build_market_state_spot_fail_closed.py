"""build_market_state must not fabricate spot=0 or cross-instrument zero moves."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from market_state import build_market_state


def _mkt_ctx(**kwargs: object) -> MagicMock:
    ctx = MagicMock()
    ctx.spy_chg_pct = kwargs.get("spy_chg_pct")
    ctx.qqq_chg_pct = kwargs.get("qqq_chg_pct")
    ctx.iwm_chg_pct = kwargs.get("iwm_chg_pct")
    ctx.vix = None
    ctx.pcr = None
    ctx.pcr_arrow = ""
    ctx.pcr_color = ""
    ctx.pcr_label = ""
    ctx.vix_regime = ""
    ctx.vix_color = ""
    ctx.vix_implication = ""
    ctx.confluence = None
    ctx.qqq_confluence = None
    return ctx


def _base_kwargs(**overrides: object) -> dict:
    kw = {
        "ticker": "SPY",
        "selected_exp": "2026-06-20",
        "session_label": "RTH",
        "spot": 100.0,
        "bid": 99.9,
        "ask": 100.1,
        "consensus_summary": None,
        "contracts_use": [],
        "walls": [],
        "totals": [],
        "price_levels": MagicMock(vwap=None, today_open=None, today_high=None, today_low=None),
        "mkt_ctx": _mkt_ctx(),
        "live_on": True,
        "zone_since_bars": 0,
        "prev_zone": None,
    }
    kw.update(overrides)
    return kw


_COMPUTE_SIGNALS_CALLS: list = []


def _fake_compute_signals(sig_inp, db=None, pred_override=None):
    _COMPUTE_SIGNALS_CALLS.append(sig_inp)
    out = MagicMock()
    out.rules = None
    out.call = None
    out.fusion = None
    out.vol_regime = None
    out.stack_decision_path = None
    out.multi_horizon_bundle = None
    out.calibration_payload = None
    return out


@patch("signals.compute_signals", side_effect=_fake_compute_signals)
def test_build_market_state_returns_degraded_when_spot_none(_mock_cs):
    _COMPUTE_SIGNALS_CALLS.clear()
    ms = build_market_state(**_base_kwargs(spot=None))
    assert ms.spot is None
    assert "Spot unavailable" in ms.rules_headline
    assert "Spot unavailable" in ms.call_headline
    assert _COMPUTE_SIGNALS_CALLS == []


@patch("signals.compute_signals", side_effect=_fake_compute_signals)
def test_build_market_state_preserves_zero_net_gamma(_mock_cs):
    _COMPUTE_SIGNALS_CALLS.clear()
    consensus = MagicMock()
    consensus.bias_signal = "Neutral"
    consensus.pin_strength = "Very Low"
    consensus.net_gamma = 0.0
    consensus.net_delta = 0.0
    consensus.gex_magnitude = "negligible"
    consensus.dex_magnitude = "negligible"
    consensus.gamma_inflection = None
    consensus.delta_inflection = None

    build_market_state(**_base_kwargs(consensus_summary=consensus))
    assert len(_COMPUTE_SIGNALS_CALLS) == 1
    assert _COMPUTE_SIGNALS_CALLS[0].net_gamma == 0.0


@patch("signals.compute_signals", side_effect=_fake_compute_signals)
def test_build_market_state_propagates_none_spy_chg(_mock_cs):
    _COMPUTE_SIGNALS_CALLS.clear()
    build_market_state(
        **_base_kwargs(
            mkt_ctx=_mkt_ctx(spy_chg_pct=None, qqq_chg_pct=None, iwm_chg_pct=None),
        )
    )
    assert len(_COMPUTE_SIGNALS_CALLS) == 1
    assert _COMPUTE_SIGNALS_CALLS[0].qqq_vs_spy_delta is None
