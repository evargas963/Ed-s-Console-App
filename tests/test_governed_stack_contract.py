from types import SimpleNamespace

import pytest

from governed_stack_contract import (
    mc_model_direction_inputs,
    wall_clock_minutes_to_mc_bars,
)


def test_wall_clock_minutes_to_mc_bars_true_wallclock():
    """Display-only 5m/15m EFE/EAE must request TRUE wall-clock bars, not slug integers.

    With monte_carlo.BAR_MINUTES=5: 5 min -> 1 bar, 15 min -> 3 bars. Using the slug
    integer (5c->5 bars) would be 25 minutes — the over-simulation bug this helper exists
    to prevent.
    """
    from monte_carlo import BAR_MINUTES

    assert wall_clock_minutes_to_mc_bars(5) == 5 // int(BAR_MINUTES)
    assert wall_clock_minutes_to_mc_bars(15) == 15 // int(BAR_MINUTES)
    if int(BAR_MINUTES) == 5:
        assert wall_clock_minutes_to_mc_bars(5) == 1
        assert wall_clock_minutes_to_mc_bars(15) == 3


def test_wall_clock_minutes_to_mc_bars_rejects_non_multiple_and_nonpositive():
    from monte_carlo import BAR_MINUTES

    with pytest.raises(ValueError):
        wall_clock_minutes_to_mc_bars(0)
    with pytest.raises(ValueError):
        wall_clock_minutes_to_mc_bars(-5)
    if int(BAR_MINUTES) == 5:
        # 1-minute forecast is NOT representable while BAR_MINUTES=5 (needs the alignment fix)
        with pytest.raises(ValueError):
            wall_clock_minutes_to_mc_bars(1)


def test_mc_inputs_from_stack_probs():
    x = SimpleNamespace(available=True, prob_up=0.6, prob_down=0.2, prob_flat=0.2)
    u, d, c, avail, src = mc_model_direction_inputs(
        xgb_out=x,
        lstm_out=SimpleNamespace(available=False),
        transformer_out=SimpleNamespace(available=False),
        stack_probs={"up": 0.5, "down": 0.3, "flat": 0.2},
    )
    assert abs(u - 0.5) < 1e-9
    assert abs(d - 0.3) < 1e-9
    assert src == "stack_probs_meta_or_weighted"
    assert c in ("high", "medium", "low")
    assert avail["xgboost"] is True


def test_mc_inputs_uniform_when_no_signal():
    fb = SimpleNamespace(available=False, prob_up=0.33, prob_down=0.33, prob_flat=0.34)
    u, d, c, avail, src = mc_model_direction_inputs(
        xgb_out=fb,
        lstm_out=fb,
        transformer_out=fb,
        stack_probs=None,
    )
    assert abs(u - 1 / 3) < 1e-9
    assert abs(d - 1 / 3) < 1e-9
    assert c == "low"
    assert src == "uniform_no_base_tri_class_signal"


def test_display_wall_clock_mc_excursions_fail_closed_without_iv():
    from signals import _compute_display_wall_clock_mc_excursions

    inp = SimpleNamespace(ticker="SPY", iv_level=None)
    out = _compute_display_wall_clock_mc_excursions(
        inp,
        regime=None,
        mc_spot_ctx={"spot": 500.0},
        mc_context_error=None,
        xgb_out=None,
        lstm_out=None,
        transformer_out=None,
        ml_bundle={},
    )
    assert out == {
        "mc_efe_5m": None,
        "mc_eae_5m": None,
        "mc_efe_15m": None,
        "mc_eae_15m": None,
    }


def test_display_wall_clock_mc_excursions_populates_5m_15m():
    from signals import _compute_display_wall_clock_mc_excursions
    from governed_stack_contract import wall_clock_minutes_to_mc_bars

    inp = SimpleNamespace(ticker="SPY", iv_level=0.18)
    fb = SimpleNamespace(available=False, prob_up=0.33, prob_down=0.33, prob_flat=0.34)
    out = _compute_display_wall_clock_mc_excursions(
        inp,
        regime=SimpleNamespace(primary="pinning", confidence="high"),
        mc_spot_ctx={"spot": 450.0, "realized_vol": 0.15, "atr": 1.5},
        mc_context_error=None,
        xgb_out=fb,
        lstm_out=fb,
        transformer_out=fb,
        ml_bundle={},
    )
    assert wall_clock_minutes_to_mc_bars(5) == 1
    assert wall_clock_minutes_to_mc_bars(15) == 3
    assert out["mc_efe_5m"] is not None and out["mc_eae_5m"] is not None
    assert out["mc_efe_15m"] is not None and out["mc_eae_15m"] is not None
    assert out["mc_efe_15m"] >= out["mc_efe_5m"]
    assert out["mc_eae_15m"] >= out["mc_eae_5m"]
