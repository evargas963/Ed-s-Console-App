"""validate_outcome_join: strict None vs empty-string outcome comparison."""

from __future__ import annotations

from calibration.validate_outcome_join import _outcome_field_equal


def test_outcome_field_equal_none_vs_empty_string_is_mismatch() -> None:
    assert _outcome_field_equal(None, "", numeric=False) is False
    assert _outcome_field_equal("", None, numeric=False) is False


def test_outcome_field_equal_both_none() -> None:
    assert _outcome_field_equal(None, None, numeric=False) is True


def test_outcome_field_equal_same_label() -> None:
    assert _outcome_field_equal("up", "up", numeric=False) is True
