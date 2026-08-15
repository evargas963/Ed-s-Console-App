# Liquidity synthesis experiments v1

**Pack verdict: ALL_FAIL_OR_BLOCKED**

- Mission: `Find & Prove — DISCUSSION/EXPERIMENT only`
- Decision path: NONE — Decide WAIT; no admission
- LP-01 touch→magnitude: FAIL locked — not reopened
- Tickers: `SPY, QQQ, IWM`
- Sessions: **298** (exact pack count)
- Date range: `2026-02-23` → `2026-07-30`
- Bars loaded: SPY=106891, QQQ=94667, IWM=81784
- Labels: triple-barrier, horizon=30m, k=1.0×ATR, costs **ABSENT**
- Seed: `20260730`

## AGENTS.md admission

| Field | Answer |
|---|---|
| MISSION_CLASS | Find & Prove — offline experiments |
| GAP | LP-01 kill left richer confluence/OB/FVG/width questions untested |
| SMALLEST_COMPLETE_CHANGE | `tools/liquidity_synthesis_experiments_v1.py` + this report |
| MINIMUM_SUFFICIENT_EVIDENCE | Same-turn harness output; placebos; exact n |
| DECISION_PATH_EFFECT | None — WAIT |
| WHY_NOW | Operator asked experiment-only follow-up from synthesis research |
| TASK_ADMISSION | Admitted as research/backtest only |

## Pre-registered PASS

```
{
  "min_events_per_arm": 150,
  "min_win_rate_edge_pp": 0.05,
  "min_halves_agreeing": 2
}
```

High kill rate is success. ICT/SMC names are candidate geometry only.

## Verdicts

| Exp | Verdict |
|---|---|
| A | **FAIL** |
| B | **FAIL** |
| C | **BLOCKED** |
| D | **FAIL** |
| E | **FAIL** |

## Key findings (PROVEN this run)

1. **A family-count — FAIL.** fam>=2 win_rate=74.0% (resolved=2866) vs fam=1 72.3%; delta=1.7%. Placebo shuffled fam>=2=75.1%.
2. **B width/E(w) — FAIL.** Tsinaslanidis trap=True. Width 0.10→1.50×ATR: win_rate 34.6%→73.6%; E 0.604→0.267.
3. **C gamma — BLOCKED.** option_chain_morning_full has only 11 days on the thinnest sentinel (need ≥20 for regime-stratified barrier inference). Bars span ~100 RTH sessions; joining would shrink the sample into an underpowered mixture. No invented gamma.
4. **D OB — FAIL.** real=53.3% vs placebo=55.9% (edge=-2.6%).
5. **E FVG — FAIL.** real=42.9% vs placebo=45.7% (edge=-2.8%).

## A — Family-count vs tag-count

**Verdict: FAIL**

> Does zone touch with n_families≥2 beat (i) n_families==1 and (ii) placebo zones built with shuffled family labels?

- Band: 0.15% of price
- Real events: 7027; placebo (shuffled families): 7027
- Causal families only: PRIOR_DAY, OVERNIGHT, ORB. TODAY_VP/VWAP/GAMMA excluded (lookahead or BLOCKED).

| bucket | n | resolved | win_rate | E |
|---|---|---|---|---|
| real families≥2 | 3022 | 2866 | 74.0% | 0.252 |
| real families=1 | 4005 | 3835 | 72.3% | 0.286 |
| placebo families≥2 | 2810 | 2654 | 75.1% | 0.255 |
| Δ(fam≥2 − fam=1) win_rate | | | 1.7% | |

### By raw tag count (real arm, descriptive)

| bucket | n | win_rate | E |
|---|---|---|---|
| tags_1 | 3501 | 72.0% | 0.288 |
| tags_2 | 2046 | 72.9% | 0.278 |
| tags_ge3 | 1480 | 75.9% | 0.223 |

## B — Zone width / E(w)

**Verdict: FAIL**

> As zone width rises, does bounce win-rate rise while E(w)=P(win)×R fails to beat random-center zones? (Tsinaslanidis discipline)

- Tsinaslanidis trap flag: **True**
- Costs: ABSENT

| width (×ATR) | real n | real win% | real E | placebo win% | placebo E | edge win% |
|---|---|---|---|---|---|---|
| 0.10 | 9620 | 34.6% | 0.604 | 34.6% | 0.599 | 0.0% |
| 0.25 | 10887 | 40.6% | 0.553 | 41.3% | 0.550 | -0.6% |
| 0.50 | 11822 | 49.5% | 0.464 | 51.4% | 0.463 | -1.9% |
| 1.00 | 12454 | 63.8% | 0.338 | 66.9% | 0.335 | -3.1% |
| 1.50 | 12586 | 73.6% | 0.267 | 75.4% | 0.258 | -1.8% |

## C — Gamma regime split

**Status: BLOCKED — Verdict: BLOCKED**

> Do structure-zone barrier outcomes differ under LONG vs SHORT gamma (morning_full terrain sign)?

- Reason: option_chain_morning_full has only 11 days on the thinnest sentinel (need ≥20 for regime-stratified barrier inference). Bars span ~100 RTH sessions; joining would shrink the sample into an underpowered mixture. No invented gamma.
- Coverage: `{"IWM": {"n_days": 12, "min": "2026-07-19", "max": "2026-07-30"}, "QQQ": {"n_days": 11, "min": "2026-07-20", "max": "2026-07-30"}, "SPY": {"n_days": 12, "min": "2026-07-19", "max": "2026-07-30"}}`

## D — D_order_block

**Verdict: FAIL**

> Do objective order-block zones beat random same-width zones on triple-barrier bounce labels?

- Definition: `{"bullish_ob": "last bearish candle before close displacement \u2265 1.5\u00d7causal_ATR within 5 bars; zone=[L,H] of that candle", "bearish_ob": "mirror", "ict_disclaimer": "[UNVERIFIED] operationalization \u2014 not vendor ICT equivalence"}`
- Zones detected: 22350
- Real events: 12379 (resolved 12243)
- Placebo events: 12111 (resolved 11912)
- Real win_rate: 53.3%; placebo: 55.9%; edge: -2.6%
- Real E: 0.441; placebo E: 0.427
- Costs: ABSENT

## E — E_fvg

**Verdict: FAIL**

> Do objective 3-candle FVG zones beat random same-width zones on triple-barrier bounce labels?

- Definition: `{"bull_fvg": "low[i] > high[i-2]; zone=[high[i-2], low[i]]; min gap 0.15\u00d7ATR", "bear_fvg": "high[i] < low[i-2]; zone=[high[i], low[i-2]]", "ict_disclaimer": "[UNVERIFIED] operationalization \u2014 not ICT course equivalence"}`
- Zones detected: 21294
- Real events: 19419 (resolved 19373)
- Placebo events: 17496 (resolved 17402)
- Real win_rate: 42.9%; placebo: 45.7%; edge: -2.8%
- Real E: 0.526; placebo E: 0.512
- Costs: ABSENT

## Disposition

- Pack: **ALL_FAIL_OR_BLOCKED**
- Structure-only. Decide stays WAIT.
- Reproduce: `python tools/liquidity_synthesis_experiments_v1.py`

## Next (discussion)

1. Accrue morning_full / terrain days until C is runnable (≥20/ticker).
2. If A stays FAIL with only 3 causal families, retest when TODAY_VP/VWAP can be constructed *causally* (running VP/VWAP at touch time — new Collect feature).
3. Trigger layer (absorption / rejection wick) nested on the same barrier labels.
4. Do not promote OB/FVG to UI from this pack unless a later run PASSes placebos.
