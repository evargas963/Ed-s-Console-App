# SPY 2026-07-30 — spot vs storm + open accrual

**MISSION_CLASS:** Collect evidence + descriptive Chart read  
**GAP:** Operator asked match-up table + whether chains accrue from the open  
**SMALLEST_COMPLETE_CHANGE:** Report only (no UI / Decide / code)  
**MINIMUM_SUFFICIENT_EVIDENCE:** Same-turn SQL + reused storm1 hourly file  
**DECISION_PATH_EFFECT:** none (WAIT; no admission)  
**WHY_NOW:** Operator questions  
**TASK_ADMISSION:** Collect/ops evidence + Find descriptive surface; Decide untouched  

Reproduce:

```bash
python scratchpad/_spy_hourly_gamma_vol_storm.py
python scratchpad/_spy_spot_vs_storm_and_open_accrual.py
python scratchpad/_open_gap_detail.py
```

Storm formula (primary): `storm1 = inv_rank(vol) × inv_rank(|net_gex_1pct|)` within ±5% of spot. Source: `scratchpad/_spy_hourly_gamma_vol_storm_out.json` (day_et=2026-07-30).

Trade-through: `price_bars_1m` OHLC in the next hour (`high≥K` and `low≤K`); n_bars=60 each hour (PROVEN).

## Spot vs storm1

| Hour ET | Hour CT | Spot | Storm | Dist pts | Dist % | Side | Next-hour tag / through (1m bars) |
|--------:|--------:|-----:|------:|---------:|-------:|:-----|:----------------------------------|
| 10:00 | 09:00 | 738.100 | 738.0 | +0.100 | +0.014% | above | YES (735.61–739.30) |
| 11:00 | 10:00 | 738.700 | 738.0 | +0.700 | +0.095% | above | NO (734.59–737.67) |
| 12:00 | 11:00 | 736.860 | 738.0 | −1.140 | −0.154% | below | YES (736.87–739.22) |
| 13:00 | 12:00 | 739.010 | 738.0 | +1.010 | +0.137% | above | NO (738.98–740.38) |
| 14:00 | 13:00 | 739.915 | 740.0 | −0.085 | −0.011% | below | YES (739.71–740.83) |
| 15:00 | 14:00 | 740.160 | 740.0 | +0.160 | +0.022% | above | NO (740.74–742.45) |
| latest | — | 743.380 | 742.0 | +1.380 | +0.186% | above | — |

Closest marks: 14:00 (−0.085 pt) and 10:00 (+0.100 pt).

## Open accrual verdict: **PARTIAL / late today**

| Fact | Value (PROVEN) |
|------|----------------|
| RTH open | 09:30:00 ET = 08:30:00 CT |
| Last pre-open chain | 09:29:05 ET / 08:29:05 CT (`ui_rest`) |
| First post-open chain | **09:53:02 ET / 08:53:02 CT** (`ui_rest`, 180 contracts) |
| Gap after open | **1382.3 s = 23.0 min** |
| `option_chain_morning_full` | same stamp 09:53:02 ET; n_contracts=3060; source=`schwab_chain_wide_gex` |
| Snaps 09:30–09:53 | COUNT=23 with_chain=0 — all `base_money_path` quote-only |
| Chain density 09:30–10:30 | COUNT=13 |
| Median chain gap 09:30–11:00 | 123.8 s (among 16 chain rows) |
| Volume after first chain | 09:53 sumVol=807,599 → 09:57=908,906 → 10:05=1,177,633 |

Recent first post-09:30 chain (SPY): 07-24 +15s, 07-25 +12s, 07-26 +9s, 07-27 +17m, 07-28 +51m, 07-29 +28s, **07-30 +23m**.

**Code:** `base_money_path` is quote-only (no chain). Full chains come from `_fetch_state` / logger / UI / terrain (`TERRAIN_REFRESH_SEC=60`). Morning full window starts `MORNING_START_MINS=570` (09:30 ET) but today first persist was 09:53.

**Chart yellow:** session `totalVolume` from the live terrain chain faucet (~60s cadence when refreshing). It only updates after a successful chain poll — not from quote-only base_money_path rows. Today durable chain/volume accrual started 23 min after the open.

**If late is unacceptable:** ensure a SPY full-chain `_fetch_state` (or terrain persist) lands in the first minute after 09:30 ET, not only `base_money_path` quotes — report only, not implemented.

## Structure levels

Failed Find & Prove structure-level hypotheses are not proof they are useless for every descriptive use; Decide stays WAIT; Chart storm is not edge.
