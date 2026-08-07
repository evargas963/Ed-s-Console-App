# liquidity_oi_volume_stickiness_v1

**MISSION_CLASS:** Find & Prove — offline stickiness bake-off
**DECISION_PATH_EFFECT:** WAIT — no Decide admission; no Chart change
**COSTS:** ABSENT
**OVERALL VERDICT:** `FAIL`
**NOTE:** No OI×vol combined arm beat placebo on pre-registered stickiness gates; baselines also FAIL

Reproduce:
```
python tools/liquidity_oi_volume_stickiness_v1.py
```

## AGENTS.md admission

| Field | Answer |
|---|---|
| MISSION_CLASS | Find & Prove — research + offline backtest |
| GAP | Chart yellow = volume only; OI×vol stickiness untested; prior packs scored bare touch |
| SMALLEST_COMPLETE_CHANGE | This tool + reports/*.md/*.json |
| MINIMUM_SUFFICIENT_EVIDENCE | Same-turn harness vs placebo + vol/OI/GEX arms; exact n |
| DECISION_PATH_EFFECT | None — WAIT |
| WHY_NOW | Operator ask: yellow-bar idea with BOTH OI and volume; PhD stickiness defs |
| TASK_ADMISSION | Admitted as Find & Prove research only |

## 1) Research findings (written before coding)

### 1.1 What prior Ed packs already proved (and missed)

- Chart yellow bars = **session options volume by strike**, not OI (`reports/liquidity_experiment_input_audit_v1.md`).
- Gamma experiments tested **GEX$ walls/pin** (gamma×OI), not volume magnets and not pure OI walls — and **FAIL**ed placebos on touch/hold/bounce.
- Price-action literacy (`reports/price_action_liquidity_literacy_v1.md`): FAIL on bare touch does **not** kill levels — it kills **location-only** events. Sticky behavior needs time-in-band, failed breaks, pin-to-close, rejection — not tags.

### 1.2 Microstructure: what makes a strike sticky?

- **Avellaneda & Lipkin (QF 2003):** pinning near expiry from delta-hedging when open interest is unusually large; mechanism is OI-scaled hedge impact, not bare volume. Transfer to SPY/QQQ/IWM 0DTE era = `[UNVERIFIED]` until measured.
- **Dealer gamma pinning (desk/academic hedging lit, Baltussen et al. JFE 2021):** long-gamma hedging mean-reverts; short-gamma accelerates. Pin strength ↑ as DTE→0 (gamma explosion). Regime split still thin on Ed morning_full.
- **OI vs volume:** OI = standing inventory (overnight-stable within session); volume = today's traded interest (accrues). Desk lore of “high OI + high volume” as a magnet is a **confluence hypothesis**, not proven edge. Turnover (volume/OI) among high-OI strikes can mark **active repositioning** vs stale inventory — also `[UNVERIFIED]` as stickiness until this harness.
- **GEX$ vs volume peaks:** GEX weights OI by gamma (near-ATM/near-expiry heavy); volume peaks can sit at different strikes than OI or GEX peaks (audit census).

### 1.3 Operational STICKY (not touch)

A strike is sticky for a session if, **after levels are known (10:15 ET)**:

1. **Time-in-band (primary A):** large fraction of remaining RTH minutes have `|close − K| ≤ 0.25 × causalATR` (ATR from pre-10:15 bars only).
2. **Failed-break rate (primary B):** among pierces beyond K by `0.35×ATR`, fraction that reclaim to the strike side within 15 minutes.
3. **Pin-to-close (secondary C):** smaller `|RTH close − K|` than placebo; near-expiry (DTE≤1 present in band) reported separately.
4. **PA rejection (descriptive):** approach into band + rejection wick ≥0.5×ATR with close back on approach side — VISIBLE OHLC proxy, not book absorption.

Mere geometric overlap of a bar range with K is **not** scored as sticky.

### 1.4 Candidate combined scores (as-of causal)

| Arm | Score | As-of |
|---|---|---|
| VOL_PEAK | top-3 volume in ±3% moneyness | obs chain volume |
| OI_PEAK | top-3 OI | obs chain OI |
| PRODUCT | top-3 OI×volume | both from obs |
| Z_PRODUCT | top-3 z(OI)×z(vol) in band | both from obs |
| TURNOVER_HIGH_OI | top-3 volume/OI among top-quartile OI | both from obs |
| GEX_WALLS | call/put wall + pin | gamma×OI via compute_terrain |

Placebos (fair-method): (1) **moneyness-matched** same `|K−S|/S` mirror; (2) **score-shuffle** of OI/vol then re-pick top-K. Uniform ±3% draws rejected (they manufacture ATM stickiness).

## 2) Sample (exact)

- Tickers: `['SPY', 'QQQ', 'IWM']`
- Observation days loaded: **202**
- Day records with bars: **198**
- morning_full exact: `{"SPY": {"raw": 12, "trading_days": 9}, "QQQ": {"raw": 11, "trading_days": 9}, "IWM": {"raw": 12, "trading_days": 9}}`
- Faucet mix: `{"snapshots_1000et": 171, "morning_full": 27}`
- Sessions by arm: `{"VOL_PEAK": 198, "OI_PEAK": 198, "PRODUCT": 198, "Z_PRODUCT": 198, "TURNOVER_HIGH_OI": 198, "GEX_WALLS": 195}`
- Drops: `{"empty_GEX_WALLS": 3, "short_session": 1, "atr_zero": 3}`
- Elapsed: 67.51s

## 3) Results by arm

| Arm | n | TIB real | TIB m-plc | TIB shuf | TIB edge | FB real | FB m-plc | FB shuf | FB edge | pin vs m-plc | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| VOL_PEAK | 198 | 2.7% | 2.3% | 1.0% | 0.4% | 54.0% | 51.7% | 35.8% | 2.3% | -1.6% | `FAIL` |
| OI_PEAK | 198 | 1.2% | 1.4% | 1.2% | -0.1% | 39.6% | 40.2% | 36.4% | -0.6% | -5.2% | `FAIL` |
| PRODUCT | 198 | 2.1% | 2.0% | 1.0% | 0.1% | 49.7% | 49.1% | 35.4% | 0.6% | -3.1% | `FAIL` |
| Z_PRODUCT | 198 | 1.3% | 1.3% | 1.0% | 0.0% | 40.5% | 41.4% | 34.4% | -0.9% | 3.2% | `FAIL` |
| TURNOVER_HIGH_OI | 198 | 1.7% | 1.9% | 1.1% | -0.1% | 47.1% | 46.5% | 35.7% | 0.6% | -1.8% | `FAIL` |
| GEX_WALLS | 195 | 2.2% | 1.9% | 1.1% | 0.3% | 48.6% | 47.8% | 36.2% | 0.9% | 1.2% | `FAIL` |

### Half-sample agreement (time-in-band)

- **VOL_PEAK:** evaluated=True agree=True n_agree=2 halves=`{"first": {"mean_edge": 0.005016347045332552, "n": 99}, "second": {"mean_edge": 0.002370969127226686, "n": 99}}`
- **OI_PEAK:** evaluated=True agree=False n_agree=0 halves=`{"first": {"mean_edge": -0.0023325037817791437, "n": 99}, "second": {"mean_edge": -0.0002964283261737259, "n": 99}}`
- **PRODUCT:** evaluated=True agree=False n_agree=1 halves=`{"first": {"mean_edge": 0.0021275557507441567, "n": 99}, "second": {"mean_edge": -0.0005428893039779315, "n": 99}}`
- **Z_PRODUCT:** evaluated=True agree=False n_agree=1 halves=`{"first": {"mean_edge": -0.0010052212950763674, "n": 99}, "second": {"mean_edge": 0.001929113279355351, "n": 99}}`
- **TURNOVER_HIGH_OI:** evaluated=True agree=False n_agree=0 halves=`{"first": {"mean_edge": -0.0018445322793148877, "n": 99}, "second": {"mean_edge": -0.0005021774560507607, "n": 99}}`
- **GEX_WALLS:** evaluated=True agree=True n_agree=2 halves=`{"first": {"mean_edge": 0.003357243936954082, "n": 99}, "second": {"mean_edge": 0.001787380857577477, "n": 96}}`

### Near-expiry pin subset (DTE≤1 present in band)

| Arm | n near sess | pin dist real | pin dist plc | improvement |
|---|---:|---:|---:|---:|
| VOL_PEAK | 195 | 3.781 | 3.712 | -1.8% |
| OI_PEAK | 195 | 5.874 | 5.579 | -5.3% |
| PRODUCT | 195 | 4.307 | 4.175 | -3.2% |
| Z_PRODUCT | 195 | 5.792 | 5.988 | 3.3% |
| TURNOVER_HIGH_OI | 195 | 4.594 | 4.517 | -1.7% |
| GEX_WALLS | 195 | 4.543 | 4.596 | 1.2% |

## 4) Ranking under fair (moneyness-matched) placebo — all FAIL gates

- Time-in-band edge rank: VOL_PEAK > GEX_WALLS > PRODUCT > Z_PRODUCT > TURNOVER_HIGH_OI > OI_PEAK
- Failed-break edge rank: VOL_PEAK > GEX_WALLS > PRODUCT > TURNOVER_HIGH_OI > OI_PEAK > Z_PRODUCT

Head-to-head (does combined beat baseline on raw edge sign?):
```
{
  "PRODUCT": {
    "VOL_PEAK": {
      "tib": false,
      "fb": false,
      "combined_pass": false,
      "baseline_pass": false
    },
    "OI_PEAK": {
      "tib": true,
      "fb": true,
      "combined_pass": false,
      "baseline_pass": false
    },
    "GEX_WALLS": {
      "tib": false,
      "fb": false,
      "combined_pass": false,
      "baseline_pass": false
    }
  },
  "Z_PRODUCT": {
    "VOL_PEAK": {
      "tib": false,
      "fb": false,
      "combined_pass": false,
      "baseline_pass": false
    },
    "OI_PEAK": {
      "tib": true,
      "fb": false,
      "combined_pass": false,
      "baseline_pass": false
    },
    "GEX_WALLS": {
      "tib": false,
      "fb": false,
      "combined_pass": false,
      "baseline_pass": false
    }
  },
  "TURNOVER_HIGH_OI": {
    "VOL_PEAK": {
      "tib": false,
      "fb": false,
      "combined_pass": false,
      "baseline_pass": false
    },
    "OI_PEAK": {
      "tib": true,
      "fb": true,
      "combined_pass": false,
      "baseline_pass": false
    },
    "GEX_WALLS": {
      "tib": false,
      "fb": false,
      "combined_pass": false,
      "baseline_pass": false
    }
  }
}
```

### Score-shuffle hard null (secondary)

Beating score-shuffle alone is NOT enough for PASS — volume/OI naturally concentrate nearer the session path, so shuffled labels often crown far strikes. Primary authority is moneyness-matched.

- **VOL_PEAK:** tib_vs_shuf=1.7%, fb_vs_shuf=18.2%, pin_vs_shuf=40.4%
- **OI_PEAK:** tib_vs_shuf=0.1%, fb_vs_shuf=3.2%, pin_vs_shuf=6.4%
- **PRODUCT:** tib_vs_shuf=1.0%, fb_vs_shuf=14.3%, pin_vs_shuf=31.7%
- **Z_PRODUCT:** tib_vs_shuf=0.3%, fb_vs_shuf=6.2%, pin_vs_shuf=5.7%
- **TURNOVER_HIGH_OI:** tib_vs_shuf=0.7%, fb_vs_shuf=11.4%, pin_vs_shuf=28.5%
- **GEX_WALLS:** tib_vs_shuf=1.1%, fb_vs_shuf=12.4%, pin_vs_shuf=29.1%

## 5) Plain-English disposition

**Verdict: FAIL.** No OI×vol combined arm beat placebo on pre-registered stickiness gates; baselines also FAIL

- Sticky ≠ touch: magnet behavior (time near strike, failed breaks, close pin, PA rejection).
- **OI×vol did NOT beat volume-only.** PRODUCT / Z_PRODUCT / TURNOVER_HIGH_OI lose to VOL_PEAK on both primary edges under moneyness-matched placebo.
- **OI-only is the weakest** of the mass arms (often negative vs matched placebo).
- **GEX$ walls** also FAIL the stickiness gates here (consistent with prior touch/hold FAILs, now under non-touch outcomes).
- An early uniform ±3% placebo looked like a PASS — that was ATM-proximity bias; rejected. Fair matched placebos collapse edges to noise.
- Volume as-of is morning/~10:00 cumulative only — Chart-yellow analogue without EOD lookahead.
- Decide: **WAIT**. Chart yellow bars unchanged.

## 6) Limits

- Snapshot chains dominate the faucet mix (narrow money-path common) — same Collect skew as gamma packs.
- morning_full exact trading days: SPY/QQQ/IWM = 9/9/9 (ops target 20 unmet).
- Pierce counts are healthy (~1k–1.8k) — B is not underpowered; it simply lacks edge vs matched placebo.
- Costs ABSENT; no economic edge claim.
- PA rejection is an OHLC proxy, not book absorption; edges near zero / negative.
- Near-expiry pin subset large (most ETF days have 0–1 DTE options) but pin improvement fails.
- Score-shuffle can still favor near-path mass; do not promote shuffle-only wins.

