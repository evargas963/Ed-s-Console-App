"""
Calibration row trust: trusted (post-quarantine production inserts) vs legacy
(pre-milestone rows + Track B reconstructed rows).

Two SQL predicates expose the policy split:

  TRUSTED_PREDICATE_SQL
      Live-writer rows only (calibration_trust='trusted', decision_source NULL).
      JSON blobs (fusion_json, canonical_json, model_outputs_json) are present.
      Use for: Brier scores, A1 isotonic calibration fit, reliability curves,
      model-output regression, retraining that consumes the existing fusion
      outputs, anything that reads canonical_json / fusion_json / model_outputs_json.

  FEATURE_STUDY_PREDICATE_SQL
      Live-writer rows + Track B reconstructed rows. Excludes the 42 stale
      pre-milestone rows (calibration_trust='legacy' + decision_source NULL).
      JSON blobs may be NULL on reconstructed rows; only structured columns
      (zone, regime, vix_bucket, vwap_side, distances, outcomes) are
      guaranteed. Use for: cohort base-rate studies, feature/zone/regime
      categorization, outcome-conditional stats, ablation studies that only
      need INPUT FEATURES + OUTCOMES (not the at-decision JSON capture).

Rule of thumb: if the study reads `canonical_json` / `fusion_json` /
`model_outputs_json`, use TRUSTED_PREDICATE_SQL. If it reads only structured
columns + outcomes, FEATURE_STUDY_PREDICATE_SQL gives 4.7x more rows.

Default is still trusted-only — FEATURE_STUDY_PREDICATE_SQL is opt-in for
new feature/cohort scripts. Do NOT replace TRUSTED_PREDICATE_SQL in existing
analyze_phase3 / edge_discovery / signal_engineering pipelines.

For maximum feature coverage, `snapshots` is the canonical feature store
(~200 columns, never had a writer gap). Use calibration_decision_log when
you specifically need decision audit identity / outcome-join methodology
alignment; use snapshots when you just want the feature matrix.
"""

from __future__ import annotations

# Values stored in calibration_decision_log.calibration_trust
CALIBRATION_TRUST_LEGACY = "legacy"
CALIBRATION_TRUST_TRUSTED = "trusted"

# Values stored in calibration_decision_log.decision_source (Track B-aware)
DECISION_SOURCE_LIVE_WRITER = None  # column is NULL on live writer rows
DECISION_SOURCE_RECONSTRUCTED = "reconstructed_from_snapshot"

# SQL fragment for trusted-only study datasets (no table alias; use `AND ` + predicate)
TRUSTED_PREDICATE_SQL = "calibration_trust = 'trusted'"

# SQL fragment for feature/cohort studies that can consume Track B reconstructed
# rows. Matches live-writer rows (trusted) + Track B rows (legacy + reconstructed).
# Excludes the 42 pre-milestone legacy rows (legacy + NULL decision_source) which
# predate the current schema lock and are operator-flagged as unreviewed.
FEATURE_STUDY_PREDICATE_SQL = (
    "(calibration_trust = 'trusted' "
    "OR decision_source = 'reconstructed_from_snapshot')"
)


def trusted_and(sql_fragment: str) -> str:
    """Append trusted filter to a WHERE clause that already references calibration_decision_log."""
    return f"({sql_fragment}) AND {TRUSTED_PREDICATE_SQL}"


def feature_study_and(sql_fragment: str) -> str:
    """Append feature-study filter (live + Track B reconstructed) to a WHERE clause.

    Use only in NEW or explicitly feature-study scripts. Existing pipelines
    (analyze_phase3, edge_discovery, signal_engineering, A1 calibration fit)
    must keep ``trusted_and`` / TRUSTED_PREDICATE_SQL — they read JSON blobs
    that reconstructed rows don't have.
    """
    return f"({sql_fragment}) AND {FEATURE_STUDY_PREDICATE_SQL}"
