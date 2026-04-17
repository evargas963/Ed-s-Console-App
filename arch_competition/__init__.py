"""Architecture competition: offline evaluation + promotion decisions (no live default change)."""

from arch_competition.eval_runner import (
    EVALUATION_MANIFEST_REQUIRED_KEYS,
    EVALUATION_MANIFEST_SCHEMA_VERSION,
    run_architecture_pair_evaluation,
)
from arch_competition.promotion_engine import (
    PROMOTION_RECORD_REQUIRED_KEYS,
    PROMOTION_RECORD_SCHEMA_VERSION,
    decide_promotion,
    PromotionPolicy,
)
from arch_competition.scheduler_integration import (
    GOVERNED_ARCH_STATE_REQUIRED_KEYS,
    GOVERNED_ARCH_STATE_SCHEMA_VERSION,
    load_architecture_competition_visibility,
)
from arch_competition.audit import AUDIT_RECORD_REQUIRED_KEYS, AUDIT_RECORD_SCHEMA_VERSION
from arch_competition.manual_control import (
    MANUAL_PROMOTE_CASCADE_INTENT,
    MANUAL_PROMOTE_PARALLEL_INTENT,
    MANUAL_ROLLBACK_INTENT,
    load_governance_visibility,
    manual_promote_to_active_explicit,
    manual_rollback_to_checkpoint_explicit,
)
from arch_competition.governance_visibility import (
    GOVERNANCE_PANEL_SCHEMA_VERSION,
    build_governance_panel_payload,
)

__all__ = [
    "EVALUATION_MANIFEST_REQUIRED_KEYS",
    "EVALUATION_MANIFEST_SCHEMA_VERSION",
    "run_architecture_pair_evaluation",
    "PROMOTION_RECORD_REQUIRED_KEYS",
    "PROMOTION_RECORD_SCHEMA_VERSION",
    "decide_promotion",
    "PromotionPolicy",
    "GOVERNED_ARCH_STATE_REQUIRED_KEYS",
    "GOVERNED_ARCH_STATE_SCHEMA_VERSION",
    "load_architecture_competition_visibility",
    "AUDIT_RECORD_REQUIRED_KEYS",
    "AUDIT_RECORD_SCHEMA_VERSION",
    "MANUAL_PROMOTE_CASCADE_INTENT",
    "MANUAL_PROMOTE_PARALLEL_INTENT",
    "MANUAL_ROLLBACK_INTENT",
    "load_governance_visibility",
    "manual_promote_to_active_explicit",
    "manual_rollback_to_checkpoint_explicit",
    "GOVERNANCE_PANEL_SCHEMA_VERSION",
    "build_governance_panel_payload",
]
