"""
Calibration row trust: trusted (post-quarantine production inserts) vs legacy (pre-milestone rows).

All empirical study paths MUST filter `calibration_trust = 'trusted'` by default.
"""

from __future__ import annotations

# Values stored in calibration_decision_log.calibration_trust
CALIBRATION_TRUST_LEGACY = "legacy"
CALIBRATION_TRUST_TRUSTED = "trusted"

# SQL fragment for trusted-only study datasets (no table alias; use `AND ` + predicate)
TRUSTED_PREDICATE_SQL = "calibration_trust = 'trusted'"


def trusted_and(sql_fragment: str) -> str:
    """Append trusted filter to a WHERE clause that already references calibration_decision_log."""
    return f"({sql_fragment}) AND {TRUSTED_PREDICATE_SQL}"
