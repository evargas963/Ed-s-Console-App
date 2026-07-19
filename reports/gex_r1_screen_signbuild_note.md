# GEX-R1-SCREEN sign-build note

**Generated:** 2026-07-17T22:07:06Z
**Label:** SCREEN, not verdict. Not edge.

## Sign validation (§8.7 gate 1)

### SPY
- morning days: 72 (2026-03-25 → 2026-07-17)
- +GEX n=52 mean regime_score=0.44118522681406286
- −GEX n=20 mean regime_score=0.5652748858899057
- orientation: **inverted_or_null**
- net_gamma sign agreement: 0.9444444444444444
- screen_pulse: **NULL_OR_WEAK** (sample_floor_met=True)

### QQQ
- morning days: 67 (2026-03-25 → 2026-07-17)
- +GEX n=45 mean regime_score=0.5604979289592317
- −GEX n=22 mean regime_score=0.4799827744795638
- orientation: **as_assumed**
- net_gamma sign agreement: 0.9552238805970149
- screen_pulse: **NULL_OR_WEAK** (sample_floor_met=True)

### IWM
- morning days: 68 (2026-03-25 → 2026-07-17)
- +GEX n=36 mean regime_score=0.30477316364865775
- −GEX n=32 mean regime_score=0.2915912324575591
- orientation: **as_assumed**
- net_gamma sign agreement: 0.9411764705882353
- screen_pulse: **NULL_OR_WEAK** (sample_floor_met=True)

## Economic walk-forward (dollars after 1bp RT cost)

See `reports/gex_r1_screen_eval_latest.json` → `per_index.*.walk_forward`.

## Limits

- n~70/ticker over ~4 months = one narrow vol regime
- ATM 0DTE window only (~40 contracts)
- do not pool tickers as independent n
- not edge until Claude independent rebuild + verify
- Nothing here is edge until Claude independently rebuilds gex_0dte, verifies sign, and clears shuffle null.
- Pass/fail is money after costs (§8.6), not classification accuracy.
