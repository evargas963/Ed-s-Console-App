> **Classification:** Historical Record | **Scope:** Completed analysis or validation `docs/db_authority_enforcement_v2_global_closure.md`.

# DB authority enforcement — v2 global closure

## 1. Executive result

**FINAL RESULT: PASS**

Every production/runtime/training/repair/audit SQLite entry point in this repository now resolves the live database through **`db.DB_PATH`** (via `db._resolve_console_db_path()` → `ED_CONSOLE_DB` or `db_authority.canonical_console_db_path()`) or through **`calibration.paths.DEFAULT_DB`** (an alias of `db.DB_PATH`). Non-canonical targets require **`--allow-noncanonical-db`** (see `calibration.db_guard` + `db_authority.cli_require_canonical_or_ack`) except in explicit harness/test contexts (`ED_CONSOLE_ALLOW_NONCANONICAL_DB`, `EdDB(..., allow_noncanonical=True)`).

The **only** remaining literal path to `data/ed_console.db` in executable code is inside **`db_authority.canonical_console_db_path()`**, which *is* the canonical authority definition.

---

## 2. Complete bypass inventory (pre-remediation)

| Category | Count (approx.) | Resolution |
|----------|------------------|------------|
| Module-level `Path(.../"data"/"ed_console.db")` | 25+ files | Replaced with `from db import DB_PATH` or `calibration.paths.DEFAULT_DB` |
| `sqlite3.connect(ROOT/.../ed_console.db)` in tools | 8+ | Same |
| `ml_scheduler` / `lstm_data` / `snapshot_normalizer` env-bypass | 3 | `from db import DB_PATH` |
| `train_compare`, `audit_model_readiness`, `verify_ml_pipeline` | 3 | `from db import DB_PATH` |
| `arch_competition/live_drift_monitoring._resolve_db_path` | 1 | Fallback → `db.DB_PATH` |
| `calibration/edge_discovery` candidate list | 1 | First candidate → `canonical_console_db_path()` |
| CLIs without `--allow-noncanonical-db` | Many | Wired `register_allow_noncanonical_flag` + `require_canonical_db_target` (or `enforce_resolved_path` where DB is resolved) |
| Docstrings / comments mentioning `data/ed_console.db` | N/A | Left as **documentation examples** only (not executable) |

---

## 3. Exact files changed (v2 global remediation)

Core resolution:

- `lstm_data.py`, `snapshot_normalizer.py`, `ml_scheduler.py`, `train_compare.py`, `audit_model_readiness.py`, `verify_ml_pipeline.py`, `arch_competition/live_drift_monitoring.py`
- `calibration/edge_discovery.py` (pick_db_path first candidate)
- `tools/_phase4_bar_check.py`, `tools/_phase4_snapshot_detail.py`, `tools/_phase4_prod_probe.py`, `tools/_phase4_fill_outcomes.py`
- `tools/_issue14_rowcount_proof.py`, `tools/_diag_pin_neutral_outcomes.py`, `tools/_audit_distance_signs_db.py`, `tools/_issue16_outcome_counts.py`, `tools/_issue16_schema_diff.py`, `tools/_issue16_verify_row_match.py`
- `tools/phase2_forward_write_verify.py`, `distance_option_a_backfill_v1.py`, `bar_rehydration_issue19_v1.py`
- `db_health_audit.py`, `debug_flow_snapshot.py`, `backfill_flow_imbalance.py`, `audit_expiry_data.py`, `tests/test_centralization.py`
- `tools/rth_pin_neutral_health_probe_v1.py`, `tools/pin_neutral_1m_5m_divergence_audit_v1.py`, `tools/bar_history_recovery_audit_v1.py`, `tools/pin_neutral_reachability_audit_v1.py`, `tools/final_system_validation_pre_accumulation_v1.py`, `tools/pin_neutral_anchor_feasibility_sample_v1.py`, `tools/pin_neutral_eligibility_funnel_v1.py`, `tools/issue19_forward_canonical_validation_v1.py`, `tools/issue19_option_a_post_validate.py`, `tools/canonical_timeframe_db_evidence_v1.py`, `tools/ontology_mismatch_evidence.py`
- `tools/similarity_feature_universe_report.py`, `tools/similarity_feature_survivorship_report.py`, `tools/adaptive_shadow_report.py`, `tools/audit_similarity_features.py`, `tools/inspect_similar_set.py`
- `lstm_model.py`, `transformer_train.py`, `replay_bundle_coverage.py`, `live_vs_replay_validation.py`

(Previously wired modules from v1 remain unchanged in policy: `db_authority.py`, `db.py`, `calibration/db_guard.py`, `calibration/paths.py`, `tests/conftest.py`, calibration validators/repairs, etc.)

---

## 4. Paths remediated (summary)

| Before | After |
|--------|--------|
| `SCRIPT_DIR / "data" / "ed_console.db"` | `db.DB_PATH` |
| `ROOT / "data" / "ed_console.db"` | `db.DB_PATH` or `calibration.paths.DEFAULT_DB` |
| `os.environ.get("ED_CONSOLE_DB", .../ed_console.db)` (scheduler) | `db.DB_PATH` only |
| `pick_db_path` first candidate literal | `db_authority.canonical_console_db_path()` |

---

## 5. Explicitly allowed exemptions

| Item | Classification |
|------|----------------|
| `db_authority.canonical_console_db_path()` | **Authority layer** — defines the canonical file path. |
| `calibration/run_production_accumulation_validation.py`, `calibration/build_trusted_anchor_proof_dataset.py` | **Harness / proof** — explicit `OUT_DB` / `PROOF_DB` + env `ED_CONSOLE_ALLOW_NONCANONICAL_DB` + `db_mod.DB_PATH` rebind. |
| `tests/**`, `:memory:` SQLite | **Test** — `ED_CONSOLE_ALLOW_NONCANONICAL_DB` in `tests/conftest.py`; temp paths. |
| Docstrings / CLI help text showing `data/ed_console.db` | **Documentation** — not runtime resolution. |
| `tools/phase2_forward_write_verify.py` | **Dev-only write probe** — no `--db` CLI; uses `db.DB_PATH` for all connections (not a production entry point). |

---

## 6. Proof of global closure

**A. No stray executable literals**

```text
rg "ed_console\\.db" --glob "*.py"
```

Remaining matches are: `db_authority.py` (canonical definition), comments/docstrings, and `db.py` / `ml_data_common.py` references in documentation.

**B. Resolver consistency**

```text
python -c "from db import DB_PATH; import lstm_data, snapshot_normalizer, ml_scheduler, train_compare; assert lstm_data.DB_PATH == DB_PATH"
```

**C. Validator — default canonical**

```text
python -m calibration.canonical_enforcement
```
→ `"binary_pass": true` on canonical DB.

**D. Non-canonical blocked without opt-in**

```text
python -m calibration.canonical_enforcement --db data/calibration_accumulation_validation.db
```
→ stderr: `refusing read on non-canonical DB` (exit 2).

**E. Repair / training**

- `distance_option_a_backfill_v1.py`, `bar_rehydration_issue19_v1.py`: default `DEFAULT_DB`; require `--allow-noncanonical-db` for harness DBs.
- `lstm_model` / `transformer_train` `__main__`: default `str(db.DB_PATH)` + guard.

---

## 7. Remaining issues

**None** for global DB authority closure under the stated scope.

**CLI breaking change:** `tools/ontology_mismatch_evidence.py` no longer accepts a bare positional DB path; use `--db PATH` (default: canonical resolver).

---

## 8. FINAL RESULT

| Field | Value |
|-------|--------|
| **FINAL RESULT** | **PASS** |
| **Canonical DB file** | `<project_root>/data/ed_console.db` via `db_authority.canonical_console_db_path()` |
| **Runtime resolver** | `db.DB_PATH` / `calibration.paths.DEFAULT_DB` |
| **Non-canonical opt-in** | `--allow-noncanonical-db` + `ED_CONSOLE_ALLOW_NONCANONICAL_DB` (tests/harness) |
