"""

ML product horizons (Issue 15+): canonical slugs, DB outcome columns, artifact suffixes.



Hard contract (two-tier):

- ALL_GOVERNED_HORIZONS: every slug that may run the full inference stack (7).

- PRIMARY_DECISION_HORIZONS: only these may influence MH bundle, canonical policy, compute_call.

- SECONDARY_SUPPORT_HORIZONS: computed/logged/diagnostics only — never authoritative for decisions.



Live trading stack continues to default to 1c; training/eval/promotion can target any governed slug.

"""

from __future__ import annotations



from horizon_outcomes import OUTCOME_HORIZON_MINUTES



# ── Authoritative two-tier contract (single source of truth) ──────────────────

ALL_GOVERNED_HORIZONS: tuple[str, ...] = (

    "1c",

    "3c",

    "5c",

    "8c",

    "13c",

    "15c",

    "60c",

)

PRIMARY_DECISION_HORIZONS: tuple[str, ...] = ("1c", "5c", "15c", "60c")

SECONDARY_SUPPORT_HORIZONS: tuple[str, ...] = ("3c", "8c", "13c")



assert len(ALL_GOVERNED_HORIZONS) == len(set(ALL_GOVERNED_HORIZONS)), "duplicate governed slug"

assert set(ALL_GOVERNED_HORIZONS) == set(PRIMARY_DECISION_HORIZONS) | set(

    SECONDARY_SUPPORT_HORIZONS

), "governed horizons must partition into primary + secondary"

assert not (set(PRIMARY_DECISION_HORIZONS) & set(SECONDARY_SUPPORT_HORIZONS)), "primary/secondary overlap"



# Backward-compatible alias: all slugs that have artifacts / governed stack loops.

ML_HORIZON_SLUGS: tuple[str, ...] = ALL_GOVERNED_HORIZONS



DEFAULT_ML_HORIZON_SLUG: str = "1c"





def normalize_ml_horizon_slug(s: str | None) -> str:

    if s is None or str(s).strip() == "":

        return DEFAULT_ML_HORIZON_SLUG

    x = str(s).strip().lower()

    if x not in ML_HORIZON_SLUGS:

        raise ValueError(

            f"ml_horizon: invalid slug {s!r}; allowed {list(ML_HORIZON_SLUGS)}"

        )

    return x





def is_primary_decision_horizon(slug: str | None) -> bool:

    """True if slug is authoritative for MH bundle / policy (not diagnostics-only)."""

    try:

        return normalize_ml_horizon_slug(slug) in PRIMARY_DECISION_HORIZONS

    except ValueError:

        return False





def is_secondary_support_horizon(slug: str | None) -> bool:

    """True if slug is diagnostics/support-only (must not drive MH bundle or compute_call)."""

    try:

        return normalize_ml_horizon_slug(slug) in SECONDARY_SUPPORT_HORIZONS

    except ValueError:

        return False





def outcome_column(slug: str) -> str:

    """DB label column, e.g. 5c -> outcome_5c."""

    su = normalize_ml_horizon_slug(slug)

    return f"outcome_{su}"





def directional_label_column(slug: str) -> str:

    """Movement-target v1: binary direction among moved rows only, e.g. outcome_dir_5c."""

    su = normalize_ml_horizon_slug(slug)

    return f"outcome_dir_{su}"





def move_label_column(slug: str) -> str:

    """Movement-target v1: move vs no_move on full sample, e.g. outcome_move_5c."""

    su = normalize_ml_horizon_slug(slug)

    return f"outcome_move_{su}"





def default_training_label_column() -> str:

    """SQL label column for training/ticker discovery when horizon is the live default."""

    return outcome_column(DEFAULT_ML_HORIZON_SLUG)





def live_inference_horizon_slug() -> str:

    """Horizon slug for models/active/, arch_state.json, and live predict_direction (Issue 15)."""

    return DEFAULT_ML_HORIZON_SLUG





def live_stack_probs_bundle_key() -> str:

    """signals / prediction_engine dict key for stacked ML probabilities (live horizon only)."""

    return f"stack_probs_{live_inference_horizon_slug()}"





# Eager constant for function default arguments (same value as default_training_label_column()).

DEFAULT_TRAINING_LABEL_COLUMN: str = outcome_column(DEFAULT_ML_HORIZON_SLUG)





def target_definition(slug: str) -> str:

    """Human + machine provenance string (must contain promotion substring)."""

    su = normalize_ml_horizon_slug(slug)

    col = outcome_column(su)

    mins = int(OUTCOME_HORIZON_MINUTES[col])

    return f"{col} ~{mins} min ahead ({mins}×1m bars)"





def promotion_definition_substring(slug: str) -> str:

    """validate_for_promotion checks this substring is in target_definition."""

    col = outcome_column(slug)

    mins = int(OUTCOME_HORIZON_MINUTES[col])

    return f"{mins} min"

