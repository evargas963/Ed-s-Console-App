from types import SimpleNamespace

from governed_stack_contract import mc_model_direction_inputs


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
