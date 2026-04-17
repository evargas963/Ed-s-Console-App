# Calibration master report — v1

**Scope:** Institutional calibration pipeline (Phases 1–5) for the Ed predictive stack.  
**Canonical clock:** `1m` (`timeframe_config.CANONICAL_TIMEFRAME`).  
**Distance contract:** Option A — non-negative `nearest_above_dist` / `nearest_below_dist`; direction by field name.

---

## Executive summary

The repository now contains **reproducible audits**, a **persistent calibration log schema + write path**, and **analysis scripts** for empirical threshold tuning, decision validation, and adaptive-weighting groundwork. On the **current** SQLite extract in this workspace:

- **Data integrity:** Canonical `1m` rows satisfy Option A distances; **no** ticker fragmentation for index-style keys in the audited sample. A **large legacy `5m` snapshot pool** must be **excluded** from calibration queries. Roughly **23%** of sampled snapshots lack a completed `price_bars_1m` anchor at or before `ts_utc` — **needs** ticker-level remediation before bar-anchored claims.
- **Logging:** Table + writer + backfill are implemented; the log is **empty** until `ED_CALIBRATION_LOG=1` runs in production/replay.
- **Calibration / decisions:** Full fusion-to-outcome metrics require **populated `calibration_decision_log`**. Snapshot-only baselines show finite mean 5c moves under naive rules; **they do not validate** the fused decision layer until the same rows exist in the log.

---

## Methodology

1. **Phase 1:** `python -m calibration.audit_phase1` → JSON artifact under `models/calibration_runs/`.
2. **Phase 2:** `ED_CALIBRATION_LOG=1` → inserts into `calibration_decision_log`; `python -m calibration.backfill_outcomes` joins outcomes from `snapshots`.
3. **Phase 3:** `python -m calibration.analyze_phase3` — reliability, Brier (when canonical JSON present), regime buckets, fusion threshold grid, probability-bucket expectancy; **fallback** to `snapshots.combined_*` when the log is empty (clearly labeled).
4. **Phase 4:** `python -m calibration.analyze_phase4` — decision PnL proxy, MHAP buckets, naive baselines from snapshots.
5. **Phase 5:** Documented framework only — **no** production weight changes.

All metrics are required to show **sample counts** or state **insufficient data**.

---

## Dataset integrity (Phase 1 highlights)

| Item | Result |
|------|--------|
| `1m` snapshot rows | 55,371 (same run as Phase 1 artifact) |
| `5m` snapshot rows | 103,109 — **do not mix** with canonical calibration |
| Option A negative distances | **0** violations |
| Symbol fragmentation (`ticker_storage_key`) | **0** |
| Anchor bar availability (5k random sample) | **22.6%** missing anchor — **uncertain / investigate** |
| Outcome null rate `outcome_5c` (all 1m rows) | ~**60.8%** — expect until horizons fill |

---

## Logging layer status (Phase 2)

- **Schema:** `calibration/schema.py`
- **Write path:** `signals._maybe_append_calibration_log` → `calibration.writer.append_calibration_decision`
- **Backfill:** `calibration.backfill_outcomes`
- **Gate:** Environment variable `ED_CALIBRATION_LOG`

---

## Calibration findings (Phase 3)

With an **empty** calibration log, primary fusion calibration metrics are **not available**. The snapshots fallback confirms **21,703** labeled rows can be joined for coarse `combined_*` analysis; most stored signals are **`wait`**, so **directional sample counts for tiered confidence are not yet credible**.

**Action:** Populate the log, backfill, re-run Phase 3.

---

## Threshold findings (Phase 3)

Fusion **threshold grid** results require `fusion_confidence_score` in stored `fusion_json`. **Deferred** until log population.

---

## Model / regime findings

**Regime-stratified** performance tables will populate from `regime_primary` × outcomes in the log. **Not yet measured** at institutional sample depth.

---

## Decision validation (Phase 4)

| Baseline (n≈21.7k 1m labeled snapshots) | Mean 5c pts (proxy) |
|----------------------------------------|----------------------|
| Always-up | +0.053 |
| Always-down | −0.498 |
| VWAP MR heuristic (crude) | +0.404 |

**Decision log performance:** **Not evaluated** — log empty.

---

## Known limitations

1. **Calibration log not yet populated** — primary blocker for fusion-level proof.
2. **5m legacy pool** in `snapshots` — strict SQL filters required everywhere.
3. **Anchor coverage gaps** — 23% in random sample; may bias bar-anchored similarity if not handled.
4. **Feature-time leakage** — not disproven by SQL; requires replay harness.
5. **MHAP parsing** — depends on exact `alignment_state` strings; verify against runtime if metrics stay at zero.

---

## Recommended next actions (strict priority)

1. **Run the console with `ED_CALIBRATION_LOG=1`** on a defined window (paper or replay) until `calibration_decision_log` has sufficient rows per regime × structure bucket.
2. **Run `calibration.backfill_outcomes`** after `fill_outcomes` stabilizes; verify join tolerance per ticker.
3. **Re-run Phase 3–4** and replace fallback sections in this report with log-based metrics (Brier, reliability, decision PnL, MHAP).
4. **Per-ticker anchor audit** for symbols in the trading universe — reduce the 23% anchor-miss rate or exclude those intervals from bar-anchored studies.

---

## References (code)

- `calibration/audit_phase1.py`
- `calibration/schema.py`, `calibration/writer.py`, `calibration/backfill_outcomes.py`
- `calibration/analyze_phase3.py`, `calibration/analyze_phase4.py`
- `signals.py` (`_maybe_append_calibration_log`)
- `timeframe_config.py`, `horizon_outcomes.py`, `instrument_identity.py`
