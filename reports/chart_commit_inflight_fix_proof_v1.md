# Chart `_chartCommitInflight` orphan fix — proof v1

**Date:** 2026-07-31  
**Verdict:** **YES — crash fix 100% committed and live-proven.**  
**Residual (not a crash):** Enter-key ticker commit UX (`commitChartTicker`) is still absent.  
**Decide:** WAIT (no decision-path admission change).  
**Scope:** UNIVERSAL (SPY + QQQ/IWM + AAPL non-sentinel).  
`# chart-intent-ok: crash-path proof only; Chart OV/GEX paint proven via CDP + API this turn.`

## AGENTS admission (this task)

| Field | Answer |
|---|---|
| MISSION_CLASS | Collect / Chart consumer integrity (render path must not throw) |
| GAP | Committed `load()` cleared undeclared `_chartCommitInflight` after hunk-filter stripped `commitChartTicker` |
| SMALLEST_COMPLETE_CHANGE | Delete the orphan assignment; comment RC-164; commit `static/chart.html` only |
| MINIMUM_SUFFICIENT_EVIDENCE | Zero code refs; Node parse OK; CDP `load()` no throw + `#gv` paint; API OV/GEX non-empty; HEAD SHA clean |
| DECISION_PATH_EFFECT | None (WAIT) |
| WHY_NOW | Operator: make sure this is 100% fixed; uncommitted crash fix ≠ 100% |
| TASK_ADMISSION | Admitted — protects Chart paint from hard ReferenceError |

## 1) Git state (PROVEN)

| Check | Result |
|---|---|
| Pre-fix | Worktree dirty: `M static/chart.html` (+7/−1); HEAD `e78732ca` still had `if (_chartCommitInflight === tk) _chartCommitInflight = null;` |
| Diff | Only that orphan line → RC-164 comment block |
| **Commit SHA** | **`6c47b89bdcb4daa75842a1edcc43205d454a3191`** |
| Message | `RC-164: remove orphan _chartCommitInflight that crashed Chart load().` |
| HEAD after | `HEAD_orphan_assign False`, `HEAD_rc164_comment True` |
| Push | **Not pushed** (operator: no push) |

## 2) Code refs (PROVEN)

| Symbol | Non-comment code refs in `static/chart.html` | Repo code that throws |
|---|---|---|
| `_chartCommitInflight` | **0** (comments only under RC-164) | **0** |
| `commitChartTicker` | **0** | **0** |

**Enter-UX residual:** No `keydown` / Enter handler for `#tk`. Operator previously wanted Enter; restoring the full `commitChartTicker` + `_chartCommitInflight` guard block is a separate residual — inventing only the variable would fake guard state. Current UX: `#tk` `change` event still calls `load()`.

## 3) Syntax (PROVEN)

```
node: script_blocks=1; script[0]: OK len=77143
```

(Python `compile` of JS is not valid; Node `new Function` is the authority.)

## 4) Live prove (PROVEN — console on `:8000`, not `:9411`)

### Served HTML

- `GET http://127.0.0.1:8000/chart` → 200, LEN=86569  
- Served body: orphan assign **absent**, RC-164 comment **present** (worktree served before commit; commit matches that body)

### `/api/terrain/strikes` — same-turn OV/GEX (`[strike, gex, ov]` rows)

Reproduce: `python scratchpad/_chart_inflight_ov_probe.py`

| Ticker | today_source | n_all | ov_sum | ov_nz | gex_nz | spot |
|---|---|---:|---:|---:|---:|---:|
| SPY | terrain_live_cache | 202 | 991234 | 151 | 202 | 742.715 |
| QQQ | terrain_live_cache | 214 | 753707 | 147 | 211 | 688.06 |
| IWM | terrain_live_cache | 88 | 98563 | 57 | 88 | 292.17 |
| AAPL | accrual_bank:0581et | 41 | 363972 | 41 | 41 | 304.91 |

All non-empty OV+GEX; non-sentinel AAPL on banked source.

### CDP browser (PROVEN)

Reproduce: `node scratchpad/_chart_inflight_cdp_proof.js` → artifact `scratchpad/_chart_inflight_cdp_proof.json`

- `load()` after navigate: `errs=[]`, `loadErr=null`, `strikesN=201`, `gvPaintNonEmpty=true`
- `typeof _chartCommitInflight === 'undefined'` (no fake redeclare)
- `#gsrc` SPY: `today: terrain_live_cache · …`
- AAPL via `change`+`load()`: `strikesN=41`, `today_source=accrual_bank:0581et`, no orphan throw
- Verdict: **PASS**

## 5) RC-156 / 157 / 162 still present (PROVEN)

| Piece | Evidence |
|---|---|
| RC-156 `#rawlevels` | DOM id present; CDP `rawlevelsPresent=true` |
| RC-157 `flex:none` | CSS `#rawlevels { flex:none; … }`; CDP computed `flex: 0 0 auto` (grow/shrink 0) |
| RC-162 BANKED / `gsrc` | Source contains `BANKED — session accrual` branch + `#gsrc`; AAPL `today_source` starts with `accrual_bank:` (live gsrc text can show PAUSED aging copy when refresh deferred — bank reader path still live) |

## 6) Other orphan scan (PROVEN)

- HEAD-before had exactly one thrower: `_chartCommitInflight` assign in `load()`.
- Heuristic underscore suspects `_f` / `_s` are **local `const`** in `load()` (not orphans).
- No other hunk-filter orphan identifiers found on the load/draw path.

## Drift-audit (this turn)

1. **Intent:** Operator wanted crash 100% fixed (committed + proven), not Claude prose.  
2. **Mechanical:** Node parse; grep zero code refs; CDP load; API OV; commit SHA verified.  
3. **Failure-class checklist:**  
   - Presence vs capability: OPERATIVE — CDP `load()` + paint.  
   - Silent-swallow: none added.  
   - Fail-closed: removed fake state rather than declaring empty guard.  
   - Stale vs live: live `:8000` + CDP this turn.  
   - Side-channel: Enter UX intentionally not faked.  
   - Patch/gate-relax: none.  
4. **Completeness critic:** Clean-checkout crash was the gun — fixed by commit. Enter-UX restore is named residual, not claimed Done. Browser MCP unavailable; CDP script substituted (same class of proof).  
5. **Verdict:** CLEAN for crash fix; residual Enter-UX open.  
6. **Self-correct:** No new gate bloat (rule 01); proof report + commit message document the hunk-filter class.  
7. **Sign-off:** drift-audit run; findings: Enter-UX residual only; corrections: committed orphan delete; gate hardened: n (lean).

## Remaining guns

1. **Enter-UX residual** — restore full `commitChartTicker` + `_chartCommitInflight` guard if operator still wants Enter-to-commit (not required for load crash).  
2. None remaining on the `_chartCommitInflight` ReferenceError path.
