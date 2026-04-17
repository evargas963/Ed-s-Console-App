"""
Institutional calibration & validation pipeline (Phases 1–5).

Run audits/analyses via:
  python -m calibration.audit_phase1
  python -m calibration.analyze_phase3
  python -m calibration.analyze_phase4
  python -m calibration.backfill_outcomes
  python -m calibration.validate_logging
  python -m calibration.canonical_enforcement
  python -m calibration.anchor_audit
  python -m calibration.validate_outcome_join

Enable persistent decision logging (Phase 2):
  set ED_CALIBRATION_LOG=1
"""

from calibration.schema import CALIBRATION_TABLE_SQL, ensure_calibration_schema

__all__ = [
    "CALIBRATION_TABLE_SQL",
    "ensure_calibration_schema",
]
