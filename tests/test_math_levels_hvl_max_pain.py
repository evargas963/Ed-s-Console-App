from math_levels import compute_max_pain


def test_compute_max_pain_returns_none_for_sparse_chain():
    assert compute_max_pain({}) is None
    assert compute_max_pain({100.0: {"call_oi": 10.0, "put_oi": 0.0}}) is None
