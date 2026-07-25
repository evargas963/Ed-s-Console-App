"""Seam: debt_ratchet blocks correctness debt, not shape/style volume."""
from tools.check_institutional_correctness import _RATCHET_BLOCKS_ON_RISE


def test_ratchet_blocks_only_correctness_debt_not_shape_or_style():
    assert "no_fake_defaults" in _RATCHET_BLOCKS_ON_RISE
    assert "orphan_dict_keys" in _RATCHET_BLOCKS_ON_RISE
    assert "tests_missing_explicit_assert" in _RATCHET_BLOCKS_ON_RISE
    assert "mypy_types" in _RATCHET_BLOCKS_ON_RISE
    # Shape / style volume must never fail the commit via the ratchet.
    assert "file_length" not in _RATCHET_BLOCKS_ON_RISE
    assert "function_length" not in _RATCHET_BLOCKS_ON_RISE
    assert "function_complexity" not in _RATCHET_BLOCKS_ON_RISE
    assert "ruff_quality" not in _RATCHET_BLOCKS_ON_RISE
