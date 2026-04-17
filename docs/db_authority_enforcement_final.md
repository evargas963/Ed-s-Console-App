# DB authority enforcement — final report

## 1. Executive result

**FINAL RESULT: FAIL** (strict global closure criteria)

Production/runtime database targeting is **enforced** through `db.py`, `db_authority.py`, and `EdDB` (including `ED_CONSOLE_DB` policy). **CLI guardrails** (`calibration.db_guard` + `--allow-noncanonical-db`) cover the main calibration validators/repairs, core training entrypoints (`ml_train`, `train_all`), several root utilities, and selected `tools/` CLIs.

**Not complete under the stated bar** (“no unresolved ambiguity,” “every entry point,” “tooling globally”): many auxiliary scripts, one-off `tools/_*.py` probes, and some modules still **hardcode** `.../data/ed_console.db` or otherwise bypass `db.DB_PATH`, so **`ED_CONSOLE_DB` can diverge** from what those scripts open. That is **documented in §9** as remaining work—not silent if the operator knows only the canonical file is `data/ed_console.db`, but it **is** ambiguous when `ED_CONSOLE_DB` points elsewhere.

---

## 2. Canonical DB authority policy (encoded in code)

| Concept | Implementation |
|--------|----------------|
| **Canonical production file** | `db_authority.canonical_console_db_path()` → `<project_root>/data/ed_console.db` (resolved). |
| **Runtime / EdDB resolution** | `db._resolve_console_db_path()` → `ED_CONSOLE_DB` if set, else canonical path. `assert_ed_console_db_env_resolves_safely()` when `ED_CONSOLE_DB` is set. |
| **Classification** | `classify_db_path()` → `canonical` \| `harness` \| `proof` \| `backup` \| `unknown`. |
| **Non-canonical CLI opt-in** | `--allow-noncanonical-db` → `calibration.db_guard.cli_require_canonical_or_ack()` (exit **2** if missing). |
| **Harness / tests** | `ED_CONSOLE_ALLOW_NONCANONICAL_DB=1` (set in `tests/conftest.py`) + `EdDB(..., allow_noncanonical=True)` where needed. |

Authoritative modules: `db_authority.py`, `db.py`, `calibration/db_guard.py`, `tests/conftest.py`.

---

## 3. DB-targeting entry point inventory

### A. Production runtime (authoritative)

| Location | Entry | Path choice | R/W | Non-canonical? |
|----------|--------|---------------|-----|----------------|
| `db.py` | `EdDB`, `DB_PATH`, `_resolve_console_db_path` | `ED_CONSOLE_DB` or default canonical | R/W | Blocked unless `allow_noncanonical` or `ED_CONSOLE_ALLOW_NONCANONICAL_DB` |

### B. Calibration package — CLI guarded (`require_canonical_db_target` or `enforce_resolved_path`)

| Module | Notes |
|--------|--------|
| `validate_outcome_join`, `validate_logging`, `audit_phase1`, `anchor_audit`, `audit_phase1` | Default `calibration.paths.DEFAULT_DB` (= `db.DB_PATH`) |
| `analyze_phase3`, `analyze_phase4`, `canonical_enforcement`, `edge_validation`, `legacy_report` | Same |
| `backfill_outcomes`, `repair_canonical_1m_bars_for_outcomes`, `backfill_signal_layer_v1_bundle` | Write-capable; `EdDB(..., allow_noncanonical=...)` where applicable |
| `edge_discovery`, `signal_engineering` | `pick_db_path()` then **`enforce_resolved_path`** (stops silent harness pick without `--allow-noncanonical-db`) |
| `signal_layer_discrimination` | Default canonical; no longer defaults to harness DB |

### C. Root / training / smoke (guarded)

| Script | Guard |
|--------|--------|
| `ml_train.py` | `require_canonical_db_target` |
| `train_all.py` | Same; `run_xgb` now receives `db_path` from CLI |
| `smoke_predict_active.py` | Same + `EdDB(..., allow_noncanonical=...)` |
| `backfill_snapshot_derived.py` | Same; default `DEFAULT_DB` from `calibration.paths` |
| `pin_neutral_outcome_repair_v1.py` | Same + `EdDB(..., allow_noncanonical=...)` |

### D. Selected `tools/` (guarded)

| Script | Guard |
|--------|--------|
| `tools/issue19_rehydration_range_v1.py` | `require_canonical_db_target` |
| `tools/repair_validation_counts_v1.py` | Same |
| `tools/run_adaptive_shadow_v2_calibration.py` | Same + `EdDB(allow_noncanonical=...)` |

### E. Harness builders (explicit)

| Script | Behavior |
|--------|----------|
| `calibration/run_production_accumulation_validation.py` | Sets `ED_CONSOLE_ALLOW_NONCANONICAL_DB` before rebinding `db_mod.DB_PATH` |
| `calibration/build_trusted_anchor_proof_dataset.py` | Same pattern |

### F. Reads audits / verification (use `db.DB_PATH` or literals — **see §9**)

Examples: `audit_snapshot_data.py`, `audit_gate_labels.py`, `verify_snapshot_pipeline.py`, `verification/db_coverage.py`, `replay_bundle_coverage.py` — mixed; several still **literal** or `db.DB_PATH` only.

### G. Many scripts still **literal `data/ed_console.db`** (not migrated)

Non-exhaustive list (grep: `ed_console.db` in `*.py`): `train_compare.py`, `lstm_data.py`, `snapshot_normalizer.py`, `distance_option_a_backfill_v1.py`, `bar_rehydration_issue19_v1.py`, `db_health_audit.py`, `tools/_phase4_*.py`, `tools/bar_history_recovery_audit_v1.py`, `tools/pin_neutral_*.py`, `audit_model_readiness.py`, `arch_competition/live_drift_monitoring.py`, etc.

---

## 4. Exact files changed (this enforcement pass)

Includes new/edited policy and guards; not every historical edit is repeated here.

**Policy / core:** `db_authority.py`, `db.py`, `calibration/db_guard.py`, `calibration/paths.py`, `tests/conftest.py`

**Calibration:** `audit_phase1.py`, `analyze_phase3.py`, `analyze_phase4.py`, `anchor_audit.py`, `audit_phase1.py`, `backfill_outcomes.py`, `backfill_signal_layer_v1_bundle.py`, `canonical_enforcement.py`, `edge_discovery.py`, `edge_validation.py`, `legacy_report.py`, `repair_canonical_1m_bars_for_outcomes.py`, `signal_engineering.py`, `signal_layer_discrimination.py`, `validate_logging.py`, `validate_outcome_join.py`, harness scripts as listed

**Root / tools:** `ml_train.py`, `train_all.py`, `smoke_predict_active.py`, `backfill_snapshot_derived.py`, `pin_neutral_outcome_repair_v1.py`, `tools/issue19_rehydration_range_v1.py`, `tools/repair_validation_counts_v1.py`, `tools/run_adaptive_shadow_v2_calibration.py`

---

## 5. Enforcement / guardrail behavior

- **`cli_require_canonical_or_ack`** (`db_authority.py`): if resolved DB path ≠ canonical and `--allow-noncanonical-db` is false → **stderr** message with classification + **exit 2**.
- **`EdDB`**: refuses non-canonical paths unless `allow_noncanonical=True` or `ED_CONSOLE_ALLOW_NONCANONICAL_DB`.
- **`pick_db_path` consumers** (`edge_discovery`, `signal_engineering`): resolved path is checked after selection so **automatic harness selection** requires explicit opt-in.

---

## 6. `ED_CONSOLE_DB` policy

| Rule | Behavior |
|------|----------|
| Set to canonical file | Allowed; must **exist**. |
| Set to non-canonical file | **Blocked** at import unless `ED_CONSOLE_ALLOW_NONCANONICAL_DB=1`. |
| Unset | Uses `data/ed_console.db` resolved path. |

Accidental wrong path: **fails loudly** (`ValueError` / `FileNotFoundError`) during `db` import when `ED_CONSOLE_DB` is set.

---

## 7. Tool classification (summary)

| Class | Examples | Guard pattern |
|-------|------------|----------------|
| Read-only validators | `canonical_enforcement`, `validate_outcome_join`, `validate_logging` | CLI ack for non-canonical |
| Write-capable repairs | `backfill_outcomes`, `pin_neutral_outcome_repair_v1`, `backfill_snapshot_derived` | CLI ack + `EdDB` allow flag |
| Training | `ml_train`, `train_all` | CLI ack (DB read for features) |
| Harness-only | accumulation / proof builders | Env `ED_CONSOLE_ALLOW_NONCANONICAL_DB` + explicit `DB_PATH` rebind |

---

## 8. Proof examples (actual outcomes)

**Canonical path resolution:**

```text
$ python -c "from db_authority import canonical_console_db_path; print(canonical_console_db_path())"
C:\Users\evarg\Documents\Trading\EdWebConsole\data\ed_console.db
```

**Non-canonical blocked (exit 2):**

```text
$ python -m calibration.canonical_enforcement --db data/calibration_accumulation_validation.db
calibration.canonical_enforcement: refusing read on non-canonical DB:
  ...
Pass --allow-noncanonical-db to proceed (explicit opt-in).
EXIT:2
```

**Same with opt-in (exit 0 from guard; tool may still fail for other reasons):**

```text
$ python -m calibration.canonical_enforcement --db data/calibration_accumulation_validation.db --allow-noncanonical-db
EXIT:0
```

**Default canonical:**

```text
$ python -m calibration.canonical_enforcement
EXIT:0
```

---

## 9. Remaining issues (why FAIL)

1. **Dozens of scripts** still open SQLite via **hardcoded** `.../data/ed_console.db` (or repo-relative paths) and do **not** use `db.DB_PATH` — so they **ignore `ED_CONSOLE_DB`** unless manually aligned.
2. **Not every** audit / repair / training helper has been wired with `db_guard`; coverage is **broad for calibration + core training** but not **exhaustive**.
3. **`tools/_phase4_*.py`** and similar **ad-hoc probes** remain literal-path scripts (acceptable as dev-only if documented; **not** “globally closed”).
4. **`audit_phase1` / `calibration.paths`**: defaults now honor `ED_CONSOLE_DB` via `DEFAULT_DB`; other files listed in §3G still need the same treatment for a **PASS**.

---

## 10. FINAL RESULT

| Field | Value |
|-------|--------|
| **FINAL RESULT** | **FAIL** |
| **Canonical DB path** | `<repo>/data/ed_console.db` (see `db_authority.canonical_console_db_path()`) |
| **Dangerous non-canonical usage blocked for `EdDB` + guarded CLIs?** | **YES** (with explicit env/CLI escape hatches) |
| **Global ambiguity eliminated?** | **NO** — see §9 |

When remaining literals are migrated to `db.DB_PATH` / `calibration.paths.DEFAULT_DB` and optional `db_guard` on high-risk write CLIs, this can be reclassified to **PASS**.
