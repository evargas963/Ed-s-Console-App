"""RC-318 — absence gets a TYPE on the sequence-encode lane, never a coerced 0.0.

The canonical form of the absence-coerced-to-a-value class was lstm_data._safe_float
(None -> 0.0) feeding reference spots and, via `_safe_float(...) or ref` idioms, the
micro-stream reference in four modules. These tests prove the typed-absence behavior of
every CHANGED site:

  * canonical_reference_spot_from_sequence_window_first_bar — absent/NaN spot -> ValueError
    (explicit row-drop; every caller catches it), never a 0.0 or NaN reference.
  * micro_reference_spot_from_window — the ONE producer for the micro reference: absent /
    NaN / non-positive first-bar spot is TESTED and falls back to the validated ref_spot.
  * features.signal_layer_v1._sign_trend — unmeasurable slope propagates as None (the
    layer's absence type), never a fabricated "measured flat" 0.0.
  * order_flow_engine._weighted_mean_present — absent legs are EXCLUDED, never counted as
    neutral 0.0 mass (_normalize no longer accepts None at all).

_safe_float itself survives ONLY as the frozen legacy-v2 checkpoint-parity coercion; its
contract is pinned here so a future edit cannot silently shift legacy serve inputs.
"""
from __future__ import annotations

import math

import pytest


# ── canonical reference spot: absent -> typed row-drop (ValueError) ──────────────────────

def test_canonical_reference_spot_absent_spot_raises_not_zero():
    from lstm_data import canonical_reference_spot_from_sequence_window_first_bar as ref

    with pytest.raises(ValueError):
        ref([{"spot": None}])
    with pytest.raises(ValueError):
        ref([{}])
    with pytest.raises(ValueError):
        ref([{"spot": "not-a-number"}])


def test_canonical_reference_spot_nan_and_inf_raise():
    # The old _safe_float form returned NaN here, which slipped past the `<= 0` guard and
    # NaN-poisoned every ref-normalized feature in the window.
    from lstm_data import canonical_reference_spot_from_sequence_window_first_bar as ref

    with pytest.raises(ValueError):
        ref([{"spot": float("nan")}])
    with pytest.raises(ValueError):
        ref([{"spot": float("inf")}])


def test_canonical_reference_spot_valid_first_bar_only():
    from lstm_data import canonical_reference_spot_from_sequence_window_first_bar as ref

    assert ref([{"spot": 431.25}, {"spot": 9.0}]) == 431.25


# ── micro reference spot: ONE producer, absence tested -> validated fallback ─────────────

def test_micro_reference_spot_absent_falls_back_to_validated_ref():
    from lstm_data import micro_reference_spot_from_window as micro

    assert micro([{"spot": None}], 430.0) == 430.0
    assert micro([{}], 430.0) == 430.0
    assert micro([], 430.0) == 430.0


def test_micro_reference_spot_nan_and_nonpositive_fall_back():
    # `_safe_float(...) or ref` let NaN (truthy) and negative spots through as the division
    # reference; the typed producer tests None/NaN/<=0 explicitly.
    from lstm_data import micro_reference_spot_from_window as micro

    assert micro([{"spot": float("nan")}], 430.0) == 430.0
    assert micro([{"spot": -5.0}], 430.0) == 430.0
    assert micro([{"spot": 0.0}], 430.0) == 430.0


def test_micro_reference_spot_present_first_bar_wins():
    from lstm_data import micro_reference_spot_from_window as micro

    assert micro([{"spot": 431.5}, {"spot": 2.0}], 430.0) == 431.5


def test_training_and_serving_lanes_use_the_one_micro_producer():
    """The four former `_safe_float(...) or ref` sites all route through the one producer."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for mod in ("lstm_data.py", "ml_scheduler.py", "ml_predict.py"):
        text = (root / mod).read_text(encoding="utf-8")
        assert "micro_reference_spot_from_window" in text, mod
        assert "_safe_float(micro" not in text, mod


# ── legacy v2 checkpoint parity: the surviving coercion is pinned, not silent ────────────

def test_safe_float_legacy_v2_coercion_pinned():
    # KEPT site (absence-literal-ok): already-trained legacy-v2 checkpoints were trained on
    # 0.0-filled absent non-nullable columns; this pin stops a silent parity shift in either
    # direction (a NaN here would poison a torch model with no imputation lane at serve).
    from lstm_data import _safe_float

    assert _safe_float(None) == 0.0
    assert _safe_float("junk") == 0.0
    assert _safe_float(2.5) == 2.5


# ── signal layer: unmeasurable slope -> None, the layer's absence type ───────────────────

def test_sign_trend_absent_slope_is_none_not_flat():
    from features.signal_layer_v1 import _sign_trend

    assert _sign_trend(None) is None


def test_sign_trend_measured_values_unchanged():
    from features.signal_layer_v1 import _sign_trend

    assert _sign_trend(0.02) == 1.0
    assert _sign_trend(-0.02) == -1.0
    assert _sign_trend(0.0) == 0.0
    assert _sign_trend(5e-9) == 0.0  # inside eps: measured flat, a real answer


def test_layer_short_history_trend_sign_is_none_end_to_end():
    # Two bars: the 1m slope needs >= 3 non-None closes, so the slope is unmeasurable.
    # Before RC-318 the layer published mtf.trend_1m_sign = 0.0 ("measured flat") for this
    # window; the honest layer value is None, and alignment must propagate that None.
    from features.signal_layer_v1 import compute_signal_layer_v1

    bars = []
    for k in range(2):
        be = 1_000_000.0 + float(k + 1) * 60.0
        bars.append(
            {
                "bar_start_ts_utc": be - 60.0,
                "bar_end_ts_utc": be,
                "open": 100.0,
                "high": 100.1,
                "low": 99.9,
                "close": 100.0 + 0.02 * k,
                "volume": 1e6,
            }
        )
    layer = compute_signal_layer_v1(bars, decision_ts_utc=bars[-1]["bar_end_ts_utc"], inp=None)
    assert layer["mtf.trend_1m_sign"] is None
    assert layer["mtf.alignment_state"] is None


def test_direction_consumers_skip_none_signs():
    # Both scoring consumers must SKIP an absent sign, not read it as flat.
    from features.signal_layer_v1 import layer_direction_policy

    layer = {
        "meta.n_bars": 30,
        "mtf.trend_1m_sign": None,
        "mtf.trend_5m_from_1m_sign": None,
        "mtf.bias_15m_from_1m_sign": None,
    }
    assert layer_direction_policy(layer) == "wait"


# ── order flow: absent legs are excluded, never neutral 0.0 mass ─────────────────────────

def test_weighted_mean_present_never_zero_fills_absent_leg():
    from app.options.order_flow.engine import _weighted_mean_present

    terms = [(1.0, None, -1.0, 1.0), (1.0, 0.5, -1.0, 1.0)]
    # Zero-filling the absent leg would yield 0.25; exclusion yields 0.5 exactly.
    assert _weighted_mean_present(terms, min_present=1) == 0.5


def test_normalize_requires_a_present_value():
    # RC-318: _normalize's dead `None -> 0.0` branch is gone; absence is the caller's
    # concern (exclusion), so passing None is now a type error, not a neutral reading.
    from app.options.order_flow.engine import _normalize

    with pytest.raises(TypeError):
        _normalize(None)  # type: ignore[arg-type]
    assert _normalize(0.3) == 0.3
    assert not math.isnan(_normalize(1e9))
