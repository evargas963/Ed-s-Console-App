# LP-01 Step 5 — touch study (lp01_touch_study_v1)

**VERDICT: FAIL**

> When price touches a structure level, is the forward move larger than the same clock minute produces anyway?

- tickers: `SPY, QQQ, IWM`
- sessions: 299
- touch events: 12471
- levels tested: PDH, PDL, PDC, PD_POC, PD_VAH, PD_VAL, ON_HIGH, ON_LOW, ORB_HIGH, ORB_LOW, ORB_MID
- excluded to avoid lookahead: TODAY_POC, TODAY_VAH, TODAY_VAL, VWAP, VWAP_P1, VWAP_M1, VWAP_P2, VWAP_M2

## Pre-registered PASS criteria

```
{
  "min_events_per_horizon": 200,
  "min_abs_cohens_d": 0.1,
  "bootstrap_ci_excludes_zero": true,
  "min_horizons_agreeing": 2,
  "must_hold_out_of_sample": true,
  "min_effect_over_placebo": 0.05
}
```

## Result by horizon

| horizon | n | mean abs fwd (touch) | time-of-day base | Cohen's d | PLACEBO d | d − placebo | bootstrap CI95 | pass |
|---|---|---|---|---|---|---|---|---|
| 5m | 12471 | 0.000959 | 0.000761 | 0.264 | 0.327 | -0.063 | [0.000180, 0.000216] | no |
| 15m | 12275 | 0.001575 | 0.001291 | 0.240 | 0.312 | -0.072 | [0.000256, 0.000311] | no |
| 30m | 12054 | 0.002140 | 0.001782 | 0.232 | 0.305 | -0.074 | [0.000321, 0.000397] | no |

### Placebo control

Touches select bars whose range CONTAINS the level, so they preferentially sample wide-range bars — and range is autocorrelated with forward volatility. Volatility clustering alone therefore produces a positive effect with no level information. The placebo arm displaces every level by a random 0.3–1.2% and runs the identical scan; whatever it reproduces is the METHOD, not the levels.

## Out-of-sample (split by session date)

- split at `2026-05-21`, consistent: **True**
  - first: 5m d=0.132 (n=5204), 15m d=0.089 (n=5114), 30m d=0.062 (n=5011)
  - second: 5m d=0.344 (n=7267), 15m d=0.329 (n=7161), 30m d=0.326 (n=7043)

## Disposition

- **FAIL** against the pre-registered criteria.
- Decision-path effect: NONE — structure-only regardless of verdict; this study does not admit anything to Decide.
- The levels remain **structure-only**: they are displayed as reference prices and are NOT admitted to the decision path. Decide stays WAIT.
- A failure here is not a defect. It is the search working: the levels are landmarks until something measures otherwise.
