"""Behavioral lock for position_sizing_policy.regime_size_multiplier (v2).

Extends tests/test_position_sizing_policy.py (which locks the single-authority
sweep and a handful of spot values) with:
  - full-table label -> multiplier behavior,
  - fail-closed handling of missing/blank/unmapped labels (default, never 0/None),
  - confidence-nudge cap and floor boundaries,
  - normalization behavior (whitespace, case) for labels and confidence,
  - design monotonicity: riskier regimes never size larger, low <= base <= high,
  - hard output bounds [0.40, 1.0] across the whole input lattice.

The function's inputs are labels, not market numerics, so the fail-closed
surface here is unmapped/blank/None labels rather than NaN prices.
"""

from __future__ import annotations

import pytest

from position_sizing_policy import (
    REGIME_SIZE_MULTIPLIER_DEFAULT,
    REGIME_SIZE_MULTIPLIERS,
    regime_size_multiplier,
)

ALL_LABELS = sorted(REGIME_SIZE_MULTIPLIERS)

# Design ordering: risk-reducing regimes never size larger than trend continuation.
# (reversal_prone < pinning == mean_reversion < vol_compression == unknown
#  < vol_expansion < breakout == acceleration < trend_continuation)
RISK_ORDER = [
    "reversal_prone",
    "pinning",
    "mean_reversion",
    "vol_compression",
    "unknown",
    "vol_expansion",
    "breakout",
    "acceleration",
    "trend_continuation",
]


# ── Table behavior: every label produces exactly its policy multiplier ───────

@pytest.mark.parametrize("label", ALL_LABELS)
def test_every_mapped_label_returns_table_value_without_confidence(label):
    assert regime_size_multiplier(label) == REGIME_SIZE_MULTIPLIERS[label]


def test_table_covers_all_declared_regimes_and_values_in_bounds():
    # Behavioral effect of the policy constants: each is a usable multiplier.
    for label, mult in REGIME_SIZE_MULTIPLIERS.items():
        assert 0.40 <= mult <= 1.00
        assert regime_size_multiplier(label) == mult


# ── Fail-closed: missing / blank / unmapped labels ───────────────────────────

@pytest.mark.parametrize("label", [None, "", "   ", "\t"])
def test_missing_or_blank_label_uses_default_never_zero(label):
    m = regime_size_multiplier(label)
    assert m == REGIME_SIZE_MULTIPLIER_DEFAULT
    assert m > 0.0  # never fabricates a zero size and never raises


@pytest.mark.parametrize(
    "label",
    ["not_a_regime", "PINNING", "Breakout", "trend continuation", "pinningx"],
)
def test_unmapped_or_wrong_case_label_uses_default(label):
    # Lookup is exact-match after strip; case variants are unmapped by design.
    assert regime_size_multiplier(label) == REGIME_SIZE_MULTIPLIER_DEFAULT


def test_explicit_unknown_equals_dict_miss_default():
    assert regime_size_multiplier("unknown") == REGIME_SIZE_MULTIPLIER_DEFAULT
    assert (
        regime_size_multiplier("unknown")
        == regime_size_multiplier("no_such_regime")
    )


def test_label_whitespace_is_stripped_before_lookup():
    assert regime_size_multiplier("  pinning  ") == REGIME_SIZE_MULTIPLIERS["pinning"]


# ── Confidence nudge: +0.10 capped at 1.0, -0.10 floored at 0.40 ─────────────

@pytest.mark.parametrize("label", ALL_LABELS)
def test_high_confidence_adds_ten_points_capped_at_one(label):
    base = REGIME_SIZE_MULTIPLIERS[label]
    expected = base if base >= 1.0 else min(1.0, base + 0.10)
    assert regime_size_multiplier(label, "high") == pytest.approx(expected)


@pytest.mark.parametrize("label", ALL_LABELS)
def test_low_confidence_subtracts_ten_points_floored_at_forty(label):
    base = REGIME_SIZE_MULTIPLIERS[label]
    expected = max(0.40, base - 0.10)
    assert regime_size_multiplier(label, "low") == pytest.approx(expected)


def test_cap_boundary_trend_continuation_high_stays_at_full_size():
    assert regime_size_multiplier("trend_continuation", "high") == 1.00


def test_cap_boundary_breakout_high_hits_exactly_one():
    # 0.90 + 0.10 lands exactly on the cap.
    assert regime_size_multiplier("breakout", "high") == pytest.approx(1.00)


def test_floor_boundary_reversal_prone_low_hits_exactly_forty():
    # 0.50 - 0.10 lands exactly on the floor.
    assert regime_size_multiplier("reversal_prone", "low") == pytest.approx(0.40)


def test_unmapped_label_still_gets_confidence_nudge_on_default():
    assert regime_size_multiplier("garbage", "high") == pytest.approx(
        REGIME_SIZE_MULTIPLIER_DEFAULT + 0.10
    )
    assert regime_size_multiplier("garbage", "low") == pytest.approx(
        REGIME_SIZE_MULTIPLIER_DEFAULT - 0.10
    )


@pytest.mark.parametrize("conf", ["HIGH", " High ", "\thigh\n"])
def test_confidence_is_case_insensitive_and_stripped(conf):
    base = REGIME_SIZE_MULTIPLIERS["pinning"]
    assert regime_size_multiplier("pinning", conf) == pytest.approx(base + 0.10)


@pytest.mark.parametrize("conf", [None, "", "medium", "extreme", "hi", "lowest"])
def test_unrecognized_confidence_leaves_base_unchanged(conf):
    for label in ALL_LABELS:
        assert regime_size_multiplier(label, conf) == REGIME_SIZE_MULTIPLIERS[label]


# ── Design monotonicity properties ───────────────────────────────────────────

@pytest.mark.parametrize("conf", [None, "low", "medium", "high"])
def test_riskier_regime_never_sizes_larger_at_fixed_confidence(conf):
    values = [regime_size_multiplier(label, conf) for label in RISK_ORDER]
    assert values == sorted(values), dict(zip(RISK_ORDER, values))


@pytest.mark.parametrize("label", ALL_LABELS)
def test_lower_confidence_never_sizes_larger_than_higher(label):
    low = regime_size_multiplier(label, "low")
    base = regime_size_multiplier(label, "medium")
    high = regime_size_multiplier(label, "high")
    assert low <= base <= high


def test_output_always_within_hard_bounds_across_input_lattice():
    labels = ALL_LABELS + [None, "", "typo_regime", "  PINNING "]
    confs = [None, "", "low", "medium", "high", "HIGH", " low ", "garbage"]
    for label in labels:
        for conf in confs:
            m = regime_size_multiplier(label, conf)
            assert 0.40 <= m <= 1.00, (label, conf, m)
