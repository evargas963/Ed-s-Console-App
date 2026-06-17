# Ablation static-lock performance analysis (Phase 3F-Perf2)

**Scope:** Analysis-only follow-up to Phase 3F-Perf1 pre-commit optimization. No check weakening; no implementation in this artifact.

**Status:** Analysis complete | **Implementation:** deferred until operator approves PERF2-1/2

## Problem

After pre-commit tiering, full static audit (pre-push / `--full-static` / objective-audit) still spends **~3.5 minutes** in repo-wide locks. Two ablation checks dominate:

| Check | Measured (2026-06-16) | Profile (prior run) |
|-------|----------------------|---------------------|
| `check_ablation_seven_model_four_horizon_grid` | **102.7s** | ~143s |
| `check_ablation_equal_layer_consumers` | **52.0s** | ~68s |
| **Combined** | **~155s** | ~211s |

## What each check does

### `check_ablation_seven_model_four_horizon_grid`

1. Scans `AGENTS.md` for grid contract markers
2. Scans `feature_curation_gate.py` for banned partial-grid phrases
3. **Loads** `feature_ablation_manifest_leaf.json` (large JSON)
4. **Builds** DB-enriched row sample via `build_ablation_enriched_row_sample` when `data/ed_console.db` exists
5. **Materializes** full `ablation_whole_stack_feature_cell_specs` grid (feature × 7 models × 4 horizons)
6. Validates catalog/runnable counts and enumerates expected vs actual `(group_id, model, horizon)` triples

### `check_ablation_equal_layer_consumers`

1. Scans `feature_curation_gate.py` for banned fallback symbols + required fidelity markers
2. Scans `governed_stack_contract.py` for layer column markers
3. **Repeats steps 3–5 above** (duplicate manifest load, DB enrich, spec build)
4. Validates upper-layer knockout semantics and runnable counts per model

## Root cause

**Duplicate expensive work:** both checks independently call `load_ablation_manifest` → `build_ablation_enriched_row_sample` → `ablation_whole_stack_feature_cell_specs`. The second check re-pays ~50% of the first check's runtime for identical spec materialization.

**Dominant operations:** JSON parse of manifest, SQLite enrich, O(cells) spec dict construction — not regex/text scans.

**Filesystem:** 4–5 file reads per check; manifest is multi-MB; `feature_curation_gate.py` read twice as full text.

## Safe optimizations (proposed — not implemented)

| ID | Optimization | Expected gain | Enforcement |
|----|--------------|---------------|-------------|
| PERF2-1 | Shared in-process spec index for one audit run | ~60–75s | Unchanged assertions |
| PERF2-2 | Disk cache keyed by manifest+DB+gate hashes | ~155s on unchanged cone | Pass/fail only; hash invalidation |
| PERF2-3 | Lazy DB enrich when scoring universe empty | Minor | Fidelity unchanged when DB used |
| PERF2-4 | Single `gate_text` read per run | <1s | Unchanged |

## Unsafe optimizations (rejected)

- Skip DB enrich on pre-push → weakens runnable/fusion fidelity
- Sample grid triples instead of full enumeration → violates seven×four contract
- Stale cache without DB/manifest invalidation → maturity bypass risk
- Remove ablation checks from `--objective-audit` → weakens full-strength audit

## Objective audit

**Must remain full-strength.** Optimizations apply to shared index + cache only; `--objective-audit` and `--full-static` continue to run all assertions.

## Next step (when approved)

Implement **PERF2-1** (shared in-process index) + **PERF2-2** (hash-keyed disk cache extension) in `tools/fix_everything_we_touch_scope.py` with paired tests in `tests/test_fix_everything_we_touch_performance.py`.

Artifact: `governance/artifacts/ABLATION_LOCK_PERFORMANCE_ANALYSIS.json`
