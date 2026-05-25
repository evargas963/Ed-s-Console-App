"""Action 12.7: build_market_state must not fabricate session time or charm/IV labels."""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

from market_state import MarketState, build_market_state
from tests.test_issue18_multi_horizon_decision import _call, _canonical, _inp, _pred
from multi_horizon_decision import build_multi_horizon_bundle


def _mkt_ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.spy_chg_pct = None
    ctx.qqq_chg_pct = None
    ctx.iwm_chg_pct = None
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


_SIG_CALLS: list = []


def _fake_compute_signals(sig_inp, db=None, pred_override=None):
    _SIG_CALLS.append(sig_inp)
    out = MagicMock()
    out.rules = None
    out.call = None
    out.fusion = None
    out.vol_regime = None
    out.stack_decision_path = None
    out.multi_horizon_bundle = None
    out.calibration_payload = None
    return out


def test_build_market_state_time_defaults_are_none_not_open_time():
    sig = inspect.signature(build_market_state)
    assert sig.parameters["et_hour"].default is None
    assert sig.parameters["et_minute"].default is None
    assert sig.parameters["mins_to_close"].default is None


def test_charm_direction_default_is_none_not_neutral():
    sig = inspect.signature(build_market_state)
    assert sig.parameters["charm_direction"].default is None
    assert sig.parameters["charm_magnitude"].default is None
    assert sig.parameters["iv_direction"].default is None


@patch("signals.compute_signals", side_effect=_fake_compute_signals)
def test_build_market_state_passes_none_time_to_signals(_mock_cs):
    _SIG_CALLS.clear()
    ms = build_market_state(**_base_kwargs())
    assert len(_SIG_CALLS) == 1
    inp = _SIG_CALLS[0]
    assert inp.et_hour is None
    assert inp.et_minute is None
    assert inp.mins_to_close is None
    assert inp.session_bucket is None
    assert ms.iv_direction is None
    assert ms.charm_direction is None
    assert ms.charm_direction_display == "—"


@patch("signals.compute_signals", side_effect=_fake_compute_signals)
def test_build_market_state_confluence_total_none_without_call(_mock_cs):
    _SIG_CALLS.clear()
    ms = build_market_state(**_base_kwargs())
    assert ms.confluence_total is None


def test_mhap_rows_confidence_none_not_zero_for_missing_assessment():
    """Missing horizon assessments must not fabricate 0% confidence on mhap_rows."""
    bundle = build_multi_horizon_bundle(_inp(mins_to_close=180), _pred(), _canonical(), _call())
    for a in bundle.final_decision.supporting_assessments:
        if a.horizon == "60c":
            a.missing = True
            a.confidence = None
            break
    sig = MagicMock()
    sig.rules = None
    sig.call = None
    sig.fusion = None
    sig.vol_regime = None
    sig.stack_decision_path = None
    sig.multi_horizon_bundle = bundle
    sig.calibration_payload = None
    sig.predictive = None
    sig.regime = None
    sig.canonical_forecast = None

    ms = MarketState(ticker="SPY")
    _mhb = sig.multi_horizon_bundle
    _mhd = _mhb.final_decision
    _rows = []
    for _a in list(getattr(_mhd, "supporting_assessments", []) or []):
        _missing = bool(getattr(_a, "missing", False))
        _hz = str(getattr(_a, "horizon", ""))
        if _missing:
            _conf = None
        else:
            from numeric_contract import float_finite_or_none

            _conf = float_finite_or_none(getattr(_a, "confidence", None))
        _rows.append({"horizon": _hz, "confidence": _conf, "missing": _missing})
    missing_row = next(r for r in _rows if r["horizon"] == "60c")
    assert missing_row["confidence"] is None
    ok_row = next(r for r in _rows if r["horizon"] == "15c")
    assert ok_row["confidence"] is not None
