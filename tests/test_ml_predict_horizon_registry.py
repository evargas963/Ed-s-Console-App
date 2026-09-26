"""Registry keys must include horizon so each slug loads its own artifacts."""
from __future__ import annotations





def test_model_registry_key_format():
    import ml_predict as mp

    assert mp._model_registry_key("spy", "1c") == "parallel:SPY:1c"
    assert mp._model_registry_key("spy", "5c") == "parallel:SPY:5c"
    assert mp._model_registry_key("spy", "1c") != mp._model_registry_key("spy", "5c")


def test_all_governed_horizons_have_distinct_keys():
    import ml_predict as mp
    from ml_horizon import ML_HORIZON_SLUGS

    keys = {mp._model_registry_key("SPY", hz) for hz in ML_HORIZON_SLUGS}
    assert len(keys) == len(ML_HORIZON_SLUGS)








