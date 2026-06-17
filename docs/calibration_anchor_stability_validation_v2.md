> **Classification:** Historical Record | **Scope:** Completed analysis or validation `docs/calibration_anchor_stability_validation_v2.md`.

# Calibration anchor stability validation v2

Proves BAR_ANCHOR_V1 behavior for **trusted** `calibration_decision_log` rows as volume grows: full per-row audit (not sampled), breakdowns by ticker / session / UTC date / RTH, root-cause taxonomy for misses, and proof that **empirical phase 3/4 never consume unanchored trusted rows**.

---

## A. Exact files changed

| File | Change |
|------|--------|
| `calibration/anchor_audit.py` | Added `_audit_trusted_calibration_anchors()` — scans **all** trusted calibration rows; metrics `calibration_trusted_anchor_audit` (by ticker, session, UTC date, RTH, root causes); `empirical_study_note` on `calibration_decision_log` summary. |
| `tests/test_calibration_anchor_stability.py` | **New:** unanchored trusted row excluded from phase 3 labeled sample; anchored row included; asserts audit JSON shape. |
| `docs/calibration_anchor_stability_validation_v2.md` | This document. |

---

## B. Current trusted-row counts (definitions)

| Metric | Source |
|--------|--------|
| Total trusted calibration rows | `COUNT(*)` where `calibration_trust='trusted'` and `canonical_timeframe='1m'` |
| Trusted with anchor (BAR_ANCHOR_V1) | `calibration_trusted_anchor_audit.trusted_rows_with_anchor` |
| Trusted without anchor | `calibration_trusted_anchor_audit.trusted_rows_without_anchor` |

**Production:** run `python -m calibration.anchor_audit --db <path> --full-scan` (or default snapshot sample + **full** trusted calibration audit — trusted block is always a full table scan of trusted rows).

---

## C. Anchor count / miss tables (structure + deterministic fixtures)

### C.1 JSON keys (`calibration_trusted_anchor_audit`)

| Field | Meaning |
|-------|---------|
| `trusted_rows_total` | All trusted rows audited |
| `trusted_rows_with_anchor` | `EXISTS bar_end_ts_utc <= decision_ts_utc` for `ticker_storage_key(ticker)` |
| `trusted_rows_without_anchor` | Misses |
| `anchor_miss_rate_overall` | `misses / total` |
| `by_ticker` | Per normalized ticker: `n`, `miss`, `miss_rate` |
| `by_market_session_bucket` | From `snapshots` join on `(ticker, ts_utc)` when present; else `unknown` |
| `by_utc_date` | `per_date`: full list of UTC dates with `n`, `miss`, `miss_rate`; `date_range_utc` |
| `by_rth_bucket` | `rth` vs `non_rth_or_unknown` from snapshot `market_session` |
| `root_cause_counts_trusted_calibration_misses` | Only for misses — see §D |
| `root_cause_miss_sum_check` | `true` iff subcauses sum to `trusted_rows_without_anchor` |

### C.2 Deterministic test fixtures (captured)

**Fixture A — unanchored trusted row (no `price_bars_1m` for SPY):**

| Metric | Value |
|--------|------:|
| trusted_rows_total | 1 |
| trusted_rows_with_anchor | 0 |
| trusted_rows_without_anchor | 1 |
| anchor_miss_rate_overall | 1.0 |

**Fixture B — anchored trusted row (`price_bars_1m` with `bar_end_ts_utc=1990` ≤ `decision_ts_utc=2000`):**

| Metric | Value |
|--------|------:|
| trusted_rows_total | 1 |
| trusted_rows_with_anchor | 1 |
| trusted_rows_without_anchor | 0 |
| anchor_miss_rate_overall | 0.0 |

Tests: `tests/test_calibration_anchor_stability.py`.

---

## D. Root-cause breakdown (trusted calibration misses only)

Mutually exclusive buckets (same logic as snapshot audit):

| Key | Cause |
|-----|--------|
| `no_rows_price_bars_1m_for_norm_ticker` | No bar history for `ticker_storage_key(ticker)` (symbol normalization / no history ingested). |
| `decision_ts_before_earliest_bar_end_retained_history_boundary` | Earliest retained `bar_end_ts_utc` is after `decision_ts_utc` (cold start / history backfill boundary). |
| `sparse_gap_or_anomaly_no_bar_end_lte_ts` | Bars exist and `decision_ts` is after first bar end, but no `bar_end <= ts` (sparse gap or clock anomaly). |

**Session / RTH:** If no matching `snapshots` row at the same `(ticker, ts_utc)`, session is `unknown` and RTH bucket is `non_rth_or_unknown` — not a miss cause, only a classification dimension.

---

## E. Full workflow inventory (calibration + anchor)

| Workflow | Consumes calibration rows? | Anchor enforcement |
|----------|---------------------------|-------------------|
| `calibration/analyze_phase3.py` `analyze` | Yes — trusted, `outcome_5c` set | **Only** rows where `snapshot_has_bar_anchor(conn, ticker, decision_ts_utc)`; unanchored counted in `excluded_by_reason.rows_without_bar_anchor_BAR_ANCHOR_V1` |
| `calibration/analyze_phase4.py` `analyze` | Yes — trusted, `outcome_5c` set | Same as phase 3 |
| `calibration/backfill_outcomes.py` | Read/update trusted | Does not require anchor for attach (outcomes from snapshots); resync uses snapshot row |
| `calibration/validate_outcome_join.py` | Verify outcomes vs snapshot | Independent of anchor; **not** used for BAR label eligibility |
| `calibration/anchor_audit.py` | Reporting / gate | Full trusted calibration audit; `binary_pass` = zero missed anchors (strict CLI) |
| `calibration/payload_audit.py` | Trusted payload stats | Not anchor-based |
| `calibration/legacy_report.py` | Counts | Reporting only |
| ML / training modules | **None** read `calibration_decision_log` | N/A |

---

## F. Proof of quarantine / fail-closed behavior

1. **Phase 3/4:** `rows_raw` is filtered by `TRUSTED_PREDICATE_SQL`, then each row is dropped unless `snapshot_has_bar_anchor(...)` returns true. Unanchored trusted rows **never** increase `labeled_sample_count`.

2. **Tests:** `test_unanchored_trusted_row_excluded_from_phase3_labeled_sample` — `calibration_rows == 0` with `outcome_5c` present but no bars; `test_anchored_trusted_row_passes_anchor_audit_and_enters_phase3_sample` — `calibration_rows == 1` when a bar exists.

3. **Accumulation:** `calibration_trusted_anchor_audit` iterates **every** trusted row (no sampling), so metrics stay valid as trusted rows accumulate.

4. **CLI:** `python -m calibration.anchor_audit --workflow-safe` exits 0 even if `binary_pass` is false (misses exist), because empirical studies still exclude unanchored rows — documented in `calibration_decision_log.empirical_study_note`.

---

## G. FINAL: **PASS**

| Gate | Result |
|------|--------|
| Active empirical workflows cannot consume unanchored trusted rows unsafely | **PASS** (phase 3/4 anchor filter + tests) |
| Trusted-row anchor behavior explained and measurable at full trusted scale | **PASS** (`calibration_trusted_anchor_audit`) |
| No unsafe dependency remains | **PASS** |

**Remaining issues:** **NONE** (for in-app behavior). **Operational:** direct SQL edits to `calibration_decision_log` could bypass logic — not addressed in application code.

---

## Validation commands / results

```bash
python -m pytest tests/test_calibration_anchor_stability.py tests/test_calibration_legacy_quarantine.py tests/test_calibration_outcome_join_scale.py tests/test_calibration_logging_production_path.py tests/test_calibration_bypass_closure.py -q
```

```text
16 passed
```

**Production audit:**

```bash
python -m calibration.anchor_audit --db <path> --full-scan
```

Inspect JSON key `calibration_trusted_anchor_audit`.
