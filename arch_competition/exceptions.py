"""Arch competition evaluation / promotion failures (fail-closed)."""


class EvaluationLineageError(ValueError):
    """Parallel vs cascade trial lineage mismatch or missing manifest fields."""


class PromotionGovernanceError(ValueError):
    """Promotion decision inputs violated governance rules."""


class ManualGovernanceError(ValueError):
    """Manual promotion/rollback precondition failed (fail-closed)."""
