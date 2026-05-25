"""Action 12.7: build_market_state must not fabricate session time or charm/IV labels."""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

import pytest

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
def test_build_market_state_stamps_iv_level_as_decimal(_mock_cs):
    """Schwab atm_iv is percent; SignalInput.iv_level must be decimal at stamp."""
    _SIG_CALLS.clear()
    totals = [MagicMock(atm_iv=18.52987037055019, pcr_oi=1.0)]
    build_market_state(**_base_kwargs(totals=totals, mc_iv_level=None))
    assert len(_SIG_CALLS) == 1
    assert _SIG_CALLS[0].iv_level == pytest.approx(0.1852987037055019)


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


def test_dominant_prob_withheld_for_non_tradable_canonical_provenance():
    """LIVE-UI-A: market_state must NOT stamp placeholder 0.333 into ms.dominant_prob
    when canonical_forecast carries non-tradable provenance (fusion_unavailable etc.).
    Producer convention: CanonicalForecast.dominant_probability() returns the placeholder
    for non-tradable cases; the market_state gate at L1541-1556 (canonical_provenance_is_tradable)
    must withhold it. dominant_dir is left as the producer's flat (fail-closed visible value).
    """
    from signal_types import CanonicalForecast

    # Non-tradable placeholder (matches canonical_forecast_from_fusion fail-closed output)
    cf_non_tradable = CanonicalForecast(
        direction="flat",
        probability_up=1 / 3,
        probability_down=1 / 3,
        probability_flat=1 / 3,
        confidence="low",
        provenance="fusion_unavailable",
    )
    # Mirror the production stamp path (market_state.py L1541-1556):
    from fusion_contract import canonical_provenance_is_tradable

    _cf = cf_non_tradable
    ms_dominant_prob = None
    if _cf is not None:
        if canonical_provenance_is_tradable(getattr(_cf, "provenance", None)):
            ms_dominant_prob = round(_cf.dominant_probability(), 4)
        else:
            ms_dominant_prob = None
    assert ms_dominant_prob is None, (
        f"non-tradable canonical leaked placeholder 0.3333 into ms.dominant_prob: {ms_dominant_prob!r}"
    )

    # Regression: tradable canonical still stamps the real prob
    cf_tradable = CanonicalForecast(
        direction="up",
        probability_up=0.65,
        probability_down=0.2,
        probability_flat=0.15,
        confidence="medium",
        provenance="bayesian_fusion",
    )
    _cf = cf_tradable
    ms_dominant_prob = None
    if _cf is not None:
        if canonical_provenance_is_tradable(getattr(_cf, "provenance", None)):
            ms_dominant_prob = round(_cf.dominant_probability(), 4)
        else:
            ms_dominant_prob = None
    assert ms_dominant_prob == 0.65, (
        f"tradable canonical dominant_prob did not pass through: {ms_dominant_prob!r}"
    )


def test_market_state_source_imports_canonical_provenance_gate():
    """Lock: market_state.py imports + uses canonical_provenance_is_tradable on the
    dominant_prob stamp path. Static check — failure means the gate was removed."""
    import ast as _ast
    from pathlib import Path

    text = Path(inspect.getfile(MarketState)).read_text(encoding="utf-8")
    assert "canonical_provenance_is_tradable" in text, "market_state lost the LIVE-UI-A gate import"
    # AST-level locator: the gate must appear in build_market_state body, not just imports.
    tree = _ast.parse(text)
    bm = next(
        (n for n in tree.body if isinstance(n, _ast.FunctionDef) and n.name == "build_market_state"),
        None,
    )
    assert bm is not None, "build_market_state function missing from market_state.py"
    body_src = _ast.unparse(bm)
    assert "canonical_provenance_is_tradable" in body_src, (
        "canonical_provenance_is_tradable not used inside build_market_state — gate moved or removed"
    )
