"""Stage 1 target registry loader + fail-closed validator (research-only).

The registry (governance/research/stage1_target_label_foundation/target_registry_v1.json)
is the single machine-readable binding of target_id -> formula -> source ->
causal contract -> cost/barrier version -> status. This module loads it and
proves its invariants; tests/test_stage1_target_registry.py locks them.

HARD Stage 1 rule: no registry entry may be PRODUCTION_APPROVED.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = (
    ROOT / "governance" / "research" / "stage1_target_label_foundation"
    / "target_registry_v1.json"
)

STATUS_ENUM = {
    "CANDIDATE",
    "VALID_FOR_EXPERIMENT",
    "INVALID",
    "RETIRED",
    "PRODUCTION_APPROVED",
}
REQUIRED_TARGET_FIELDS = (
    "target_id", "version", "columns", "family", "formula", "economic_meaning",
    "allowed_horizons", "source_tables", "anchor_timestamp", "target_timestamp",
    "causal_availability", "session_policy", "cost_model_version", "barrier_version",
    "label_completion_rule", "overlap_policy", "missing_data_policy",
    "synthetic_data_policy", "expected_metrics", "promotion_status",
    "known_limitations",
)
# a target is "economic" (must name a non-NONE cost model) when its family or id
# signals a cost/utility/return-net economic quantity
_ECONOMIC_MARKERS = ("cost_adjusted", "cost_threshold", "utility", "prob_exceed_costs")


def load_registry(path: Path = REGISTRY_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_registry(reg: dict) -> list[str]:
    """Return a list of invariant violations (empty == valid)."""
    errs: list[str] = []
    if reg.get("schema") != "STAGE1_TARGET_REGISTRY":
        errs.append("schema must be STAGE1_TARGET_REGISTRY")
    if reg.get("schema_version") != 1:
        errs.append("schema_version must be 1")
    canonical = set(reg.get("canonical_horizons") or [])
    if canonical != {"1c", "5c", "15c", "60c"}:
        errs.append(f"canonical_horizons must be the 4 primary horizons, got {sorted(canonical)}")
    cost_versions = set((reg.get("cost_model_versions") or {}).keys())
    barrier_versions = set((reg.get("barrier_versions") or {}).keys())
    if "NONE" not in cost_versions:
        errs.append("cost_model_versions must define NONE")
    if "NONE" not in barrier_versions:
        errs.append("barrier_versions must define NONE")

    seen_ids: set[str] = set()
    for t in reg.get("targets") or []:
        tid = t.get("target_id", "<missing>")
        if tid in seen_ids:
            errs.append(f"{tid}: duplicate target_id")
        seen_ids.add(tid)
        for f in REQUIRED_TARGET_FIELDS:
            if f not in t:
                errs.append(f"{tid}: missing required field {f!r}")
        status = t.get("promotion_status")
        if status not in STATUS_ENUM:
            errs.append(f"{tid}: promotion_status {status!r} not in status enum")
        if status == "PRODUCTION_APPROVED":
            errs.append(f"{tid}: PRODUCTION_APPROVED is FORBIDDEN in Stage 1")
        # allowed_horizons subset of canonical (empty allowed for INVALID/candidate stubs)
        bad_h = set(t.get("allowed_horizons") or []) - canonical
        if bad_h:
            errs.append(f"{tid}: allowed_horizons contains non-canonical {sorted(bad_h)}")
        # cost/barrier version references must be declared
        cmv = t.get("cost_model_version")
        if cmv not in cost_versions:
            errs.append(f"{tid}: cost_model_version {cmv!r} not declared in cost_model_versions")
        bv = t.get("barrier_version")
        if bv not in barrier_versions:
            errs.append(f"{tid}: barrier_version {bv!r} not declared in barrier_versions")
        # economic targets must name a versioned (non-NONE) cost model
        marker = (t.get("family", "") + " " + tid).lower()
        if any(m in marker for m in _ECONOMIC_MARKERS) and cmv == "NONE":
            errs.append(f"{tid}: economic target must name a versioned cost model (got NONE)")
        # VALID_FOR_EXPERIMENT requires a proven-causal reconstructable contract
        if status == "VALID_FOR_EXPERIMENT":
            ca = (t.get("causal_availability") or "").upper()
            if "PROVEN CAUSAL" not in ca or "RECONSTRUCT" not in ca:
                errs.append(
                    f"{tid}: VALID_FOR_EXPERIMENT requires causal_availability to assert "
                    "'PROVEN causal' and reconstructability"
                )
    return errs


def targets_by_status(reg: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for t in reg.get("targets") or []:
        out.setdefault(t.get("promotion_status", "?"), []).append(t.get("target_id"))
    return out


if __name__ == "__main__":
    r = load_registry()
    v = validate_registry(r)
    if v:
        for e in v:
            print("INVALID:", e)
        raise SystemExit(1)
    print("target_registry_v1: VALID")
    for st, ids in sorted(targets_by_status(r).items()):
        print(f"  {st}: {len(ids)} -> {ids}")
