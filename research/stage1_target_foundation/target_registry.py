"""Stage 1 target registry loader + fail-closed validator (research-only).

The registry (research/stage1_target_label_foundation/target_registry_v1.json)
is the single machine-readable binding of target_id -> formula -> source ->
causal contract -> cost/barrier version -> status. This module loads it and
proves its invariants; tests/test_stage1_target_registry.py locks them.

STATUS MODEL (schema_version 2): causal reconstructability and experiment
readiness are SEPARATE. CAUSAL_CONTRACT_PROVEN is a causality statement only and
does NOT confer Stage 2 eligibility. EXPERIMENT_ELIGIBLE requires every
applicable experiment-readiness gate to pass. LEGACY_BASELINE_ONLY is the
deployed production label, usable only as a baseline-to-beat.

HARD Stage 1 rule: no registry entry may be PRODUCTION_APPROVED.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = (
    ROOT / "research" / "stage1_target_label_foundation"
    / "target_registry_v1.json"
)

# The separated status ladder. Causality (CAUSAL_CONTRACT_PROVEN) is distinct
# from experiment readiness (EXPERIMENT_ELIGIBLE). LEGACY_BASELINE_ONLY is the
# deployed label, never an entrant on its own merit.
STATUS_ENUM = {
    "CANDIDATE",
    "CAUSAL_CONTRACT_PROVEN",
    "DATA_QUALITY_PROVEN",
    "EXPERIMENT_ELIGIBLE",
    "LEGACY_BASELINE_ONLY",
    "INVALID",
    "RETIRED",
    "PRODUCTION_APPROVED",
}
# statuses that assert the causal contract is proven
CAUSAL_PROVEN_STATUSES = {
    "CAUSAL_CONTRACT_PROVEN",
    "DATA_QUALITY_PROVEN",
    "EXPERIMENT_ELIGIBLE",
    "LEGACY_BASELINE_ONLY",
}
# the data-quality subset of the readiness gates (used to distinguish
# DATA_QUALITY_PROVEN from CAUSAL_CONTRACT_PROVEN)
DATA_QUALITY_GATES = (
    "coverage_sufficient",
    "thresholds_fitted",
    "synthetic_provenance_flagged",
    "class_balance_governed",
)
# the full set of readiness gate keys the eligibility rule considers
ALL_GATE_KEYS = DATA_QUALITY_GATES + (
    "overlap_purge_embargo_defined",
    "cost_binding",
    "barrier_spec_fitted",
)

REQUIRED_TARGET_FIELDS = (
    "target_id", "version", "columns", "family", "formula", "economic_meaning",
    "allowed_horizons", "realized_span_minutes_by_horizon", "source_tables",
    "anchor_timestamp", "target_timestamp", "causal_availability",
    "session_policy", "cost_model_version", "barrier_version",
    "label_completion_rule", "overlap_policy", "missing_data_policy",
    "synthetic_data_policy", "expected_metrics", "promotion_status",
    "experiment_readiness", "known_limitations",
)
# a target is "economic" (must name a non-NONE cost model) when its family or id
# signals a cost/utility/return-net economic quantity
_ECONOMIC_MARKERS = ("cost_adjusted", "cost_threshold", "utility", "prob_exceed_costs")
# canonical realized span = (N + 1) minutes for an Nc horizon
_HORIZON_N = {"1c": 1, "5c": 5, "15c": 15, "60c": 60}


def load_registry(path: Path = REGISTRY_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _gate_ok(gate: dict | None) -> bool:
    """A gate passes if it is not applicable, or applicable and ok."""
    if not isinstance(gate, dict):
        return False
    if gate.get("applicable") is False:
        return True
    return bool(gate.get("ok"))


def compute_eligible(readiness: dict) -> bool:
    """eligible == causal_contract_proven AND every applicable gate passes."""
    if not readiness.get("causal_contract_proven"):
        return False
    gates = readiness.get("gates") or {}
    if not gates:
        return False
    return all(_gate_ok(gates.get(k)) for k in ALL_GATE_KEYS if k in gates)


def validate_registry(reg: dict) -> list[str]:
    """Return a list of invariant violations (empty == valid)."""
    errs: list[str] = []
    if reg.get("schema") != "STAGE1_TARGET_REGISTRY":
        errs.append("schema must be STAGE1_TARGET_REGISTRY")
    if reg.get("schema_version") != 2:
        errs.append("schema_version must be 2 (separated status model)")
    canonical = set(reg.get("canonical_horizons") or [])
    if canonical != {"1c", "5c", "15c", "60c"}:
        errs.append(f"canonical_horizons must be the 4 primary horizons, got {sorted(canonical)}")
    # horizon-span semantics must be declared and match (N+1) minutes (Objective E)
    span = reg.get("horizon_span_semantics") or {}
    declared_span = span.get("realized_span_minutes_by_horizon") or {}
    for h, n in _HORIZON_N.items():
        if declared_span.get(h) != n + 1:
            errs.append(
                f"horizon_span_semantics {h}: realized span must be {n + 1} minutes "
                f"(N+1), got {declared_span.get(h)!r}"
            )
    cost_versions = set((reg.get("cost_model_versions") or {}).keys())
    barrier_versions = set((reg.get("barrier_versions") or {}).keys())
    if "NONE" not in cost_versions:
        errs.append("cost_model_versions must define NONE")
    if "NONE" not in barrier_versions:
        errs.append("barrier_versions must define NONE")
    if set(reg.get("status_enum") or []) != STATUS_ENUM:
        errs.append("registry status_enum must equal the separated STATUS_ENUM")

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
        # allowed_horizons subset of canonical (empty allowed for INVALID stubs)
        bad_h = set(t.get("allowed_horizons") or []) - canonical
        if bad_h:
            errs.append(f"{tid}: allowed_horizons contains non-canonical {sorted(bad_h)}")
        # per-target realized span must match (N+1) for each allowed horizon
        tspan = t.get("realized_span_minutes_by_horizon") or {}
        for h in t.get("allowed_horizons") or []:
            if h not in _HORIZON_N:
                continue  # non-canonical horizon already flagged above
            if tspan.get(h) != _HORIZON_N[h] + 1:
                errs.append(
                    f"{tid}: realized_span_minutes_by_horizon[{h}] must be "
                    f"{_HORIZON_N[h] + 1}, got {tspan.get(h)!r}"
                )
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

        # ---- status <-> experiment_readiness consistency (the core redesign) ----
        r = t.get("experiment_readiness") or {}
        if "causal_contract_proven" not in r or "eligible" not in r:
            errs.append(f"{tid}: experiment_readiness must declare causal_contract_proven + eligible")
            continue
        causal = bool(r.get("causal_contract_proven"))
        declared_elig = bool(r.get("eligible"))
        computed_elig = compute_eligible(r)
        if declared_elig != computed_elig:
            errs.append(
                f"{tid}: experiment_readiness.eligible={declared_elig} disagrees with "
                f"computed eligibility {computed_elig} (causal + all applicable gates)"
            )
        # causality-asserting statuses require causal_contract_proven == true
        if status in CAUSAL_PROVEN_STATUSES and not causal:
            errs.append(f"{tid}: status {status} requires causal_contract_proven=true")
        # CANDIDATE/INVALID/RETIRED must NOT assert a proven causal contract as
        # experiment-eligible; and must never be eligible
        if status in {"CANDIDATE", "INVALID", "RETIRED"} and computed_elig:
            errs.append(f"{tid}: status {status} cannot be experiment-eligible")
        # EXPERIMENT_ELIGIBLE iff computed eligible; nothing else may be eligible
        if status == "EXPERIMENT_ELIGIBLE" and not computed_elig:
            errs.append(f"{tid}: EXPERIMENT_ELIGIBLE requires all readiness gates to pass")
        if status != "EXPERIMENT_ELIGIBLE" and computed_elig:
            errs.append(
                f"{tid}: computed eligible but status is {status}; an eligible target "
                "MUST carry EXPERIMENT_ELIGIBLE"
            )
        # LEGACY_BASELINE_ONLY must be causally proven but NOT eligible
        if status == "LEGACY_BASELINE_ONLY" and computed_elig:
            errs.append(f"{tid}: LEGACY_BASELINE_ONLY must not be experiment-eligible")
        # DATA_QUALITY_PROVEN: causal + all data-quality gates pass, but not eligible
        if status == "DATA_QUALITY_PROVEN":
            gates = r.get("gates") or {}
            if not all(_gate_ok(gates.get(k)) for k in DATA_QUALITY_GATES if k in gates):
                errs.append(f"{tid}: DATA_QUALITY_PROVEN requires all data-quality gates to pass")
            if computed_elig:
                errs.append(f"{tid}: DATA_QUALITY_PROVEN must not yet be eligible (else EXPERIMENT_ELIGIBLE)")
    return errs


def stage2_eligible_targets(reg: dict) -> list[str]:
    """The ONLY selection Stage 2 may use: targets that are EXPERIMENT_ELIGIBLE
    and whose readiness independently computes eligible. Fail-closed: a target
    that is merely causally proven is NOT returned."""
    out: list[str] = []
    for t in reg.get("targets") or []:
        if t.get("promotion_status") != "EXPERIMENT_ELIGIBLE":
            continue
        if compute_eligible(t.get("experiment_readiness") or {}):
            out.append(t.get("target_id"))
    return out


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
    print("stage2_eligible_targets:", stage2_eligible_targets(r))
