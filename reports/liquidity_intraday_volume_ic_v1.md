# liquidity_intraday_volume_ic_v1

## Plain English (read first)

1. **Why freeze was used:** Morning freeze exists to PREVENT lookahead false positives. Using EOD / late-day cumulative options volume to predict same-day stickiness is circular — volume accumulates where price already went. Freeze does NOT inflate edge; it answers a different question: 'can I act at 10:15 on the morning chain?'

2. **Why the Chart critique is right:** Live Chart yellow bars update through the session. Testing only the morning freeze does not test what the operator sees on Chart. This study runs the Chart-relevant experiment: as-of cumulative volume from the latest causal snapshot at each decision clock T.

3. **What this run found:** At **10:15** (n=193 sessions): live VOL residual mean IC vs time_in_band = 0.0462 (verdict `WEAK_FAIL`, edge vs placebo 0.0459); freeze VOL = 0.0378; Δ(live−freeze) = 0.0084; clock `FAIL`. At **11:00** (n=215 sessions): live VOL residual mean IC vs time_in_band = 0.0107 (verdict `WEAK_FAIL`, edge vs placebo 0.0078); freeze VOL = -0.0160; Δ(live−freeze) = 0.0267; clock `WEAK_LIVE_ABOVE_FREEZE`. At **12:00** (n=213 sessions): live VOL residual mean IC vs time_in_band = 0.0420 (verdict `WEAK_FAIL`, edge vs placebo 0.0270); freeze VOL = -0.0011; Δ(live−freeze) = 0.0431; clock `WEAK_LIVE_ABOVE_FREEZE`. At **14:00** (n=210 sessions): live VOL residual mean IC vs time_in_band = 0.0023 (verdict `FAIL`, edge vs placebo -0.0183); freeze VOL = -0.0419; Δ(live−freeze) = 0.0441; clock `FAIL`. Overall: `WEAK_LIVE_ABOVE_FREEZE`.

**MISSION_CLASS:** Find & Prove — offline causal intraday volume IC
**DECISION_PATH_EFFECT:** WAIT — no Decide admission; no Chart/UI change
**OVERALL VERDICT:** `WEAK_LIVE_ABOVE_FREEZE` (basis: `ATM-controlled partial Spearman for live VOL vs FREEZE_VOL and vs placebo, per decision clock`)

Reproduce:
```
python tools/liquidity_intraday_volume_ic_v1.py
```

## AGENTS.md admission

| Field | Answer |
|---|---|
| MISSION_CLASS | Find & Prove — research + offline IC |
| GAP | Morning-freeze IC tested; Chart-updating cumulative volume IC untested |
| SMALLEST_COMPLETE_CHANGE | This tool + reports/*.md/*.json |
| MINIMUM_SUFFICIENT_EVIDENCE | Per-clock residual IC vs placebo + vs freeze; exact n; density census |
| DECISION_PATH_EFFECT | None — WAIT |
| WHY_NOW | Operator: freeze is anti-cheat not false-positive machine; Chart needs updating-volume test |
| TASK_ADMISSION | Admitted as Find & Prove research only |

## 1) Method (locked)

- Clocks T (ET): `['10:15', '11:00', '12:00', '14:00']`
- Snapshot tolerance: latest chain with ET minute ≤ T and lag ≤ **30** minutes
- Live signals: `VOL`, `OI`, `PRODUCT` (= OI×vol) from that as-of chain
- Baseline: `FREEZE_VOL`, `FREEZE_OI`, `FREEZE_PRODUCT` from morning_full (prefer) or 09:45–10:15 snap — same freeze as prior studies
- Targets on bars with `min_of_day > T` only (pin-to-close blanked if <60m RTH remain)
- ATR for bands from bars before T only
- Primary IC: partial Spearman controlling `DIST_INV` (ATM proximity)
- Placebo: within-day shuffle of signal across strikes
- PASS gates: `{"min_sessions": 80, "min_mean_ic": 0.05, "min_ic_ir": 0.3, "min_hit_rate": 0.55, "min_edge_vs_placebo": 0.04, "bootstrap_excludes_zero": true, "min_edge_vs_freeze": 0.02}`

## 2) Snapshot density (exact, same-turn census)

- **SPY:** RTH chain snaps = **18389** across **87** trading days (`2026-03-25` → `2026-07-30`); snaps/day median=193, mean=211.37; by ET hour={9: 1319, 10: 2703, 11: 2774, 12: 2797, 13: 2902, 14: 2927, 15: 2967}
- **QQQ:** RTH chain snaps = **6161** across **85** trading days (`2026-03-25` → `2026-07-30`); snaps/day median=41, mean=72.48; by ET hour={9: 441, 10: 977, 11: 1022, 12: 969, 13: 928, 14: 921, 15: 903}
- **IWM:** RTH chain snaps = **4948** across **85** trading days (`2026-03-25` → `2026-07-30`); snaps/day median=32, mean=58.21; by ET hour={9: 409, 10: 754, 11: 789, 12: 757, 13: 749, 14: 739, 15: 751}

Clock coverage (days with snap ≤ T within tol):

| Ticker | Clock | Days covered | Total chain days | Mean lag (min) |
|---|---|---:|---:|---:|
| IWM | 10:15 | 64 | 85 | 6.52 |
| IWM | 11:00 | 70 | 85 | 6.87 |
| IWM | 12:00 | 70 | 85 | 8.33 |
| IWM | 14:00 | 68 | 85 | 7.65 |
| QQQ | 10:15 | 64 | 85 | 6.83 |
| QQQ | 11:00 | 72 | 85 | 6.54 |
| QQQ | 12:00 | 70 | 85 | 6.79 |
| QQQ | 14:00 | 70 | 85 | 7.64 |
| SPY | 10:15 | 69 | 87 | 2.88 |
| SPY | 11:00 | 78 | 87 | 2.69 |
| SPY | 12:00 | 75 | 87 | 3.4 |
| SPY | 14:00 | 75 | 87 | 3.81 |

morning_full trading days: `{"SPY": {"trading_days_exact": 9, "min_et": "2026-07-20", "max_et": "2026-07-30"}, "QQQ": {"trading_days_exact": 9, "min_et": "2026-07-20", "max_et": "2026-07-30"}, "IWM": {"trading_days_exact": 9, "min_et": "2026-07-20", "max_et": "2026-07-30"}}`
Freeze observation keys loaded: **202**

## 3) Verdict summary (per clock)

| Clock | n sessions | mean lag | Clock verdict |
|---|---:|---:|---|
| 10:15 | 193 | 5.17 | `FAIL` |
| 11:00 | 215 | 5.24 | `WEAK_LIVE_ABOVE_FREEZE` |
| 12:00 | 213 | 6.03 | `WEAK_LIVE_ABOVE_FREEZE` |
| 14:00 | 210 | 6.36 | `FAIL` |

## 4) Per-clock detail — PRIMARY residual IC + live vs freeze

### Clock 10:15 ET — `FAIL`

- Sessions exact: **193** by ticker `{'SPY': 67, 'QQQ': 62, 'IWM': 64}`
- Date range: `2026-03-25` → `2026-07-30`
- Mean / median snap lag: 5.17 / 2 min
- Mean post-T bars: 342.9; pin included: True (RTH minutes remaining=345)
- Freeze faucet mix: `{'morning_full': 22, 'snapshots_1000et': 171}`
- Drops: `{'short_session': 1, 'atr_zero': 3}`
- Residual verdict counts: `{'PASS': 0, 'WEAK_FAIL': 10, 'FAIL': 20, 'UNDERPOWERED': 0, 'BLANK': 0}`

#### Live vs freeze (ATM-controlled residual mean IC)

| Live | Freeze | Target | live mean IC | freeze mean IC | Δ (live−freeze) | beats freeze? | live verdict | freeze verdict |
|---|---|---|---:|---:|---:|---|---|---|
| VOL | FREEZE_VOL | time_in_band | 0.0462 | 0.0378 | 0.0084 | False | `WEAK_FAIL` | `WEAK_FAIL` |
| VOL | FREEZE_VOL | failed_break_rate | 0.0375 | 0.0300 | 0.0074 | False | `WEAK_FAIL` | `WEAK_FAIL` |
| VOL | FREEZE_VOL | pin_closeness | 0.0076 | 0.0066 | 0.0010 | False | `FAIL` | `WEAK_FAIL` |
| VOL | FREEZE_VOL | signed_pull | 0.0164 | 0.0151 | 0.0013 | False | `WEAK_FAIL` | `WEAK_FAIL` |
| VOL | FREEZE_VOL | composite | 0.0215 | 0.0170 | 0.0046 | False | `FAIL` | `FAIL` |
| OI | FREEZE_OI | time_in_band | -0.0083 | -0.0181 | 0.0098 | False | `FAIL` | `FAIL` |
| OI | FREEZE_OI | failed_break_rate | -0.0006 | -0.0106 | 0.0100 | False | `FAIL` | `FAIL` |
| OI | FREEZE_OI | pin_closeness | -0.0624 | -0.0319 | -0.0306 | False | `FAIL` | `FAIL` |
| OI | FREEZE_OI | signed_pull | -0.0450 | -0.0111 | -0.0339 | False | `FAIL` | `FAIL` |
| OI | FREEZE_OI | composite | -0.0393 | -0.0101 | -0.0292 | False | `FAIL` | `FAIL` |
| PRODUCT | FREEZE_PRODUCT | time_in_band | 0.0365 | 0.0236 | 0.0130 | False | `WEAK_FAIL` | `FAIL` |
| PRODUCT | FREEZE_PRODUCT | failed_break_rate | 0.0349 | 0.0251 | 0.0098 | False | `WEAK_FAIL` | `WEAK_FAIL` |
| PRODUCT | FREEZE_PRODUCT | pin_closeness | -0.0189 | -0.0040 | -0.0149 | False | `FAIL` | `FAIL` |
| PRODUCT | FREEZE_PRODUCT | signed_pull | -0.0052 | 0.0128 | -0.0180 | False | `FAIL` | `FAIL` |
| PRODUCT | FREEZE_PRODUCT | composite | 0.0012 | 0.0129 | -0.0117 | False | `FAIL` | `FAIL` |

#### Residual IC cells (control = DIST_INV)

| Signal | Target | n | mean IC | IC IR | hit% | plc mean | edge | boot CI | Verdict |
|---|---|---:|---:|---:|---:|---:|---:|---|---|
| VOL | time_in_band | 193 | 0.0462 | 0.134 | 57.5% | 0.0003 | 0.0459 | [-0.0057, 0.0929] | `WEAK_FAIL` |
| VOL | failed_break_rate | 193 | 0.0375 | 0.119 | 58.0% | -0.0240 | 0.0615 | [-0.0043, 0.0808] | `WEAK_FAIL` |
| VOL | pin_closeness | 183 | 0.0076 | 0.013 | 49.7% | -0.0151 | 0.0227 | [-0.0777, 0.0915] | `FAIL` |
| VOL | signed_pull | 193 | 0.0164 | 0.028 | 50.3% | 0.0064 | 0.0100 | [-0.0598, 0.0998] | `WEAK_FAIL` |
| VOL | composite | 193 | 0.0215 | 0.039 | 50.8% | 0.0217 | -0.0002 | [-0.0557, 0.1009] | `FAIL` |
| OI | time_in_band | 193 | -0.0083 | -0.032 | 48.2% | 0.0198 | -0.0281 | [-0.0522, 0.0322] | `FAIL` |
| OI | failed_break_rate | 193 | -0.0006 | -0.002 | 48.2% | -0.0243 | 0.0237 | [-0.0381, 0.0366] | `FAIL` |
| OI | pin_closeness | 183 | -0.0624 | -0.134 | 40.4% | 0.0004 | -0.0628 | [-0.1180, 0.0083] | `FAIL` |
| OI | signed_pull | 193 | -0.0450 | -0.094 | 43.5% | -0.0469 | 0.0018 | [-0.1171, 0.0288] | `FAIL` |
| OI | composite | 193 | -0.0393 | -0.085 | 45.1% | 0.0038 | -0.0431 | [-0.1039, 0.0284] | `FAIL` |
| PRODUCT | time_in_band | 193 | 0.0365 | 0.127 | 57.5% | -0.0088 | 0.0453 | [-0.0029, 0.0739] | `WEAK_FAIL` |
| PRODUCT | failed_break_rate | 193 | 0.0349 | 0.126 | 52.8% | 0.0008 | 0.0341 | [-0.0062, 0.0766] | `WEAK_FAIL` |
| PRODUCT | pin_closeness | 183 | -0.0189 | -0.036 | 45.4% | 0.0105 | -0.0294 | [-0.0947, 0.0657] | `FAIL` |
| PRODUCT | signed_pull | 193 | -0.0052 | -0.010 | 47.7% | 0.0072 | -0.0124 | [-0.0758, 0.0748] | `FAIL` |
| PRODUCT | composite | 193 | 0.0012 | 0.002 | 48.2% | -0.0200 | 0.0212 | [-0.0682, 0.0715] | `FAIL` |
| FREEZE_VOL | time_in_band | 193 | 0.0378 | 0.108 | 54.9% | -0.0085 | 0.0463 | [-0.0096, 0.0874] | `WEAK_FAIL` |
| FREEZE_VOL | failed_break_rate | 193 | 0.0300 | 0.093 | 58.0% | -0.0187 | 0.0487 | [-0.0108, 0.0762] | `WEAK_FAIL` |
| FREEZE_VOL | pin_closeness | 183 | 0.0066 | 0.011 | 50.3% | 0.0029 | 0.0037 | [-0.0847, 0.0942] | `WEAK_FAIL` |
| FREEZE_VOL | signed_pull | 193 | 0.0151 | 0.026 | 50.3% | -0.0096 | 0.0246 | [-0.0668, 0.1036] | `WEAK_FAIL` |
| FREEZE_VOL | composite | 193 | 0.0170 | 0.030 | 50.3% | 0.0202 | -0.0033 | [-0.0661, 0.0910] | `FAIL` |
| FREEZE_OI | time_in_band | 193 | -0.0181 | -0.070 | 45.6% | -0.0124 | -0.0058 | [-0.0507, 0.0205] | `FAIL` |
| FREEZE_OI | failed_break_rate | 193 | -0.0106 | -0.042 | 49.2% | 0.0185 | -0.0291 | [-0.0445, 0.0220] | `FAIL` |
| FREEZE_OI | pin_closeness | 183 | -0.0319 | -0.068 | 43.7% | 0.0046 | -0.0364 | [-0.0967, 0.0344] | `FAIL` |
| FREEZE_OI | signed_pull | 193 | -0.0111 | -0.023 | 45.6% | -0.0153 | 0.0042 | [-0.0770, 0.0637] | `FAIL` |
| FREEZE_OI | composite | 193 | -0.0101 | -0.022 | 47.7% | 0.0184 | -0.0284 | [-0.0729, 0.0522] | `FAIL` |
| FREEZE_PRODUCT | time_in_band | 193 | 0.0236 | 0.080 | 52.3% | 0.0327 | -0.0091 | [-0.0158, 0.0674] | `FAIL` |
| FREEZE_PRODUCT | failed_break_rate | 193 | 0.0251 | 0.090 | 51.3% | -0.0155 | 0.0406 | [-0.0152, 0.0645] | `WEAK_FAIL` |
| FREEZE_PRODUCT | pin_closeness | 183 | -0.0040 | -0.008 | 44.8% | -0.0154 | 0.0114 | [-0.0802, 0.0657] | `FAIL` |
| FREEZE_PRODUCT | signed_pull | 193 | 0.0128 | 0.024 | 47.7% | 0.0046 | 0.0081 | [-0.0611, 0.0810] | `FAIL` |
| FREEZE_PRODUCT | composite | 193 | 0.0129 | 0.026 | 49.7% | -0.0107 | 0.0236 | [-0.0486, 0.0815] | `FAIL` |

### Clock 11:00 ET — `WEAK_LIVE_ABOVE_FREEZE`

- Sessions exact: **215** by ticker `{'SPY': 76, 'QQQ': 70, 'IWM': 69}`
- Date range: `2026-03-25` → `2026-07-30`
- Mean / median snap lag: 5.24 / 2 min
- Mean post-T bars: 298.6; pin included: True (RTH minutes remaining=300)
- Freeze faucet mix: `{'morning_full': 25, 'snapshots_1000et': 164}`
- Drops: `{'no_freeze_obs': 26, 'freeze_signals_zeroed': 26, 'short_session': 2, 'atr_zero': 3}`
- Residual verdict counts: `{'PASS': 0, 'WEAK_FAIL': 1, 'FAIL': 29, 'UNDERPOWERED': 0, 'BLANK': 0}`

#### Live vs freeze (ATM-controlled residual mean IC)

| Live | Freeze | Target | live mean IC | freeze mean IC | Δ (live−freeze) | beats freeze? | live verdict | freeze verdict |
|---|---|---|---:|---:|---:|---|---|---|
| VOL | FREEZE_VOL | time_in_band | 0.0107 | -0.0160 | 0.0267 | True | `WEAK_FAIL` | `FAIL` |
| VOL | FREEZE_VOL | failed_break_rate | 0.0065 | -0.0077 | 0.0141 | False | `FAIL` | `FAIL` |
| VOL | FREEZE_VOL | pin_closeness | -0.0206 | 0.0002 | -0.0208 | False | `FAIL` | `FAIL` |
| VOL | FREEZE_VOL | signed_pull | -0.0571 | -0.0169 | -0.0402 | False | `FAIL` | `FAIL` |
| VOL | FREEZE_VOL | composite | -0.0607 | -0.0324 | -0.0283 | False | `FAIL` | `FAIL` |
| OI | FREEZE_OI | time_in_band | -0.0352 | -0.0499 | 0.0148 | False | `FAIL` | `FAIL` |
| OI | FREEZE_OI | failed_break_rate | -0.0243 | -0.0389 | 0.0146 | False | `FAIL` | `FAIL` |
| OI | FREEZE_OI | pin_closeness | -0.0935 | -0.0604 | -0.0330 | False | `FAIL` | `FAIL` |
| OI | FREEZE_OI | signed_pull | -0.0984 | -0.0627 | -0.0356 | False | `FAIL` | `FAIL` |
| OI | FREEZE_OI | composite | -0.0951 | -0.0698 | -0.0253 | False | `FAIL` | `FAIL` |
| PRODUCT | FREEZE_PRODUCT | time_in_band | -0.0087 | -0.0415 | 0.0328 | True | `FAIL` | `FAIL` |
| PRODUCT | FREEZE_PRODUCT | failed_break_rate | -0.0109 | -0.0338 | 0.0229 | True | `FAIL` | `FAIL` |
| PRODUCT | FREEZE_PRODUCT | pin_closeness | -0.0722 | -0.0491 | -0.0231 | False | `FAIL` | `FAIL` |
| PRODUCT | FREEZE_PRODUCT | signed_pull | -0.0980 | -0.0615 | -0.0366 | False | `FAIL` | `FAIL` |
| PRODUCT | FREEZE_PRODUCT | composite | -0.0967 | -0.0771 | -0.0196 | False | `FAIL` | `FAIL` |

#### Residual IC cells (control = DIST_INV)

| Signal | Target | n | mean IC | IC IR | hit% | plc mean | edge | boot CI | Verdict |
|---|---|---:|---:|---:|---:|---:|---:|---|---|
| VOL | time_in_band | 215 | 0.0107 | 0.032 | 55.8% | 0.0029 | 0.0078 | [-0.0344, 0.0513] | `WEAK_FAIL` |
| VOL | failed_break_rate | 215 | 0.0065 | 0.021 | 56.7% | 0.0076 | -0.0011 | [-0.0346, 0.0445] | `FAIL` |
| VOL | pin_closeness | 199 | -0.0206 | -0.032 | 48.7% | -0.0220 | 0.0014 | [-0.1035, 0.0789] | `FAIL` |
| VOL | signed_pull | 215 | -0.0571 | -0.088 | 45.6% | 0.0270 | -0.0841 | [-0.1493, 0.0260] | `FAIL` |
| VOL | composite | 215 | -0.0607 | -0.099 | 46.0% | -0.0038 | -0.0569 | [-0.1466, 0.0200] | `FAIL` |
| OI | time_in_band | 215 | -0.0352 | -0.164 | 42.8% | -0.0117 | -0.0234 | [-0.0620, -0.0077] | `FAIL` |
| OI | failed_break_rate | 215 | -0.0243 | -0.111 | 43.3% | 0.0203 | -0.0447 | [-0.0534, 0.0068] | `FAIL` |
| OI | pin_closeness | 199 | -0.0935 | -0.205 | 39.7% | 0.0245 | -0.1180 | [-0.1564, -0.0315] | `FAIL` |
| OI | signed_pull | 215 | -0.0984 | -0.209 | 40.5% | -0.0499 | -0.0484 | [-0.1638, -0.0441] | `FAIL` |
| OI | composite | 215 | -0.0951 | -0.209 | 40.9% | 0.0225 | -0.1176 | [-0.1542, -0.0315] | `FAIL` |
| PRODUCT | time_in_band | 215 | -0.0087 | -0.033 | 50.7% | 0.0082 | -0.0169 | [-0.0402, 0.0292] | `FAIL` |
| PRODUCT | failed_break_rate | 215 | -0.0109 | -0.043 | 54.9% | -0.0001 | -0.0108 | [-0.0420, 0.0237] | `FAIL` |
| PRODUCT | pin_closeness | 199 | -0.0722 | -0.126 | 44.2% | 0.0011 | -0.0733 | [-0.1444, 0.0083] | `FAIL` |
| PRODUCT | signed_pull | 215 | -0.0980 | -0.170 | 42.3% | -0.0152 | -0.0828 | [-0.1736, -0.0223] | `FAIL` |
| PRODUCT | composite | 215 | -0.0967 | -0.175 | 41.9% | -0.0283 | -0.0684 | [-0.1674, -0.0359] | `FAIL` |
| FREEZE_VOL | time_in_band | 189 | -0.0160 | -0.045 | 51.9% | -0.0306 | 0.0146 | [-0.0637, 0.0375] | `FAIL` |
| FREEZE_VOL | failed_break_rate | 189 | -0.0077 | -0.023 | 55.0% | 0.0072 | -0.0148 | [-0.0600, 0.0387] | `FAIL` |
| FREEZE_VOL | pin_closeness | 175 | 0.0002 | 0.000 | 48.6% | 0.0108 | -0.0106 | [-0.0965, 0.1002] | `FAIL` |
| FREEZE_VOL | signed_pull | 189 | -0.0169 | -0.025 | 48.1% | 0.0080 | -0.0249 | [-0.1175, 0.0831] | `FAIL` |
| FREEZE_VOL | composite | 189 | -0.0324 | -0.051 | 48.1% | -0.0079 | -0.0245 | [-0.1188, 0.0528] | `FAIL` |
| FREEZE_OI | time_in_band | 189 | -0.0499 | -0.204 | 40.2% | 0.0131 | -0.0630 | [-0.0847, -0.0154] | `FAIL` |
| FREEZE_OI | failed_break_rate | 189 | -0.0389 | -0.166 | 41.8% | 0.0066 | -0.0455 | [-0.0712, -0.0035] | `FAIL` |
| FREEZE_OI | pin_closeness | 175 | -0.0604 | -0.123 | 44.6% | 0.0071 | -0.0675 | [-0.1315, 0.0077] | `FAIL` |
| FREEZE_OI | signed_pull | 189 | -0.0627 | -0.126 | 44.4% | 0.0040 | -0.0667 | [-0.1285, 0.0071] | `FAIL` |
| FREEZE_OI | composite | 189 | -0.0698 | -0.146 | 43.4% | 0.0181 | -0.0879 | [-0.1335, 0.0021] | `FAIL` |
| FREEZE_PRODUCT | time_in_band | 189 | -0.0415 | -0.134 | 44.4% | -0.0062 | -0.0353 | [-0.0873, 0.0006] | `FAIL` |
| FREEZE_PRODUCT | failed_break_rate | 189 | -0.0338 | -0.116 | 47.1% | 0.0135 | -0.0473 | [-0.0733, 0.0080] | `FAIL` |
| FREEZE_PRODUCT | pin_closeness | 175 | -0.0491 | -0.082 | 45.7% | 0.0054 | -0.0545 | [-0.1443, 0.0393] | `FAIL` |
| FREEZE_PRODUCT | signed_pull | 189 | -0.0615 | -0.103 | 47.1% | -0.0115 | -0.0499 | [-0.1506, 0.0249] | `FAIL` |
| FREEZE_PRODUCT | composite | 189 | -0.0771 | -0.136 | 43.9% | 0.0096 | -0.0868 | [-0.1580, 0.0060] | `FAIL` |

### Clock 12:00 ET — `WEAK_LIVE_ABOVE_FREEZE`

- Sessions exact: **213** by ticker `{'SPY': 74, 'QQQ': 69, 'IWM': 70}`
- Date range: `2026-03-25` → `2026-07-30`
- Mean / median snap lag: 6.03 / 3 min
- Mean post-T bars: 238.0; pin included: True (RTH minutes remaining=240)
- Freeze faucet mix: `{'morning_full': 27, 'snapshots_1000et': 155}`
- Drops: `{'no_freeze_obs': 31, 'freeze_signals_zeroed': 31, 'atr_zero': 2}`
- Residual verdict counts: `{'PASS': 0, 'WEAK_FAIL': 6, 'FAIL': 24, 'UNDERPOWERED': 0, 'BLANK': 0}`

#### Live vs freeze (ATM-controlled residual mean IC)

| Live | Freeze | Target | live mean IC | freeze mean IC | Δ (live−freeze) | beats freeze? | live verdict | freeze verdict |
|---|---|---|---:|---:|---:|---|---|---|
| VOL | FREEZE_VOL | time_in_band | 0.0420 | -0.0011 | 0.0431 | True | `WEAK_FAIL` | `FAIL` |
| VOL | FREEZE_VOL | failed_break_rate | 0.0275 | -0.0054 | 0.0329 | True | `WEAK_FAIL` | `FAIL` |
| VOL | FREEZE_VOL | pin_closeness | -0.0050 | 0.0306 | -0.0356 | False | `FAIL` | `FAIL` |
| VOL | FREEZE_VOL | signed_pull | -0.0157 | 0.0474 | -0.0631 | False | `FAIL` | `WEAK_FAIL` |
| VOL | FREEZE_VOL | composite | -0.0110 | 0.0440 | -0.0550 | False | `FAIL` | `WEAK_FAIL` |
| OI | FREEZE_OI | time_in_band | -0.0240 | -0.0356 | 0.0116 | False | `FAIL` | `FAIL` |
| OI | FREEZE_OI | failed_break_rate | -0.0256 | -0.0416 | 0.0160 | False | `FAIL` | `FAIL` |
| OI | FREEZE_OI | pin_closeness | -0.0769 | -0.0257 | -0.0512 | False | `FAIL` | `FAIL` |
| OI | FREEZE_OI | signed_pull | -0.0860 | -0.0239 | -0.0621 | False | `FAIL` | `FAIL` |
| OI | FREEZE_OI | composite | -0.0847 | -0.0325 | -0.0522 | False | `FAIL` | `FAIL` |
| PRODUCT | FREEZE_PRODUCT | time_in_band | 0.0161 | -0.0191 | 0.0352 | True | `WEAK_FAIL` | `FAIL` |
| PRODUCT | FREEZE_PRODUCT | failed_break_rate | 0.0059 | -0.0245 | 0.0304 | True | `WEAK_FAIL` | `FAIL` |
| PRODUCT | FREEZE_PRODUCT | pin_closeness | -0.0281 | -0.0041 | -0.0240 | False | `FAIL` | `FAIL` |
| PRODUCT | FREEZE_PRODUCT | signed_pull | -0.0456 | 0.0031 | -0.0487 | False | `FAIL` | `FAIL` |
| PRODUCT | FREEZE_PRODUCT | composite | -0.0441 | -0.0029 | -0.0413 | False | `FAIL` | `FAIL` |

#### Residual IC cells (control = DIST_INV)

| Signal | Target | n | mean IC | IC IR | hit% | plc mean | edge | boot CI | Verdict |
|---|---|---:|---:|---:|---:|---:|---:|---|---|
| VOL | time_in_band | 212 | 0.0420 | 0.146 | 56.6% | 0.0150 | 0.0270 | [0.0025, 0.0800] | `WEAK_FAIL` |
| VOL | failed_break_rate | 211 | 0.0275 | 0.105 | 56.4% | -0.0125 | 0.0400 | [-0.0042, 0.0591] | `WEAK_FAIL` |
| VOL | pin_closeness | 197 | -0.0050 | -0.007 | 48.7% | -0.0037 | -0.0012 | [-0.1029, 0.0975] | `FAIL` |
| VOL | signed_pull | 213 | -0.0157 | -0.022 | 49.3% | 0.0260 | -0.0417 | [-0.1124, 0.0929] | `FAIL` |
| VOL | composite | 213 | -0.0110 | -0.016 | 48.8% | 0.0096 | -0.0206 | [-0.0924, 0.0810] | `FAIL` |
| OI | time_in_band | 212 | -0.0240 | -0.110 | 43.9% | -0.0153 | -0.0088 | [-0.0516, 0.0043] | `FAIL` |
| OI | failed_break_rate | 211 | -0.0256 | -0.116 | 42.7% | -0.0232 | -0.0023 | [-0.0589, 0.0013] | `FAIL` |
| OI | pin_closeness | 197 | -0.0769 | -0.159 | 38.6% | -0.0135 | -0.0634 | [-0.1471, -0.0007] | `FAIL` |
| OI | signed_pull | 213 | -0.0860 | -0.174 | 39.4% | 0.0013 | -0.0873 | [-0.1610, -0.0249] | `FAIL` |
| OI | composite | 213 | -0.0847 | -0.177 | 38.5% | -0.0034 | -0.0813 | [-0.1465, -0.0145] | `FAIL` |
| PRODUCT | time_in_band | 212 | 0.0161 | 0.066 | 54.7% | -0.0215 | 0.0376 | [-0.0154, 0.0490] | `WEAK_FAIL` |
| PRODUCT | failed_break_rate | 211 | 0.0059 | 0.027 | 54.5% | -0.0029 | 0.0088 | [-0.0242, 0.0374] | `WEAK_FAIL` |
| PRODUCT | pin_closeness | 197 | -0.0281 | -0.046 | 47.7% | 0.0103 | -0.0385 | [-0.1041, 0.0466] | `FAIL` |
| PRODUCT | signed_pull | 213 | -0.0456 | -0.073 | 48.8% | -0.0198 | -0.0258 | [-0.1438, 0.0384] | `FAIL` |
| PRODUCT | composite | 213 | -0.0441 | -0.074 | 46.5% | -0.0074 | -0.0367 | [-0.1216, 0.0345] | `FAIL` |
| FREEZE_VOL | time_in_band | 180 | -0.0011 | -0.004 | 49.4% | -0.0225 | 0.0214 | [-0.0473, 0.0439] | `FAIL` |
| FREEZE_VOL | failed_break_rate | 179 | -0.0054 | -0.019 | 49.7% | -0.0111 | 0.0057 | [-0.0456, 0.0413] | `FAIL` |
| FREEZE_VOL | pin_closeness | 168 | 0.0306 | 0.044 | 49.4% | -0.0004 | 0.0311 | [-0.0757, 0.1299] | `FAIL` |
| FREEZE_VOL | signed_pull | 181 | 0.0474 | 0.069 | 53.6% | -0.0232 | 0.0706 | [-0.0543, 0.1493] | `WEAK_FAIL` |
| FREEZE_VOL | composite | 181 | 0.0440 | 0.066 | 53.0% | 0.0042 | 0.0398 | [-0.0421, 0.1398] | `WEAK_FAIL` |
| FREEZE_OI | time_in_band | 180 | -0.0356 | -0.159 | 42.2% | -0.0309 | -0.0046 | [-0.0697, 0.0001] | `FAIL` |
| FREEZE_OI | failed_break_rate | 179 | -0.0416 | -0.192 | 41.9% | -0.0130 | -0.0285 | [-0.0712, -0.0124] | `FAIL` |
| FREEZE_OI | pin_closeness | 168 | -0.0257 | -0.049 | 45.2% | -0.0237 | -0.0020 | [-0.1043, 0.0503] | `FAIL` |
| FREEZE_OI | signed_pull | 181 | -0.0239 | -0.045 | 44.8% | 0.0343 | -0.0582 | [-0.0980, 0.0562] | `FAIL` |
| FREEZE_OI | composite | 181 | -0.0325 | -0.064 | 44.8% | 0.0145 | -0.0470 | [-0.1087, 0.0361] | `FAIL` |
| FREEZE_PRODUCT | time_in_band | 180 | -0.0191 | -0.073 | 46.1% | -0.0015 | -0.0176 | [-0.0575, 0.0228] | `FAIL` |
| FREEZE_PRODUCT | failed_break_rate | 179 | -0.0245 | -0.102 | 45.3% | -0.0316 | 0.0070 | [-0.0585, 0.0114] | `FAIL` |
| FREEZE_PRODUCT | pin_closeness | 168 | -0.0041 | -0.006 | 44.6% | -0.0360 | 0.0319 | [-0.0905, 0.0839] | `FAIL` |
| FREEZE_PRODUCT | signed_pull | 181 | 0.0031 | 0.005 | 45.9% | -0.0008 | 0.0040 | [-0.0924, 0.0997] | `FAIL` |
| FREEZE_PRODUCT | composite | 181 | -0.0029 | -0.005 | 45.3% | 0.0021 | -0.0050 | [-0.0916, 0.0903] | `FAIL` |

### Clock 14:00 ET — `FAIL`

- Sessions exact: **210** by ticker `{'SPY': 73, 'QQQ': 69, 'IWM': 68}`
- Date range: `2026-03-25` → `2026-07-30`
- Mean / median snap lag: 6.36 / 3.0 min
- Mean post-T bars: 117.9; pin included: True (RTH minutes remaining=120)
- Freeze faucet mix: `{'morning_full': 27, 'snapshots_1000et': 149}`
- Drops: `{'no_freeze_obs': 34, 'freeze_signals_zeroed': 34, 'atr_zero': 3}`
- Residual verdict counts: `{'PASS': 0, 'WEAK_FAIL': 0, 'FAIL': 30, 'UNDERPOWERED': 0, 'BLANK': 0}`

#### Live vs freeze (ATM-controlled residual mean IC)

| Live | Freeze | Target | live mean IC | freeze mean IC | Δ (live−freeze) | beats freeze? | live verdict | freeze verdict |
|---|---|---|---:|---:|---:|---|---|---|
| VOL | FREEZE_VOL | time_in_band | 0.0023 | -0.0419 | 0.0441 | True | `FAIL` | `FAIL` |
| VOL | FREEZE_VOL | failed_break_rate | -0.0051 | -0.0402 | 0.0351 | True | `FAIL` | `FAIL` |
| VOL | FREEZE_VOL | pin_closeness | -0.0374 | 0.0012 | -0.0386 | False | `FAIL` | `FAIL` |
| VOL | FREEZE_VOL | signed_pull | -0.0365 | -0.0309 | -0.0056 | False | `FAIL` | `FAIL` |
| VOL | FREEZE_VOL | composite | -0.0331 | -0.0327 | -0.0003 | False | `FAIL` | `FAIL` |
| OI | FREEZE_OI | time_in_band | -0.0310 | -0.0467 | 0.0157 | False | `FAIL` | `FAIL` |
| OI | FREEZE_OI | failed_break_rate | -0.0384 | -0.0470 | 0.0086 | False | `FAIL` | `FAIL` |
| OI | FREEZE_OI | pin_closeness | -0.1117 | -0.0787 | -0.0330 | False | `FAIL` | `FAIL` |
| OI | FREEZE_OI | signed_pull | -0.1025 | -0.0897 | -0.0128 | False | `FAIL` | `FAIL` |
| OI | FREEZE_OI | composite | -0.0995 | -0.0959 | -0.0036 | False | `FAIL` | `FAIL` |
| PRODUCT | FREEZE_PRODUCT | time_in_band | -0.0027 | -0.0382 | 0.0355 | True | `FAIL` | `FAIL` |
| PRODUCT | FREEZE_PRODUCT | failed_break_rate | -0.0106 | -0.0387 | 0.0280 | True | `FAIL` | `FAIL` |
| PRODUCT | FREEZE_PRODUCT | pin_closeness | -0.0586 | -0.0378 | -0.0208 | False | `FAIL` | `FAIL` |
| PRODUCT | FREEZE_PRODUCT | signed_pull | -0.0551 | -0.0558 | 0.0007 | False | `FAIL` | `FAIL` |
| PRODUCT | FREEZE_PRODUCT | composite | -0.0531 | -0.0592 | 0.0061 | False | `FAIL` | `FAIL` |

#### Residual IC cells (control = DIST_INV)

| Signal | Target | n | mean IC | IC IR | hit% | plc mean | edge | boot CI | Verdict |
|---|---|---:|---:|---:|---:|---:|---:|---|---|
| VOL | time_in_band | 207 | 0.0023 | 0.009 | 58.9% | 0.0206 | -0.0183 | [-0.0317, 0.0338] | `FAIL` |
| VOL | failed_break_rate | 204 | -0.0051 | -0.021 | 53.9% | 0.0215 | -0.0266 | [-0.0383, 0.0276] | `FAIL` |
| VOL | pin_closeness | 183 | -0.0374 | -0.051 | 47.0% | -0.0392 | 0.0019 | [-0.1398, 0.0672] | `FAIL` |
| VOL | signed_pull | 210 | -0.0365 | -0.049 | 48.1% | -0.0060 | -0.0305 | [-0.1341, 0.0527] | `FAIL` |
| VOL | composite | 210 | -0.0331 | -0.046 | 48.1% | 0.0031 | -0.0362 | [-0.1295, 0.0698] | `FAIL` |
| OI | time_in_band | 207 | -0.0310 | -0.146 | 51.2% | 0.0372 | -0.0682 | [-0.0585, -0.0026] | `FAIL` |
| OI | failed_break_rate | 204 | -0.0384 | -0.185 | 47.1% | -0.0059 | -0.0325 | [-0.0654, -0.0084] | `FAIL` |
| OI | pin_closeness | 183 | -0.1117 | -0.238 | 39.9% | 0.0150 | -0.1267 | [-0.1819, -0.0362] | `FAIL` |
| OI | signed_pull | 210 | -0.1025 | -0.203 | 41.0% | -0.0165 | -0.0860 | [-0.1706, -0.0334] | `FAIL` |
| OI | composite | 210 | -0.0995 | -0.202 | 40.0% | 0.0033 | -0.1028 | [-0.1673, -0.0324] | `FAIL` |
| PRODUCT | time_in_band | 207 | -0.0027 | -0.013 | 53.1% | 0.0101 | -0.0128 | [-0.0292, 0.0278] | `FAIL` |
| PRODUCT | failed_break_rate | 204 | -0.0106 | -0.053 | 54.4% | 0.0308 | -0.0414 | [-0.0371, 0.0156] | `FAIL` |
| PRODUCT | pin_closeness | 183 | -0.0586 | -0.091 | 45.9% | -0.0097 | -0.0489 | [-0.1495, 0.0221] | `FAIL` |
| PRODUCT | signed_pull | 210 | -0.0551 | -0.083 | 46.7% | 0.0008 | -0.0560 | [-0.1496, 0.0284] | `FAIL` |
| PRODUCT | composite | 210 | -0.0531 | -0.082 | 45.7% | -0.0167 | -0.0363 | [-0.1409, 0.0350] | `FAIL` |
| FREEZE_VOL | time_in_band | 172 | -0.0419 | -0.174 | 41.3% | 0.0086 | -0.0505 | [-0.0784, -0.0044] | `FAIL` |
| FREEZE_VOL | failed_break_rate | 170 | -0.0402 | -0.177 | 41.8% | 0.0199 | -0.0600 | [-0.0725, -0.0076] | `FAIL` |
| FREEZE_VOL | pin_closeness | 153 | 0.0012 | 0.002 | 49.7% | -0.0159 | 0.0171 | [-0.1222, 0.1226] | `FAIL` |
| FREEZE_VOL | signed_pull | 175 | -0.0309 | -0.041 | 49.1% | -0.0084 | -0.0226 | [-0.1366, 0.0816] | `FAIL` |
| FREEZE_VOL | composite | 175 | -0.0327 | -0.045 | 49.1% | 0.0133 | -0.0461 | [-0.1432, 0.0802] | `FAIL` |
| FREEZE_OI | time_in_band | 172 | -0.0467 | -0.215 | 48.3% | 0.0024 | -0.0491 | [-0.0799, -0.0172] | `FAIL` |
| FREEZE_OI | failed_break_rate | 170 | -0.0470 | -0.225 | 47.1% | 0.0056 | -0.0526 | [-0.0753, -0.0196] | `FAIL` |
| FREEZE_OI | pin_closeness | 153 | -0.0787 | -0.149 | 43.1% | -0.0048 | -0.0739 | [-0.1566, 0.0031] | `FAIL` |
| FREEZE_OI | signed_pull | 175 | -0.0897 | -0.162 | 42.9% | -0.0010 | -0.0887 | [-0.1722, -0.0095] | `FAIL` |
| FREEZE_OI | composite | 175 | -0.0959 | -0.181 | 41.1% | -0.0292 | -0.0667 | [-0.1724, -0.0199] | `FAIL` |
| FREEZE_PRODUCT | time_in_band | 172 | -0.0382 | -0.175 | 45.9% | -0.0074 | -0.0307 | [-0.0732, -0.0063] | `FAIL` |
| FREEZE_PRODUCT | failed_break_rate | 170 | -0.0387 | -0.187 | 43.5% | 0.0232 | -0.0619 | [-0.0689, -0.0087] | `FAIL` |
| FREEZE_PRODUCT | pin_closeness | 153 | -0.0378 | -0.057 | 45.8% | 0.0161 | -0.0539 | [-0.1389, 0.0888] | `FAIL` |
| FREEZE_PRODUCT | signed_pull | 175 | -0.0558 | -0.082 | 46.3% | 0.0280 | -0.0838 | [-0.1585, 0.0327] | `FAIL` |
| FREEZE_PRODUCT | composite | 175 | -0.0592 | -0.090 | 46.3% | -0.0063 | -0.0528 | [-0.1499, 0.0436] | `FAIL` |

## 5) Fair-method / limits

- Equal-width ±3% moneyness band (no wing SUM traps).
- Cross-sectional IC within day; placebo = within-day shuffle.
- Primary claim = partial Spearman vs DIST_INV (ATM control).
- Snapshots skipped when lag > tol — thin clocks reported as UNDERPOWERED, not invented.
- Freeze signals zeroed when morning obs missing for that day (counted in drops).
- failed_break_rate sparse when pierces rare; pin blanked if <60m day left (not triggered at these clocks — all have ≥120m).
- No costs; no Decide path; ranking IC ≠ tradeable edge.

Elapsed: 73.01s
Generated: 2026-07-31T01:36:18.781146+00:00
