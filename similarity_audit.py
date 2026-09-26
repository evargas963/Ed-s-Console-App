"""
Issue 21 — structured audit, validation, and export helpers for tier-driven similarity.

Read-only / deterministic utilities. Does not change selection policy (Issue 19).

Column tuples mirror db.py (SIMILARITY_*_OUTCOME_COLUMNS) — keep in sync.

Feature contract (adaptive shadow baseline audit): baseline_feature_contract_v1().
"""
from __future__ import annotations



# ── Mirror db.py Issue 19 (avoid circular import) ─────────────────────────────
from ml_horizon import PRIMARY_DECISION_HORIZONS

SIMILARITY_EMPIRICAL_OUTCOME_COLUMNS: tuple[str, ...] = tuple(
    f"outcome_{hz}" for hz in PRIMARY_DECISION_HORIZONS
)
SIMILARITY_TIER_STOP_OUTCOME_COLUMNS: tuple[str, ...] = (
    "outcome_1c",
    "outcome_5c",
    "outcome_15c",
)








































