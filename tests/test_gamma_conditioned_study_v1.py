"""RC-7 seams for the gamma-conditioned study (pure units)."""
from __future__ import annotations

from research.pilot_step3.gamma_conditioned_study_v1 import (
    STALENESS_MAX_SEC,
    TRAILING_SESSIONS,
    condition_membership,
    latest_gamma_at,
    robust_z,
)


def test_sign_conditions_partition_and_strong_requires_z():
    assert condition_membership(-5.0, None) == {"NEG"}
    assert condition_membership(5.0, None) == {"POS"}
    assert condition_membership(-5.0, -1.5) == {"NEG", "NEG_STRONG"}
    assert condition_membership(5.0, 1.0) == {"POS", "POS_STRONG"}
    assert condition_membership(0.0, 0.0) == set()          # zero gamma joins nothing


def test_robust_z_needs_full_trailing_baseline_and_live_iqr():
    assert robust_z(1.0, [0.0] * (TRAILING_SESSIONS - 1)) is None    # thin history
    assert robust_z(1.0, [5.0] * TRAILING_SESSIONS) is None          # degenerate IQR
    hist = [float(i) for i in range(TRAILING_SESSIONS)]              # median 9.5/10 band
    z = robust_z(19.5, hist)
    assert z is not None and z > 0.9


def test_latest_gamma_staleness_fails_closed():
    rows = [(1000.0, 2.0), (1600.0, -3.0)]
    assert latest_gamma_at(rows, 1650.0) == -3.0                      # fresh
    assert latest_gamma_at(rows, 1600.0 + STALENESS_MAX_SEC + 1) is None  # stale
    assert latest_gamma_at(rows, 999.0) is None                       # nothing before
