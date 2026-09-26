"""
ML product horizons (Issue 15+): canonical slugs, DB outcome columns, artifact suffixes.


Hard contract (two-tier):
- ALL_GOVERNED_HORIZONS: every slug that may run the full inference stack (four primaries).
- PRIMARY_DECISION_HORIZONS: only these may influence MH bundle, canonical policy, compute_call.
- SECONDARY_SUPPORT_HORIZONS: empty after Phase 3 C2; partition asserts remain for future extension.


Live trading stack continues to default to 1c; training/eval/promotion can target any governed slug.
"""
from __future__ import annotations




# ── Authoritative two-tier contract (single source of truth) ──────────────────
PRIMARY_DECISION_HORIZONS: tuple[str, ...] = ("1c", "5c", "15c", "60c")
SECONDARY_SUPPORT_HORIZONS: tuple[str, ...] = ()
ALL_GOVERNED_HORIZONS: tuple[str, ...] = PRIMARY_DECISION_HORIZONS


assert len(ALL_GOVERNED_HORIZONS) == len(set(ALL_GOVERNED_HORIZONS)), "duplicate governed slug"
assert set(ALL_GOVERNED_HORIZONS) == set(PRIMARY_DECISION_HORIZONS) | set(
    SECONDARY_SUPPORT_HORIZONS
), "governed horizons must partition into primary + secondary"
assert not (set(PRIMARY_DECISION_HORIZONS) & set(SECONDARY_SUPPORT_HORIZONS)), "primary/secondary overlap"


# Backward-compatible alias: all slugs that have artifacts / governed stack loops.
ML_HORIZON_SLUGS: tuple[str, ...] = ALL_GOVERNED_HORIZONS



























