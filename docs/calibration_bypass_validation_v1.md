# Calibration bypass validation v1

Closure proof: no application path can bypass calibration constraints (`canonical_timeframe`, trusted study scope, writer-only inserts, backfill-only outcome writes) without going through controlled modules.

---

## A. Full entry / exit inventory

### A.1 Writes (`calibration_decision_log`)

| Kind | File | Function | Enforcement |
|------|------|----------|-------------|
| **INSERT (production)** | `calibration/writer.py` | `append_calibration_decision` | `canonical_timeframe` must be `1m`; `calibration_trust='trusted'`; `ON CONFLICT DO NOTHING` (idempotent) |
| **INSERT (tests only)** | `tests/test_calibration_*.py` | fixtures | Test harness — not production |
| **UPDATE (outcomes)** | `calibration/backfill_outcomes.py` | `backfill`, `_resync_existing_outcomes_from_snapshots` | `enforce_calibration_decision_log_only_1m` first; only **`calibration_trust='trusted'`** rows |
| **UPDATE (tests only)** | `tests/test_calibration_outcome_join_scale.py` | drift injection | Test-only |
| **DELETE (migration)** | `calibration/schema.py` | `_migrate_calibration_unique_ticker_decision_ts` | One-time dedupe before unique index; not runtime API |

### A.2 Reads / analysis (Python)

| File | Role | Study-trusted predicate? | Other safeguards |
|------|------|---------------------------|------------------|
| `calibration/analyze_phase3.py` | Empirical phase 3 | **Yes** — `TRUSTED_PREDICATE_SQL` on labeled rows | `enforce_calibration_decision_log_only_1m`; BAR_ANCHOR_V1 filter |
| `calibration/analyze_phase4.py` | Empirical phase 4 | **Yes** | Same |
| `calibration/validate_outcome_join.py` | Join verification | **Default yes** (`trusted_only=True`) | `--include-legacy` explicit opt-in |
| `calibration/payload_audit.py` | Payload / timestamp audit | **Yes** for metrics | `TRUSTED_PREDICATE_SQL` on study sections; totals split |
| `calibration/anchor_audit.py` | Anchor feasibility | **Yes** for calibration gate | Trusted rows for miss/`binary_pass` |
| `calibration/legacy_report.py` | Trust breakdown | N/A (full counts) | Reporting only — not a mixed study aggregate |
| `calibration/validate_logging.py` | Schema smoke test | N/A | Counts all + trusted + legacy separately |
| `calibration/validate_logging_e2e.py` | E2E row delta | N/A | Total COUNT only |
| `calibration/canonical_enforcement.py` | Binary gate | **No** (all rows) | Fails on NULL/`!=1m` timeframe — safety gate, not a study pool |
| `calibration/audit_phase1.py` | Table existence | N/A | No row reads |
| `calibration/schema.py` | DDL / migration | N/A | Schema ownership |
| `calibration/trust.py` | Constants | N/A | — |
| `signals.py` | Calls writer | N/A | **No SQL** — string literals in logs only |
| `tests/test_calibration_*.py` | Tests | Mixed | Isolated DBs |

### A.3 Production call chain for inserts

`compute_signals` → `_maybe_append_calibration_log` → `append_calibration_decision` (`calibration/writer.py`). No other production insert path exists (see §C).

### A.4 ML / training / server

**Grep closure:** No `ml_*.py`, `server`, or training module references `calibration_decision_log`. Empirical studies use `calibration/analyze_phase3|4` and related tools only.

---

## B. All detected bypass paths

| # | Description | Status |
|---|-------------|--------|
| 1 | **Non-writer INSERT in application code** | **None found** — only `writer.py` + tests |
| 2 | **Non-backfill UPDATE in application code** | **None found** — only `backfill_outcomes.py` + tests |
| 3 | **Study read without trusted filter** | **None in default paths** — phase 3/4/payload/anchor use trusted for study; `validate_outcome_join` defaults `trusted_only=True` |
| 4 | **ML/analysis importing calibration log** | **None** — no references outside `calibration/`, `tests/test_calibration*`, `signals.py` |
| 5 | **Direct SQLite file manipulation** | **Operational risk** — not enforceable in Python; DBA/console access can bypass any app rule |

Items 1–4: **no bypass** in repository Python. Item 5 is outside code closure.

---

## C. Fixes applied

1. **Mechanical tests** — `tests/test_calibration_bypass_closure.py`:
   - Any `.py` file containing `calibration_decision_log` must live under `calibration/`, `tests/test_calibration*`, or be `signals.py`.
   - `INSERT INTO calibration_decision_log` only in `calibration/writer.py` or `tests/test_calibration*`.
   - `UPDATE calibration_decision_log` only in `calibration/backfill_outcomes.py` or `tests/test_calibration*`.

2. **Existing safeguards retained** — canonical enforcement, trusted study predicates, legacy quarantine (see `docs/calibration_legacy_quarantine_v2.md`).

---

## D. Final counts (repository audit)

| Metric | Value |
|--------|------:|
| Python files referencing `calibration_decision_log` (allowlisted) | 19 |
| Files outside allowlist referencing table | **0** (enforced by test) |
| Production `INSERT` modules | **1** (`calibration/writer.py`) |
| Production `UPDATE` modules | **1** (`calibration/backfill_outcomes.py`) |
| Modules with `INSERT`/`UPDATE` violations vs allowlist test | **0** |

Files containing `calibration_decision_log` (audit snapshot):  
`calibration/analyze_phase3.py`, `calibration/analyze_phase4.py`, `calibration/anchor_audit.py`, `calibration/audit_phase1.py`, `calibration/backfill_outcomes.py`, `calibration/canonical_enforcement.py`, `calibration/legacy_report.py`, `calibration/payload_audit.py`, `calibration/schema.py`, `calibration/trust.py`, `calibration/validate_logging.py`, `calibration/validate_logging_e2e.py`, `calibration/validate_outcome_join.py`, `calibration/writer.py`, `signals.py`, `tests/test_calibration_bypass_closure.py`, `tests/test_calibration_legacy_quarantine.py`, `tests/test_calibration_logging_production_path.py`, `tests/test_calibration_outcome_join_scale.py`.

---

## E. PASS / FAIL

**FINAL: PASS**

| Gate | Result |
|------|--------|
| Bypass paths in application Python | **0** |
| Unauthorized reference to `calibration_decision_log` | **0** (test-enforced) |
| INSERT/UPDATE outside controlled modules | **0** (test-enforced) |

**Remaining unclosed risk (documented only):** direct SQLite access to the database file.

---

## Validation commands / results

```bash
python -m pytest tests/test_calibration_bypass_closure.py tests/test_calibration_legacy_quarantine.py tests/test_calibration_outcome_join_scale.py tests/test_calibration_logging_production_path.py -q
```

```text
14 passed
```
