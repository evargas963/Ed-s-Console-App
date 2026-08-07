# Liquidity gamma levels experiment v1

**Pack verdict: FAIL**

- Mission: `Find & Prove — DISCUSSION/EXPERIMENT only`
- Decision path: NONE — Decide WAIT; no admission
- Tickers: `SPY, QQQ, IWM`
- Sessions scored: **195** (obs available: {"SPY": 70, "QQQ": 66, "IWM": 66})
- Date range: `2026-03-27` → `2026-07-30`
- Source: prefer morning_full, else snapshots@10:00 ET → `terrain_engine.compute_terrain`
- Faucet mix: `{"snapshots_1000et": 171, "morning_full": 27}`
- Levels: CALL_WALL, PUT_WALL, GAMMA_FLIP, GAMMA_PIN
- Labels: triple-barrier bounce, horizon=30m, k=1.0×ATR, half-width=0.25×ATR, touch after 10:15 ET, costs **ABSENT**
- Seed: `20260730`
- Runtime: 59.2s

## AGENTS.md admission

| Field | Answer |
|---|---|
| MISSION_CLASS | Find & Prove — offline gamma-level touch experiment |
| GAP | Prior pack Exp C BLOCKED on morning_full; walls/flip/pin untested as touch targets |
| SMALLEST_COMPLETE_CHANGE | `tools/liquidity_gamma_levels_experiment_v1.py` + this report |
| MINIMUM_SUFFICIENT_EVIDENCE | Same-turn harness; placebo same-width; exact n; LIMIT stated |
| DECISION_PATH_EFFECT | None — WAIT |
| WHY_NOW | Operator: use gamma levels to see how they fare |
| TASK_ADMISSION | Admitted as research/backtest only |

## Pre-registered PASS

```
{
  "min_events_per_arm": 150,
  "min_win_rate_edge_pp": 0.05,
  "min_halves_agreeing": 2,
  "min_regime_resolved": 150
}
```

High kill rate is success. Gamma levels are candidate geometry only.

## Sample LIMIT (PROVEN)

Sessions with reconstructable gamma levels: n=195 (2026-03-27→2026-07-30). Faucet mix: {'snapshots_1000et': 171, 'morning_full': 27}. GAMMA_FLIP / regime available primarily on morning_full days (TRUSTED wide chain); snapshot fill usually has walls+pin only (confidence UNAVAILABLE, flip=None). No invented levels.

- Reconstructed OK: 198; fail: 0; empty levels: 3
- Level presence (ticker-days): `{"CALL_WALL": 198, "PUT_WALL": 198, "GAMMA_FLIP": 26, "GAMMA_PIN": 198}`
- Confidence: `{"UNAVAILABLE": 171, "TRUSTED": 27}`
- Regime days: `{"SHORT_GAMMA": 27}`
- Faucets: `{"snapshots_1000et": 171, "morning_full": 27}`

## Verdicts

| Arm | Verdict |
|---|---|
| G_approach (primary) | **FAIL** |
| G_role_walls (secondary) | **FAIL** |

## Key findings (PROVEN this run)

1. **G_approach — FAIL.** real win_rate=40.9% (resolved=2205, n=2208) vs placebo=41.4% (resolved=3663); edge=-0.5%; E real=0.525 placebo=0.549. OOS halves_agree=False.
2. **G_role_walls — FAIL.** real=38.8% vs placebo=42.2%; edge=-3.4%.
3. **Regime split:** Regime split too thin for PASS gate (need ≥150 resolved/arm/regime); pooled primary stands. Per-regime numbers are descriptive only.
4. **GAMMA_FLIP:** present on 26 ticker-days (morning_full TRUSTED) but **0 post-10:15 touches** in this sample (flip typically sits outside the day's traded range). Not invented; not scored as a touch event.

## G_approach — primary (approach-side bounce)

**Verdict: FAIL**

> Do gamma structure levels (call/put wall, flip, pin) as touch zones beat random same-width zones on triple-barrier bounce labels? Direction = approach-side bounce.

- Real events: 2208 (resolved 2205)
- Placebo events: 3667 (resolved 3663)
- Real win_rate: 40.9%; placebo: 41.4%; edge: -0.5%
- Real E: 0.525; placebo E: 0.549
- Costs: ABSENT

### By level kind (real)

| kind | n | resolved | win_rate | E |
|---|---|---|---|---|
| CALL_WALL | 742 | 741 | 42.8% | 0.558 |
| PUT_WALL | 619 | 618 | 37.2% | 0.468 |
| GAMMA_FLIP | 0 | 0 | n/a | n/a |
| GAMMA_PIN | 847 | 846 | 42.0% | 0.539 |

### By regime (descriptive)

| regime | real n | real win% | placebo win% |
|---|---|---|---|
| LONG_GAMMA | 0 | n/a | n/a |
| SHORT_GAMMA | 232 | 40.5% | 40.7% |

Note: Regime split too thin for PASS gate (need ≥150 resolved/arm/regime); pooled primary stands. Per-regime numbers are descriptive only.

## G_role_walls — secondary

**Verdict: FAIL**

> Do gamma structure levels (call/put wall, flip, pin) as touch zones beat random same-width zones on triple-barrier bounce labels? Walls use role direction (call→resistance, put→support); flip/pin use approach.

- Real win_rate: 38.8%; placebo: 42.2%; edge: -3.4%
- Real E: 0.553; placebo E: 0.553

### By level kind (real, role mode)

| kind | n | resolved | win_rate | E |
|---|---|---|---|---|
| CALL_WALL | 669 | 668 | 38.3% | 0.593 |
| PUT_WALL | 554 | 553 | 34.7% | 0.525 |
| GAMMA_FLIP | 0 | 0 | n/a | n/a |
| GAMMA_PIN | 847 | 846 | 42.0% | 0.539 |

## Disposition

- Pack (primary G_approach): **FAIL**
- Decide stays WAIT. No admission.
- Reproduce: `python tools/liquidity_gamma_levels_experiment_v1.py`

## Method notes

- Placebo: same count of random centers per session inside that session's RTH high/low, same half-width (0.25×session ATR).
- No lookahead: levels from ≤10:15 ET observation; touches only after 10:15 ET.
- Costs ABSENT — any economic claim would require a cost layer.
- Fair-method: equal zone width real vs placebo; no invented levels on missing days.
