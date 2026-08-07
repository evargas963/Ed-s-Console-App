# Liquidity gamma hold / horizon experiments v1

**Pack verdict: FAIL**

- Mission: `Find & Prove — DISCUSSION/EXPERIMENT only`
- Decision path: NONE — Decide WAIT; no admission
- Tickers: `SPY, QQQ, IWM`
- Sessions scored: **195** (obs available: {"SPY": 70, "QQQ": 66, "IWM": 66})
- Date range: `2026-03-27` → `2026-07-30`
- Faucet mix: `{"snapshots_1000et": 171, "morning_full": 27}`
- Seed: `20260730` · Runtime: 50.9s
- Costs: **ABSENT** · No lookahead (obs ≤10:15; score after 10:15 ET)

Discussion (plain English): `reports/liquidity_gamma_storm_discussion_v1.md`

## AGENTS.md admission

| Field | Answer |
|---|---|
| MISSION_CLASS | Find & Prove — offline hold/horizon/regime gamma experiments |
| GAP | Prior bounce pack FAIL; magnet/hold + multi-horizon + morning_full flip untested |
| SMALLEST_COMPLETE_CHANGE | `tools/liquidity_gamma_hold_horizon_experiments_v1.py` + this report |
| MINIMUM_SUFFICIENT_EVIDENCE | Same-turn harness; placebo; exact n; LIMITs stated |
| DECISION_PATH_EFFECT | None — WAIT |
| WHY_NOW | Operator asked experiments #3/#4/#7 + storm discussion |
| TASK_ADMISSION | Admitted as research/backtest only |

## Pre-registered PASS

```
{
  "min_events_per_arm": 150,
  "min_hold_edge_pp": 0.05,
  "min_win_rate_edge_pp": 0.05,
  "min_halves_agreeing": 2,
  "min_regime_resolved": 150,
  "min_morning_full_days_per_ticker": 20
}
```

## Sample LIMIT (PROVEN)

Sessions with reconstructable gamma levels: n=195 (2026-03-27→2026-07-30). Faucet mix: {'snapshots_1000et': 171, 'morning_full': 27}. morning_full exact: SPY=9, QQQ=9, IWM=9. No invented levels / no invented future accrual.

### morning_full exact day counts (PROVEN `COUNT(*)` trading days)

| ticker | n_days | date_min | date_max | meets_ops_≥20 |
|---|---|---|---|---|
| SPY | 9 | 2026-07-20 | 2026-07-30 | False |
| QQQ | 9 | 2026-07-20 | 2026-07-30 | False |
| IWM | 9 | 2026-07-20 | 2026-07-30 | False |

- Level presence (ticker-days): `{"CALL_WALL": 198, "PUT_WALL": 198, "GAMMA_FLIP": 26, "GAMMA_PIN": 198}`
- Confidence: `{"UNAVAILABLE": 171, "TRUSTED": 27}`
- Regime days (all faucets): `{"SHORT_GAMMA": 27}`

## Verdicts

| Experiment | Verdict |
|---|---|
| E3 session respect (magnet/hold) | **FAIL** |
| E3 touch-and-hold | **FAIL** |
| E4 flip + regime | **BLOCKED** |
| E7 multi-horizon (any PASS?) | **FAIL** |
| Pack | **FAIL** |

## E3 — Wall-hold / magnet (not bounce)

### E3a session respect

**Verdict: FAIL**

> Given morning CALL_WALL / PUT_WALL / PIN, when post-10:15 price approaches within 0.5×ATR, does the session hold (no close-through by 0.25×ATR / pin-close magnet) better than same-distance random levels?

- Real approached events: n=273, hold_rate=5.1%
- Placebo: n=291, hold_rate=15.8%
- Edge: -10.7%
- Mean MAE (ATR, real/placebo): 10.598 / 9.280
- OOS halves_agree: False
- Costs: ABSENT

| kind | n | hold_rate |
|---|---|---|
| CALL_WALL | 76 | 7.9% |
| PUT_WALL | 76 | 6.6% |
| GAMMA_PIN | 121 | 2.5% |

### E3b touch-and-hold vs break-and-go

**Verdict: FAIL**

> On first post-10:15 zone touch, does price avoid close-through within 30m more often than same-distance placebo?

- Real: n=2460, hold_rate=11.5%
- Placebo: n=2650, hold_rate=13.2%
- Edge: -1.8%
- OOS halves_agree: False

| kind | n | hold_rate |
|---|---|---|
| CALL_WALL | 815 | 20.1% |
| PUT_WALL | 709 | 16.4% |
| GAMMA_PIN | 936 | 0.2% |

## E4 — morning_full / flip + regime

**Verdict: BLOCKED**

> On TRUSTED morning_full (+ causal snapshot fill for walls), do flip touches exist and does wall-hold differ by LONG/SHORT gamma?

- Ops note: Accrue to N≥20 TRUSTED morning_full days/ticker is an ops Collect target — not synthetic history.
- morning_full regime days: `{"SHORT_GAMMA": 27}`
- All-faucet regime days: `{"SHORT_GAMMA": 27}`
- Flip touches real n=0 (placebo n=21); verdict=BLOCKED

### LIMITS

- morning_full days/ticker below ops target 20: SPY=9, QQQ=9, IWM=9. Accrue more TRUSTED morning_full sessions (ops) — do not invent.
- GAMMA_FLIP post-10:15 touches = 0 in this sample (flip typically outside traded range). Flip bounce arm BLOCKED.
- LONG_GAMMA reconstructed days = 0 in scored sample (SHORT_GAMMA days=27; morning_full regime days LONG=0 SHORT=27). Regime split one-sided; SHORT-only wall-hold numbers are descriptive with caveat.
- Regime-conditional hold n below PASS min_regime_resolved=150; no PASS claim on regime split.

### Wall-hold by regime (descriptive if thin)

| regime | real n | real hold% | placebo hold% | edge |
|---|---|---|---|---|
| LONG_GAMMA | 0 | n/a | n/a | n/a |
| SHORT_GAMMA | 12 | 8.3% | 14.3% | -6.0% |

## E7 — Multi-horizon barriers (same zones)

**Pack (any horizon PASS?): FAIL**

> On the same morning gamma zones, do 15m / 60m / EOD triple-barrier bounce labels beat placebo, and does horizon change FAIL→PASS?

| horizon | real win% | placebo win% | edge | resolved real/plac | halves_agree | verdict |
|---|---|---|---|---|---|---|
| 15m | 41.1% | 41.8% | -0.8% | 2194/3626 | False | **FAIL** |
| 60m | 40.9% | 42.8% | -1.9% | 2206/3684 | False | **FAIL** |
| EOD | 40.9% | 41.7% | -0.8% | 2206/3608 | False | **FAIL** |

Horizon changes FAIL→PASS? **NO** (map: `{"15m": "FAIL", "60m": "FAIL", "EOD": "FAIL"}`).

## Disposition

- Pack: **FAIL**
- Decide stays WAIT. No admission.
- Reproduce: `python tools/liquidity_gamma_hold_horizon_experiments_v1.py`

## Method notes

- E3 placebo: same |distance from morning spot| as real wall/pin, role-preserving scoring.
- E7 placebo: uniform random centers in session RTH high/low, same half-width.
- Fair-method: equal zone width; approached-only for session hold rates; no invented morning_full days.
- Magnet ≠ bounce: PIN held = session close near pin; walls held = no close-through after approach.
- Pos vs neg gamma: absorb/pin vs accelerate is literature-supported directionally; Ed sample here is SHORT-heavy — see E4 LIMITS.
