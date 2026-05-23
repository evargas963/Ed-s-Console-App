"""P3-10: invalidate_model_registry evicts per (ticker, horizon)."""
from __future__ import annotations

import ml_predict


def test_invalidate_model_registry_clears_cached_key():
    ml_predict.reset_caches()
    rk = ml_predict._model_registry_key("SPY", "1c")
    ml_predict._xgb_registry[rk] = {"model": object()}
    assert ml_predict.invalidate_model_registry("SPY", "1c") is True
    assert rk not in ml_predict._xgb_registry
