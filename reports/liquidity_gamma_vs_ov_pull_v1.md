# Gamma-heavy vs options-volume-heavy pull — v1

**Status:** Find & Prove measurement (offline). Costs ABSENT. Decide WAIT.
**Generated (UTC):** 2026-07-31T02:58:24.910993+00:00
**Elapsed:** 73.97s

Reproduce:

```
python tools/liquidity_gamma_vs_ov_pull_v1.py
```

---

## AGENTS.md admission

| Field | Answer |
|---|---|
| MISSION_CLASS | Find & Prove — measure γ-mass vs options-volume pull |
| GAP | Operator hypothesized γ-heavy+light-vol pulls harder than vol-heavy+light-γ; prior turn shrugged |
| SMALLEST_COMPLETE_CHANGE | This tool + report (+ JSON) |
| MINIMUM_SUFFICIENT_EVIDENCE | Same-turn run; exact n; class + IC + placebo |
| DECISION_PATH_EFFECT | None — WAIT |
| WHY_NOW | Operator bind: research + start measuring, deliver first answer |
| TASK_ADMISSION | Research + offline measurement only; no UI; no Decide |

---

## Phase 1 — Research (short)

1. **Dealer gamma / GEX is a hedging-flow mechanism.** When dealers are long gamma, delta-hedging leans *against* spot moves (buy dips / sell rips) → magnet / pin risk near high-gamma strikes; when short gamma, hedging leans *with* moves → acceleration. Supported directionally by Baltussen, Da, Lammers, Martens (JFE 2021) linking negative gamma hedging demand to intraday momentum. Transfer of *strike-level pin magnitude* to Ed ETF ladders is `[UNVERIFIED]`.

2. **Options volume (flow) is a different object.** Session volume at a strike marks where contracts traded *today*; it can relocate interest, informativeness, and future OI — but volume alone does not specify the *dealer gamma inventory* that forces mechanical underlying hedges. Desk lore that 'yellow bars = magnet' is `[UNVERIFIED]` as a pull mechanism without gamma context.

3. **Why γ-mass without volume ≠ volume without γ-mass (microstructure reason).** Gamma scales how much delta changes *per unit spot move*; OI/gamma stock creates ongoing hedge demand as spot wanders. Volume is a flow rate that may or may not leave dealers in a high-gamma book at that strike. A high-volume / low-gamma strike can be noise or directional taking without a pin engine; a high-gamma / low-volume strike can still force hedges if the OI book is large. Mechanism distinction: **supported** (hedging literature). Ed predictive claim that γ-heavy outpulls vol-heavy after ATM/distance control: answered in Phase 3 (see fair residualized verdict).

4. **Pin / max-pain near expiry** is a related but narrower channel (high OI + exploding gamma as DTE→0). `[UNVERIFIED]` as the dominant driver of 30–60m ETF pull in this study's window.

5. **Vendor GEX 'wall/magnet' narratives** (SpotGamma-style) compress hedging geometry into tradeable levels; predictive edge on Ed walls previously **FAIL** vs placebo (`liquidity_gamma_levels_experiment_v1`, hold/horizon pack). Those were wall/bounce tests — not this γ-vs-vol asymmetric ranking test.

6. **Storm1 equal product** `inv_rank(vol)×inv_rank(|GEX|)` treats both legs symmetrically. Operator asks whether overweighting γ (`score_g`) beats overweighting vol (`score_v`) or the equal product — fair head-to-head below.

7. **Fair-method warning (ATM confound).** Both volume and |GEX| concentrate near ATM; ATM strikes also have mechanically smaller distances / higher time-in-band. Raw IC can false-PASS via proximity. This study reports **ATM-residual (partial Spearman controlling dist_inv)** alongside raw IC.

8. **Costs ABSENT.** No slippage, spread, or hedge-cost model in outcomes.

---

## Phase 2 — Operationalization

- **Obs faucet:** `option_chain_morning_full prefer; else snapshots 09:45–10:15 ET`
- **Outcome start:** 10:15 ET (no lookahead)
- **Band:** ±3% moneyness
- **GEX metric:** abs(net_gex_1pct$) with raw-gamma fallback — Chart family
- **Volume metric:** sum(totalVolume) call+put at strike from obs chain only

### Strike classes (within band, per session)

- **GAMMA_HEAVY:** pct(|GEX|)≥0.80 AND pct(vol)<0.80 within ±3% band
- **VOL_HEAVY:** pct(vol)≥0.80 AND pct(|GEX|)<0.80
- **COMBO_BALANCED:** pct(|GEX|)≥0.80 AND pct(vol)≥0.80 (equiv. top product storm1 region)
- **PLACEBO:** moneyness-matched random strikes (sticky placebo helper)

### Continuous scores

- `score_eq` = inv_rank(vol)*inv_rank(|gex|)  # current storm1
- `score_g`  = inv_rank(|gex|)^2 * inv_rank(vol)
- `score_v`  = inv_rank(vol)^2 * inv_rank(|gex|)

---

## Phase 3 — Measurement results

**Exact sessions scored:** `195` (by ticker: `{'IWM': 65, 'QQQ': 63, 'SPY': 67}`)
**Faucet mix:** `{'snapshots_1000et': 168, 'morning_full': 27}`
**Exact events by class:** `{'GAMMA_HEAVY': 488, 'VOL_HEAVY': 488, 'COMBO_BALANCED': 383, 'PLACEBO': 1356}`

### Composition diagnostic (do not skip)

γ-heavy strikes sit systematically farther from spot than vol-heavy (volume concentrates near ATM). Raw dollar pull can false-PASS from this alone.

- **mean |S0−K| GAMMA_HEAVY:** `5.7347` (n=488)
- **mean |S0−K| VOL_HEAVY:** `2.4313` (n=488)
- **gap (γ − vol):** `3.3033`

### Primary FAIR: pull residualized on dist_t0 @ 30m

`pull_resid = pull_dist − (α + β·|S0−K|)` pooled across all class events. Positive residual = more pull than starting-distance predicts.

| Class | n | mean resid | median | frac(resid>0) |
|---|---:|---:|---:|---:|
| GAMMA_HEAVY | 488 | 0.2079 | 0.3420 | 0.5943 |
| VOL_HEAVY | 488 | -0.1012 | 0.1407 | 0.5369 |
| COMBO_BALANCED | 383 | -0.0444 | 0.1966 | 0.5822 |
| PLACEBO | 1356 | -0.0259 | 0.1706 | 0.5553 |

- **γ-heavy − vol-heavy (fair):** `0.3091`
- **γ-heavy − placebo (fair):** `0.2338`
- **Half-sample agree (γ>vol):** `{'evaluated': True, 'split_date': '2026-06-09', 'n_agree': 2, 'halves_agree': True}`
- **Fair verdict:** **PASS**

### Raw dollar pull @ 30m (composition-exposed — not primary)

`pull = |S0−K| − |S30−K|` (positive = closer). All class means are typically negative (net drift away); 'edge' here is *less negative*.

| Class | n | mean pull | median | frac(pull>0) |
|---|---:|---:|---:|---:|
| GAMMA_HEAVY | 488 | -0.1955 | -0.0574 | 0.4652 |
| VOL_HEAVY | 488 | -0.4960 | -0.2500 | 0.4160 |
| PLACEBO | 1356 | -0.4240 | -0.2200 | 0.4196 |

- raw edge γ−vol: `0.3005` · verdict: **PASS** (treat as composition-exposed)

### pull_frac_30m

| Class | n | mean | median |
|---|---:|---:|---:|
| GAMMA_HEAVY | 488 | -0.2558 | -0.0178 |
| VOL_HEAVY | 485 | -1.3988 | -0.1405 |
| COMBO_BALANCED | 383 | -1.4984 | -0.1560 |
| PLACEBO | 1356 | -1.1050 | -0.0976 |

- edge γ−vol: `1.1430` · γ−placebo: `0.8492` · verdict: **PASS**

### pull_frac_60m

| Class | n | mean | median |
|---|---:|---:|---:|
| GAMMA_HEAVY | 488 | -0.3187 | -0.0437 |
| VOL_HEAVY | 485 | -2.5477 | -0.2861 |
| COMBO_BALANCED | 383 | -2.0591 | -0.2496 |
| PLACEBO | 1356 | -1.8796 | -0.1629 |

- edge γ−vol: `2.2291` · γ−placebo: `1.5609` · verdict: **PASS**

### pull_resid_dist_60m

| Class | n | mean | median |
|---|---:|---:|---:|
| GAMMA_HEAVY | 488 | 0.1926 | 0.3951 |
| VOL_HEAVY | 488 | -0.1079 | 0.0347 |
| COMBO_BALANCED | 383 | 0.0610 | 0.2913 |
| PLACEBO | 1356 | -0.0477 | 0.1618 |

- edge γ−vol: `0.3005` · γ−placebo: `0.2403` · verdict: **PASS**

### pull_dist_60m

| Class | n | mean | median |
|---|---:|---:|---:|
| GAMMA_HEAVY | 488 | -0.2669 | -0.1650 |
| VOL_HEAVY | 488 | -0.7392 | -0.6350 |
| COMBO_BALANCED | 383 | -0.5741 | -0.4000 |
| PLACEBO | 1356 | -0.6135 | -0.4700 |

- edge γ−vol: `0.4723` · γ−placebo: `0.3466` · verdict: **PASS**

### time_in_band_30m

| Class | n | mean | median |
|---|---:|---:|---:|
| GAMMA_HEAVY | 488 | 0.0107 | 0.0000 |
| VOL_HEAVY | 488 | 0.0333 | 0.0000 |
| COMBO_BALANCED | 383 | 0.0312 | 0.0000 |
| PLACEBO | 1356 | 0.0214 | 0.0000 |

- edge γ−vol: `-0.0226` · γ−placebo: `-0.0107` · verdict: **FAIL**

### time_in_band_60m

| Class | n | mean | median |
|---|---:|---:|---:|
| GAMMA_HEAVY | 488 | 0.0114 | 0.0000 |
| VOL_HEAVY | 488 | 0.0323 | 0.0000 |
| COMBO_BALANCED | 383 | 0.0285 | 0.0000 |
| PLACEBO | 1356 | 0.0200 | 0.0000 |

- edge γ−vol: `-0.0209` · γ−placebo: `-0.0085` · verdict: **FAIL**

### dist_h_30m

| Class | n | mean | median |
|---|---:|---:|---:|
| GAMMA_HEAVY | 488 | 5.9302 | 4.5250 |
| VOL_HEAVY | 488 | 2.9273 | 1.9850 |
| COMBO_BALANCED | 383 | 2.7962 | 1.7900 |
| PLACEBO | 1356 | 4.1149 | 2.7900 |

- edge γ−vol: `-3.0028` · γ−placebo: `-1.8153` · verdict: **FAIL**

### dist_h_60m

| Class | n | mean | median |
|---|---:|---:|---:|
| GAMMA_HEAVY | 488 | 6.0016 | 4.6700 |
| VOL_HEAVY | 488 | 3.1705 | 2.3800 |
| COMBO_BALANCED | 383 | 2.9312 | 2.0100 |
| PLACEBO | 1356 | 4.3044 | 2.9420 |

- edge γ−vol: `-2.8310` · γ−placebo: `-1.6972` · verdict: **FAIL**

### Continuous score IC vs pull_dist (Spearman; higher score → more pull)

| Score × horizon | n_days | mean IC | hit rate | ATM-resid mean IC | ATM-resid hit |
|---|---:|---:|---:|---:|---:|
| score_eq_30m | 194 | -0.0271 | 0.4845 | 0.0366 | 0.5722 |
| score_g_30m | 194 | -0.0241 | 0.4897 | 0.0288 | 0.5773 |
| score_v_30m | 194 | -0.0325 | 0.4639 | 0.0352 | 0.5052 |
| score_eq_60m | 195 | -0.0407 | 0.4462 | 0.0396 | 0.5641 |
| score_g_60m | 195 | -0.0266 | 0.4718 | 0.0443 | 0.5744 |
| score_v_60m | 195 | -0.0532 | 0.4359 | 0.0344 | 0.5385 |

- **Score verdict 30m raw / atm-resid:** `FAIL` / `EQ_BETTER`
- **edge IC(score_g)−IC(score_v) 30m:** raw `0.0084` · atm-resid `-0.0064`
- **Score verdict 60m raw / atm-resid:** `FAIL` / `WEAK`

---

## Plain-English verdict

On 195 SPY/QQQ/IWM sessions (n_events γ=488, vol=488, combo=383, placebo=1356), gamma-heavy strikes show MORE pull than vol-heavy after controlling for starting distance: fair residual mean 0.2079 vs -0.1012 (edge=0.3091, vs placebo edge=0.2338, verdict=PASS; halves agree). Composition: γ-heavy starts ~5.7347 from spot vs vol-heavy ~2.4313. This is NOT classic magnet stickiness — time-in-band FAIL for γ-heavy. Continuous scores: 30m atm-resid IC favors score_eq (0.0366) over score_g (0.0288); chart use_for_now=score_eq. Costs ABSENT. Decide WAIT.

---

## Chart highlight recommendation (for now)

**Use:** `score_eq`

**Reason:** atm-resid IC does not favor score_g over score_v (edge_g_minus_v=-0.0064); keep score_eq

---

## NEXT measurement

1. **Distance-matched pairs:** within each session, pair each γ-heavy strike to a vol-heavy strike with closest |S0−K| (stricter than linear residual).
2. **Regime split:** LONG_GAMMA vs SHORT_GAMMA days (pin vs acceleration).
3. **DTE split:** near-expiry (≤1) vs longer-dated mass.
4. **Afternoon as-of refresh:** score at T with accrued volume, pull after T (morning volume ranks are noisy).
5. Accrue more `morning_full` days (current faucet mostly snapshots_1000et).
6. Still Decide WAIT — costs ABSENT; no TRADE admission.

---

## Limits

- Fair pull PASS is **relative resistance to drift-away**, not classic pin: time-in-band and ending distance FAIL for γ-heavy (they start and stay farther).
- Continuous `score_g` does **not** beat `score_eq` on 30m ATM-residual IC (chart stays eq).
- Morning as-of options volume can be sparse — vol ranks noisier than |GEX|.
- `pull_frac` can explode when |S0−K| is tiny near ATM — prefer resid metric.
- No Decide admission. Costs ABSENT.

