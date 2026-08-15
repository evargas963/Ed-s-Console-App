# liquidity_strike_ic_v1

**MISSION_CLASS:** Find & Prove — offline Information Coefficient (Spearman) on strike signals vs stickiness
**DECISION_PATH_EFFECT:** WAIT — no Decide admission; no Chart/UI change
**COSTS:** ABSENT (ranking study, not a trade system)
**OVERALL VERDICT:** `WEAK_FAIL` (basis: `partial_spearman_controlling_DIST_INV`)

**NOTE:** Raw DIST_INV IC is strong (mechanical ATM↔pin geometry); liquidity signals judged on partial Spearman controlling for DIST_INV.

Reproduce:
```
python tools/liquidity_strike_ic_v1.py
```

## AGENTS.md admission

| Field | Answer |
|---|---|
| MISSION_CLASS | Find & Prove — research + offline IC |
| GAP | Prior packs scored top-K touch/hold/stickiness; continuous cross-sectional rank IC untested |
| SMALLEST_COMPLETE_CHANGE | This tool + reports/*.md/*.json |
| MINIMUM_SUFFICIENT_EVIDENCE | Same-turn mean IC / IR / hit / bootstrap vs within-day signal shuffle; primary = ATM-partial IC |
| DECISION_PATH_EFFECT | None — WAIT |
| WHY_NOW | Operator: try Information Coefficient; brainstorm what else |
| TASK_ADMISSION | Admitted as Find & Prove research only |

## 1) IC definition (locked)

For each session and each (signal, target) pair, take all option strikes within **±3%** of morning spot. Compute

```
IC_day = Spearman( rank(signal_strike), rank(target_strike) )
```

**Primary (liquidity claim):** partial Spearman controlling for `DIST_INV` (ATM proximity). Rank-transform signal, target, and DIST_INV; residualize signal ranks and target ranks on DIST_INV ranks; Pearson of residuals. This blocks the lazy trap where volume/OI/GEX merely tag near-spot strikes that are mechanically closer to the close / in-band.

Aggregate across sessions:

- **mean IC** — average of day ICs
- **IC IR** — mean / stdev (information ratio of the IC series)
- **hit rate** — fraction of days with IC > 0
- **bootstrap** — 400 day-resamples → 95% CI on mean IC

**Placebo:** shuffle signal values across strikes *within* the same day, then recompute Spearman (or partial Spearman). A real ranking relationship should show mean IC ≫ placebo (~0).

**Causal:** signals from `option_chain_morning_full` (prefer) or snapshots in 09:45–10:15 ET; stickiness targets from RTH bars at/after 10:15 ET; ATR for bands from pre-10:15 bars only (same as `liquidity_oi_volume_stickiness_v1`).

### Signals (higher = stronger candidate magnet)

| Signal | Definition |
|---|---|
| VOL | Summed as-of options volume at strike |
| OI | Summed open interest |
| PRODUCT | OI × volume |
| Z_PRODUCT | z(OI) × z(vol) within band |
| TURNOVER | volume / OI (0 if OI=0) |
| GEX_ABS | abs(dealer GEX$) at strike from morning chain |
| DIST_INV | 1/(|K−S|+0.01) — ATM proximity confounder |

### Targets (higher = stickier)

| Target | Definition |
|---|---|
| time_in_band | Fraction of post-10:15 closes within 0.25×causalATR of K |
| failed_break_rate | Reclaim rate after pierce ≥0.35×ATR (sparse; often blank) |
| pin_closeness | negative abs(RTH close − K) |
| signed_pull | Mean bar-to-bar reduction in abs(close−K) |
| composite | Equal-weight z of available stickiness targets |

### PASS gates (pre-registered)

```
{
  "min_sessions": 80,
  "min_mean_ic": 0.05,
  "min_ic_ir": 0.3,
  "min_hit_rate": 0.55,
  "min_edge_vs_placebo": 0.04,
  "bootstrap_excludes_zero": true
}
```

## 2) Sample (exact)

- Tickers: `['SPY', 'QQQ', 'IWM']`
- Observation keys loaded: **202**
- Sessions with IC computed: **198**
- Date range: `2026-03-25` → `2026-07-30`
- Sessions by ticker: `{'SPY': 68, 'QQQ': 64, 'IWM': 66}`
- Faucet mix: `{'snapshots_1000et': 171, 'morning_full': 27}`
- morning_full census: `{"SPY": {"raw": 12, "trading_days": 9, "min_et": "2026-07-19", "max_et": "2026-07-30"}, "QQQ": {"raw": 11, "trading_days": 9, "min_et": "2026-07-20", "max_et": "2026-07-30"}, "IWM": {"raw": 12, "trading_days": 9, "min_et": "2026-07-19", "max_et": "2026-07-30"}}`
- Regime labels: `{'LONG_GAMMA': 0, 'SHORT_GAMMA': 27, 'UNKNOWN': 171}`
- Mean strikes in ±3% band: **21.4**
- Drops: `{'short_session': 1, 'atr_zero': 3}`
- Blank reasons (top): `{'RESID|DIST_INV|time_in_band|control_is_signal': 198, 'RESID|DIST_INV|failed_break_rate|control_is_signal': 198, 'RESID|DIST_INV|pin_closeness|control_is_signal': 198, 'RESID|DIST_INV|signed_pull|control_is_signal': 198, 'RESID|DIST_INV|composite|control_is_signal': 198, 'RESID|VOL|pin_closeness|spearman_undefined': 11, 'RESID|OI|pin_closeness|spearman_undefined': 11, 'RESID|PRODUCT|pin_closeness|spearman_undefined': 11, 'RESID|Z_PRODUCT|pin_closeness|spearman_undefined': 11, 'RESID|TURNOVER|pin_closeness|spearman_undefined': 11, 'RESID|GEX_ABS|pin_closeness|spearman_undefined': 10, 'GEX_ABS|time_in_band|zero_variance': 3, 'RESID|GEX_ABS|time_in_band|zero_variance': 3, 'GEX_ABS|failed_break_rate|zero_variance': 3, 'RESID|GEX_ABS|failed_break_rate|zero_variance': 3, 'GEX_ABS|pin_closeness|zero_variance': 3, 'RESID|GEX_ABS|pin_closeness|zero_variance': 3, 'GEX_ABS|signed_pull|zero_variance': 3, 'RESID|GEX_ABS|signed_pull|zero_variance': 3, 'GEX_ABS|composite|zero_variance': 3}`
- Elapsed: 64.48s

## 3) PRIMARY — partial Spearman IC (control = DIST_INV / ATM)

Liquidity signals must clear placebo **after** removing ATM proximity. DIST_INV itself is excluded here (it is the control).

| Signal | Target | n | mean IC | IC IR | hit% | plc mean | edge | boot CI | Verdict |
|---|---|---:|---:|---:|---:|---:|---:|---|---|
| VOL | time_in_band | 198 | 0.0333 | 0.102 | 55.1% | 0.0132 | 0.0201 | [-0.0097, 0.0819] | `WEAK_FAIL` |
| VOL | failed_break_rate | 198 | 0.0311 | 0.104 | 55.6% | -0.0030 | 0.0341 | [-0.0115, 0.0747] | `WEAK_FAIL` |
| VOL | pin_closeness | 187 | 0.0122 | 0.022 | 50.3% | -0.0104 | 0.0226 | [-0.0595, 0.0883] | `WEAK_FAIL` |
| VOL | signed_pull | 198 | -0.0334 | -0.062 | 46.0% | 0.0084 | -0.0418 | [-0.1089, 0.0445] | `FAIL` |
| VOL | composite | 198 | -0.0140 | -0.028 | 47.0% | -0.0002 | -0.0138 | [-0.0816, 0.0669] | `FAIL` |
| OI | time_in_band | 198 | -0.0123 | -0.048 | 48.0% | -0.0019 | -0.0105 | [-0.0490, 0.0194] | `FAIL` |
| OI | failed_break_rate | 198 | 0.0036 | 0.014 | 51.0% | -0.0033 | 0.0069 | [-0.0318, 0.0412] | `WEAK_FAIL` |
| OI | pin_closeness | 187 | -0.0495 | -0.108 | 43.3% | -0.0358 | -0.0137 | [-0.1237, 0.0199] | `FAIL` |
| OI | signed_pull | 198 | -0.0665 | -0.143 | 42.4% | 0.0160 | -0.0825 | [-0.1344, 0.0030] | `FAIL` |
| OI | composite | 198 | -0.0511 | -0.116 | 43.9% | -0.0022 | -0.0489 | [-0.1131, 0.0118] | `FAIL` |
| PRODUCT | time_in_band | 198 | 0.0223 | 0.080 | 55.6% | -0.0026 | 0.0248 | [-0.0207, 0.0612] | `WEAK_FAIL` |
| PRODUCT | failed_break_rate | 198 | 0.0321 | 0.120 | 56.1% | -0.0021 | 0.0342 | [-0.0039, 0.0715] | `WEAK_FAIL` |
| PRODUCT | pin_closeness | 187 | -0.0161 | -0.033 | 44.4% | -0.0055 | -0.0106 | [-0.0857, 0.0612] | `FAIL` |
| PRODUCT | signed_pull | 198 | -0.0548 | -0.111 | 39.4% | -0.0315 | -0.0233 | [-0.1205, 0.0174] | `FAIL` |
| PRODUCT | composite | 198 | -0.0340 | -0.074 | 42.4% | 0.0059 | -0.0398 | [-0.0892, 0.0291] | `FAIL` |
| Z_PRODUCT | time_in_band | 198 | -0.0031 | -0.012 | 48.0% | 0.0124 | -0.0155 | [-0.0348, 0.0315] | `FAIL` |
| Z_PRODUCT | failed_break_rate | 198 | 0.0082 | 0.032 | 48.5% | -0.0136 | 0.0219 | [-0.0247, 0.0394] | `FAIL` |
| Z_PRODUCT | pin_closeness | 187 | 0.0063 | 0.022 | 48.7% | -0.0134 | 0.0196 | [-0.0370, 0.0424] | `FAIL` |
| Z_PRODUCT | signed_pull | 198 | 0.0166 | 0.056 | 55.1% | 0.0015 | 0.0152 | [-0.0234, 0.0559] | `WEAK_FAIL` |
| Z_PRODUCT | composite | 198 | 0.0179 | 0.061 | 57.6% | 0.0070 | 0.0109 | [-0.0243, 0.0601] | `WEAK_FAIL` |
| TURNOVER | time_in_band | 198 | 0.0407 | 0.139 | 58.1% | -0.0301 | 0.0709 | [-0.0005, 0.0844] | `WEAK_FAIL` |
| TURNOVER | failed_break_rate | 198 | 0.0273 | 0.100 | 56.1% | 0.0270 | 0.0003 | [-0.0118, 0.0698] | `WEAK_FAIL` |
| TURNOVER | pin_closeness | 187 | 0.0684 | 0.141 | 54.0% | -0.0067 | 0.0751 | [-0.0124, 0.1422] | `WEAK_FAIL` |
| TURNOVER | signed_pull | 198 | 0.0259 | 0.053 | 50.5% | -0.0015 | 0.0274 | [-0.0378, 0.0997] | `WEAK_FAIL` |
| TURNOVER | composite | 198 | 0.0342 | 0.074 | 51.5% | 0.0093 | 0.0249 | [-0.0245, 0.1024] | `WEAK_FAIL` |
| GEX_ABS | time_in_band | 195 | 0.0005 | 0.002 | 48.7% | 0.0205 | -0.0200 | [-0.0420, 0.0352] | `FAIL` |
| GEX_ABS | failed_break_rate | 195 | 0.0106 | 0.039 | 49.2% | 0.0223 | -0.0117 | [-0.0285, 0.0483] | `FAIL` |
| GEX_ABS | pin_closeness | 185 | -0.0192 | -0.041 | 47.0% | 0.0071 | -0.0263 | [-0.0764, 0.0496] | `FAIL` |
| GEX_ABS | signed_pull | 195 | -0.0587 | -0.126 | 42.6% | -0.0026 | -0.0560 | [-0.1275, 0.0055] | `FAIL` |
| GEX_ABS | composite | 195 | -0.0406 | -0.091 | 45.1% | -0.0097 | -0.0309 | [-0.1024, 0.0256] | `FAIL` |

### Ranked residual IC (top 15)

| Rank | Signal | Target | mean IC | IR | hit% | edge vs plc | Verdict |
|---:|---|---|---:|---:|---:|---:|---|
| 1 | TURNOVER | pin_closeness | 0.0684 | 0.141 | 54.0% | 0.0751 | `WEAK_FAIL` |
| 2 | TURNOVER | time_in_band | 0.0407 | 0.139 | 58.1% | 0.0709 | `WEAK_FAIL` |
| 3 | TURNOVER | composite | 0.0342 | 0.074 | 51.5% | 0.0249 | `WEAK_FAIL` |
| 4 | VOL | time_in_band | 0.0333 | 0.102 | 55.1% | 0.0201 | `WEAK_FAIL` |
| 5 | PRODUCT | failed_break_rate | 0.0321 | 0.120 | 56.1% | 0.0342 | `WEAK_FAIL` |
| 6 | VOL | failed_break_rate | 0.0311 | 0.104 | 55.6% | 0.0341 | `WEAK_FAIL` |
| 7 | TURNOVER | failed_break_rate | 0.0273 | 0.100 | 56.1% | 0.0003 | `WEAK_FAIL` |
| 8 | TURNOVER | signed_pull | 0.0259 | 0.053 | 50.5% | 0.0274 | `WEAK_FAIL` |
| 9 | PRODUCT | time_in_band | 0.0223 | 0.080 | 55.6% | 0.0248 | `WEAK_FAIL` |
| 10 | Z_PRODUCT | composite | 0.0179 | 0.061 | 57.6% | 0.0109 | `WEAK_FAIL` |
| 11 | Z_PRODUCT | signed_pull | 0.0166 | 0.056 | 55.1% | 0.0152 | `WEAK_FAIL` |
| 12 | VOL | pin_closeness | 0.0122 | 0.022 | 50.3% | 0.0226 | `WEAK_FAIL` |
| 13 | GEX_ABS | failed_break_rate | 0.0106 | 0.039 | 49.2% | -0.0117 | `FAIL` |
| 14 | Z_PRODUCT | failed_break_rate | 0.0082 | 0.032 | 48.5% | 0.0219 | `FAIL` |
| 15 | Z_PRODUCT | pin_closeness | 0.0063 | 0.022 | 48.7% | 0.0196 | `FAIL` |

## 4) DESCRIPTIVE — raw Spearman IC (ATM-inflated)

Includes DIST_INV. Strong raw IC here can be pure geometry (near-spot strikes sit closer to the close / in-band when spot does not travel far).

| Signal | Target | n | mean IC | IC IR | hit% | plc mean | edge | boot CI | Verdict |
|---|---|---:|---:|---:|---:|---:|---:|---|---|
| VOL | time_in_band | 198 | 0.4292 | 1.615 | 91.9% | -0.0197 | 0.4489 | [0.3944, 0.4644] | `PASS` |
| VOL | failed_break_rate | 198 | 0.4255 | 1.856 | 95.5% | 0.0144 | 0.4111 | [0.3923, 0.4557] | `PASS` |
| VOL | pin_closeness | 198 | 0.5173 | 1.277 | 85.4% | -0.0035 | 0.5208 | [0.4675, 0.5757] | `PASS` |
| VOL | signed_pull | 198 | -0.1288 | -0.373 | 33.8% | -0.0015 | -0.1273 | [-0.1766, -0.0770] | `FAIL` |
| VOL | composite | 198 | 0.4381 | 1.361 | 89.9% | 0.0165 | 0.4215 | [0.3942, 0.4822] | `PASS` |
| OI | time_in_band | 198 | 0.1268 | 0.519 | 69.2% | 0.0028 | 0.1239 | [0.0936, 0.1648] | `PASS` |
| OI | failed_break_rate | 198 | 0.1374 | 0.567 | 68.7% | -0.0237 | 0.1612 | [0.1033, 0.1688] | `PASS` |
| OI | pin_closeness | 198 | 0.1421 | 0.417 | 66.2% | -0.0194 | 0.1615 | [0.0911, 0.1984] | `PASS` |
| OI | signed_pull | 198 | -0.0966 | -0.219 | 38.9% | 0.0161 | -0.1127 | [-0.1526, -0.0298] | `FAIL` |
| OI | composite | 198 | 0.1130 | 0.308 | 62.1% | 0.0046 | 0.1084 | [0.0637, 0.1651] | `PASS` |
| PRODUCT | time_in_band | 198 | 0.3564 | 1.470 | 88.4% | -0.0187 | 0.3752 | [0.3210, 0.3905] | `PASS` |
| PRODUCT | failed_break_rate | 198 | 0.3611 | 1.640 | 91.4% | -0.0171 | 0.3782 | [0.3320, 0.3929] | `PASS` |
| PRODUCT | pin_closeness | 198 | 0.4203 | 1.078 | 83.8% | -0.0343 | 0.4546 | [0.3658, 0.4732] | `PASS` |
| PRODUCT | signed_pull | 198 | -0.1356 | -0.372 | 34.3% | 0.0115 | -0.1471 | [-0.1893, -0.0811] | `FAIL` |
| PRODUCT | composite | 198 | 0.3517 | 1.057 | 82.3% | -0.0098 | 0.3615 | [0.3034, 0.3946] | `PASS` |
| Z_PRODUCT | time_in_band | 198 | -0.0940 | -0.391 | 33.8% | -0.0178 | -0.0762 | [-0.1247, -0.0623] | `FAIL` |
| Z_PRODUCT | failed_break_rate | 198 | -0.0799 | -0.329 | 35.9% | 0.0060 | -0.0860 | [-0.1158, -0.0485] | `FAIL` |
| Z_PRODUCT | pin_closeness | 198 | -0.1052 | -0.417 | 31.8% | 0.0077 | -0.1129 | [-0.1372, -0.0696] | `FAIL` |
| Z_PRODUCT | signed_pull | 198 | 0.0371 | 0.132 | 57.1% | -0.0060 | 0.0432 | [0.0006, 0.0781] | `WEAK_FAIL` |
| Z_PRODUCT | composite | 198 | -0.0851 | -0.324 | 33.8% | -0.0227 | -0.0625 | [-0.1181, -0.0488] | `FAIL` |
| TURNOVER | time_in_band | 198 | 0.3938 | 1.435 | 90.4% | -0.0104 | 0.4041 | [0.3589, 0.4320] | `PASS` |
| TURNOVER | failed_break_rate | 198 | 0.3865 | 1.580 | 92.4% | 0.0226 | 0.3640 | [0.3493, 0.4165] | `PASS` |
| TURNOVER | pin_closeness | 198 | 0.5042 | 1.334 | 88.4% | 0.0112 | 0.4931 | [0.4532, 0.5568] | `PASS` |
| TURNOVER | signed_pull | 198 | -0.0822 | -0.237 | 36.4% | -0.0033 | -0.0788 | [-0.1312, -0.0332] | `FAIL` |
| TURNOVER | composite | 198 | 0.4221 | 1.310 | 88.9% | -0.0183 | 0.4403 | [0.3764, 0.4721] | `PASS` |
| GEX_ABS | time_in_band | 195 | 0.3641 | 1.662 | 93.3% | 0.0050 | 0.3591 | [0.3324, 0.3964] | `PASS` |
| GEX_ABS | failed_break_rate | 195 | 0.3650 | 1.777 | 92.8% | -0.0184 | 0.3833 | [0.3361, 0.3892] | `PASS` |
| GEX_ABS | pin_closeness | 195 | 0.4496 | 1.253 | 85.6% | -0.0022 | 0.4518 | [0.4000, 0.5033] | `PASS` |
| GEX_ABS | signed_pull | 195 | -0.1318 | -0.423 | 30.8% | -0.0086 | -0.1232 | [-0.1729, -0.0857] | `FAIL` |
| GEX_ABS | composite | 195 | 0.3718 | 1.244 | 86.7% | -0.0007 | 0.3725 | [0.3309, 0.4141] | `PASS` |
| DIST_INV | time_in_band | 198 | 0.4988 | 1.969 | 92.4% | 0.0430 | 0.4558 | [0.4642, 0.5334] | `PASS` |
| DIST_INV | failed_break_rate | 198 | 0.4968 | 2.388 | 96.0% | -0.0117 | 0.5085 | [0.4696, 0.5255] | `PASS` |
| DIST_INV | pin_closeness | 198 | 0.6362 | 1.905 | 96.5% | 0.0089 | 0.6274 | [0.5881, 0.6824] | `PASS` |
| DIST_INV | signed_pull | 198 | -0.1284 | -0.699 | 22.7% | -0.0042 | -0.1241 | [-0.1543, -0.1025] | `FAIL` |
| DIST_INV | composite | 198 | 0.5332 | 2.163 | 97.5% | -0.0012 | 0.5345 | [0.4985, 0.5646] | `PASS` |

### Ranked raw IC (top 15)

| Rank | Signal | Target | mean IC | IR | hit% | edge vs plc | Verdict |
|---:|---|---|---:|---:|---:|---:|---|
| 1 | DIST_INV | pin_closeness | 0.6362 | 1.905 | 96.5% | 0.6274 | `PASS` |
| 2 | DIST_INV | composite | 0.5332 | 2.163 | 97.5% | 0.5345 | `PASS` |
| 3 | VOL | pin_closeness | 0.5173 | 1.277 | 85.4% | 0.5208 | `PASS` |
| 4 | TURNOVER | pin_closeness | 0.5042 | 1.334 | 88.4% | 0.4931 | `PASS` |
| 5 | DIST_INV | time_in_band | 0.4988 | 1.969 | 92.4% | 0.4558 | `PASS` |
| 6 | DIST_INV | failed_break_rate | 0.4968 | 2.388 | 96.0% | 0.5085 | `PASS` |
| 7 | GEX_ABS | pin_closeness | 0.4496 | 1.253 | 85.6% | 0.4518 | `PASS` |
| 8 | VOL | composite | 0.4381 | 1.361 | 89.9% | 0.4215 | `PASS` |
| 9 | VOL | time_in_band | 0.4292 | 1.615 | 91.9% | 0.4489 | `PASS` |
| 10 | VOL | failed_break_rate | 0.4255 | 1.856 | 95.5% | 0.4111 | `PASS` |
| 11 | TURNOVER | composite | 0.4221 | 1.310 | 88.9% | 0.4403 | `PASS` |
| 12 | PRODUCT | pin_closeness | 0.4203 | 1.078 | 83.8% | 0.4546 | `PASS` |
| 13 | TURNOVER | time_in_band | 0.3938 | 1.435 | 90.4% | 0.4041 | `PASS` |
| 14 | TURNOVER | failed_break_rate | 0.3865 | 1.580 | 92.4% | 0.3640 | `PASS` |
| 15 | GEX_ABS | composite | 0.3718 | 1.244 | 86.7% | 0.3725 | `PASS` |

## 5) Verdict

- Residual (primary) cell counts: `{'PASS': 0, 'WEAK_FAIL': 13, 'FAIL': 17, 'UNDERPOWERED': 0, 'BLANK': 0}`
- Raw (descriptive) cell counts: `{'PASS': 24, 'WEAK_FAIL': 1, 'FAIL': 10, 'UNDERPOWERED': 0, 'BLANK': 0}`
- **Overall (ATM-controlled):** `WEAK_FAIL`

Interpretation rule: a *liquidity* signal has reliable IC only if **partial** mean IC (control=DIST_INV) clears absolute gates **and** bootstrap CI excludes 0 **and** mean IC − placebo mean clears the edge gate. Raw DIST_INV PASS shows ATM geometry predicts pin/in-band — expected, not edge.

## 6) Blanks / limits (fair-method)

- Equal-width ±3% moneyness band for all strikes (no wide-wing SUM traps).
- Cross-sectional IC within day — not pooling strikes across days (avoids day-effect).
- Primary claim uses partial Spearman vs DIST_INV (blocks ATM mechanical inflation).
- failed_break_rate can be noisy when pierces are sparse per strike.
- morning_full coverage is thin vs snapshot faucet (exact census above).
- Regime labels mostly UNKNOWN on snapshot faucet (GEX recon only on some days).
- No costs; no Decide path; ranking IC ≠ tradeable edge.

Generated: 2026-07-31T01:25:19.181852+00:00
