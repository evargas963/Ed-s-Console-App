"""Issue 17: 60c is first-class for ML (artifacts, labels, rule features, meta horizon label)."""

from __future__ import annotations


from ml_horizon import (
    ML_HORIZON_SLUGS,
)






def test_60c_in_product_horizon_tuple():
    assert "60c" in ML_HORIZON_SLUGS
    assert ML_HORIZON_SLUGS[-1] == "60c"




