# RC-437 — OI/vanna wall-distance adjudication (Path A vs Path B)

**MISSION_CLASS:** Decide (architecture adjudication) — not a live ML restore  
**GAP:** RC-435/436 left the active ML fleet fail-closed dark; before host retrain, choose whether to **retire** the four OI/vanna wall-distance features (A) or **establish one canonical producer** inside the terrain/structural book (B).  
**SMALLEST_COMPLETE_CHANGE:** This adjudication + REPORT-ONLY vs enforcement distinction + lock that RC-436 cannot CLOSE while the fleet still requires withheld distances.  
**MINIMUM_SUFFICIENT_EVIDENCE:** Same-turn `python ./tools/measure_rc435_abstain_impact.py`; terrain/CONSENSUS code inspection; XGB gain on SPY 1c; empty decision-path admissions; liquidity research forbidding OI-wall scoring of GEX experiments.  
**DECISION_PATH_EFFECT:** None until Path A retrain/promote — Decide stays rules-engine on withheld live ticks (RC-435).  
**WHY_NOW:** Operator: do not assume “drop four features”; adjudicate A vs B before host retrain; restore honest useful ML, not merely silence the abstain gate.  
**TASK_ADMISSION:** Adversarial auditor packet under RC-437; RC-436 remains OPEN until live fleet restore is proven.

## Verdict

**Recommend Path A — retire the four OI/vanna wall-distance features from the model feature contract, then host-retrain/promote under `model_feature_wall_distance_cols()` + schema bump.**

Path B is **not** justified as the permanent institutional answer *now*. It remains a **Find & Prove** candidate only if a future prereg proves predictive value for a *terrain-native* stock-OI (or true vanna-structure) wall definition — never by reviving the selected-expiry competing book.

## Criteria scorecard

| Criterion | Path A (retire) | Path B (canonical producer) |
|---|---|---|
| Predictive value | Modest non-zero XGB gain on SPY 1c (~0.6–0.9% per withheld `*_pct` feature; same-turn booster `get_score(gain)`). Not proven OOS edge; `decision_path_admissions.json` admissions=`[]`. | Would need enrolled-universe, wide-chain, placebo-controlled prereg before Decide/ML. No admission today. |
| Semantic correctness | Retires names that no longer mean what live CONSENSUS/KL paint (walls are `None`). Avoids “distance to a withheld wall.” | Stock max-OI wall can be a real concept; “vanna wall” as max \|vanna\| strike was phantom-prone (RC-422). Must be redefined inside `compute_terrain`, not selected-expiry pickers. |
| Train/serve consistency | A restores consistency: train without columns that are always absent live. | B restores consistency only after terrain produces walls, CONSENSUS binds them, encode persists distances, then retrain. |
| Complexity | Low: contract shrink + host retrain/promote (already prepared helper). | High: terrain producer, bind, overlay, encode, schema, Prove, then retrain. |
| ONE FAUCET | A removes a dead second meaning. ΔOI walls (`compute_delta_oi_walls` / overnight build-unwind) remain the OI structural story already in the book. | B is legal only as **one** terrain computation feeding CONSENSUS + distances — never a parallel selected-expiry book. |

## Evidence (same-turn / in-repo)

1. **Fleet dark (RC-436 measure, REPORT-ONLY exit 0):**
   - `xgb_triclass_active=32 require_withheld=32 live_gate_true=32 by_hz={'1c':14,'5c':9,'15c':9}`
   - `serveable_lstm=5 live_gate_true=5 serveable_transformer=5 live_gate_true=5`
   - Reproduce: `python ./tools/measure_rc435_abstain_impact.py`

2. **No terrain OI/vanna wall keys:** `terrain_engine.py` count of `call_oi_wall` / `put_oi_wall` / `vanna_wall` = 0. Terrain does expose `oi_by_strike`, `vanna_agg`, gamma/delta/charm walls, and **ΔOI** walls via `math_exposure_core.compute_delta_oi_walls` (different product).

3. **CONSENSUS bind:** `math_levels.consensus_walls_bind_terrain_ssot` hard-sets call/put OI and vanna walls/strengths to `None` (RC-422 ONE FAUCET).

4. **Research:** `reports/liquidity_experiment_input_audit_v1.md` — gamma experiments must **not** score OI walls; levels = GEX$ via `compute_terrain`.

5. **Charter:** empty admissions registry — unadmitted influence must not drive TRADE.

6. **Forbidden revival:** selected-expiry max-OI vs wide-chain divergence was the RC-422 defect (measured 750 vs 760 class). Reviving that book to light old models fails ONE FAUCET and semantic honesty.

## Path A implementation sequence (does **not** close RC-436)

1. Keep RC-435 abstain until new artifacts land (interim honesty).
2. Operator-host (this cloud DB is empty — `snapshots_1m_normalized` COUNT(*)=0): retrain enrolled universe with wall distances = `model_feature_wall_distance_cols()` (excludes the four bases).
3. Co-land in the **same** promote commit: wire live `WALL_DISTANCE_COLS` / sequence `FEATURES_*` to that list + `FEATURE_SCHEMA_VERSION` bump + promote only artifacts that pass existing institutional model gates (no manual `models/active/` copy).
4. Prove artifacts: `python ./tools/prove_path_a_ml_restore.py` → exit 0 / `RESTORED=1` (ENFORCEMENT — not the REPORT-ONLY measure tool).
5. Prove live stack: `python ./tools/prove_path_a_ml_restore.py --require-stack-probs` → exit 0 on the operator-host console. The prove calls `ml_predict.predict_direction` → `run_unified_stack_ml_once` (same authority as `signals`) against the latest Collect snapshot row and requires a complete `stack_probs` triplet; optional `--via-api` corroborates live `/api/analytics/state` `ml_layer_probs`. Rules-only / missing helper soft-pass is not restore.
6. Then CLOSE RC-436 (enforcement lock refuses earlier CLOSE; artifact creation alone is insufficient).
7. Do **not** start RC-423 work until RC-436 restore is proven unless a hard blocker makes Path A progress impossible (empty cloud DB is such a blocker **for cloud agents only** — host is unblocked).

## Path B (deferred Find & Prove only)

If pursued later: define wall semantics on the **wide-chain terrain book**, implement inside `compute_terrain`, bind CONSENSUS from that cache only, prereg + OOS vs placebo, admit before Decide, then introduce distances under a **new** schema. Do **not** re-enable selected-expiry OI/vanna pickers.

## Measure vs enforcement (RC-437)

| Surface | Role | Exit / gate |
|---|---|---|
| `tools/measure_rc435_abstain_impact.py` | **REPORT-ONLY** fleet measurement | Completes → **exit 0** always |
| `tools/ml_fleet_restore_lock.py` + `check_rc436_closed_requires_ml_fleet_restore` | **ENFORCEMENT** | Staging/closing RC-436 as CLOSED while active metas still list withheld `*_pct` → **BLOCK** |
| `tools/prove_path_a_ml_restore.py` | **ENFORCEMENT** host accept | Exit 1 until artifacts clean; `--require-stack-probs` exercises `predict_direction` → `run_unified_stack_ml_once` (real `stack_probs`, no synthetic helper) |

## Status

- **Adjudication:** COMPLETE (this report + RC-437).  
- **Live ML restore:** NOT_PROVEN — tracked by **RC-436 OPEN**.
