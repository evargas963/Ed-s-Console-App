"""Arch competition evaluation / promotion failures (fail-closed)."""


class EvaluationLineageError(ValueError):
    """Parallel vs cascade trial lineage mismatch or missing manifest fields."""


class PromotionGovernanceError(ValueError):
    """Promotion decision inputs violated governance rules."""


class PromotionGovernanceMissingError(PromotionGovernanceError):
    """Required governed artifact file is missing on disk (fail-closed)."""


class PromotionGovernanceInvalidError(PromotionGovernanceError):
    """Governed artifact present but invalid (parse error or schema mismatch)."""


class ManualGovernanceError(ValueError):
    """Manual promotion/rollback precondition failed (fail-closed)."""
