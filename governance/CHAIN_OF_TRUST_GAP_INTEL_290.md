# Chain-of-trust gap intel (preserved from rejected `61358a6`)

**Status:** Intel only — not a closure gate. Produced by categorical-inventory resolver before Commit 1 restart.

**Scan:** 580 consumer reads in §4, §6, §7, §10, §11, §13, §14, §16. **290 gaps** (no structured producer link).

**Priority fields (spot, walls, IV, MVP):** closed under override tables — confirms contamination risk is in snapshot/outcome/nearest_* paths, not headline price fields.

## Representative gap categories (remediation backlog for TraceableDerivation migration)

| Category | Examples | Remediation direction |
|---|---|---|
| Snapshot structural | `snapshot.zone`, `snapshot.vwap_side`, `snapshot.nearest_*` | Link to `build_market_state` / inference snapshot producers with `FieldInputRef` |
| Snapshot identity | `snapshot.ticker`, `snapshot.ts_utc`, `snapshot.id` | PASS_THROUGH from DB row or `build_inference_snapshot_v1` |
| Outcomes | `snapshot.outcome_1c`, `snapshot.outcome_15c_pts` | `db.fill_outcomes` / bar-anchor chain |
| MVP meta | `mvp.meta.n_bars` | Fusion metadata — allowlist or explicit producer |
| Calibration | `snapshot.decision_ts_utc`, `snapshot.raw_probability` | Writer/reader inventory with structured inputs |

Re-run after §A–§Q inventories use `TraceableDerivation` and `assert_chain_closes` (future §D gate).
