# LEVEL-SET DIRECTIVE — reset the premise, fix the structure, run one real bet

**From:** Claude (for the operator) · **To:** Cursor · **Date (UTC):** 2026-07-17
**Status:** Find & Prove stays operator-PAUSE. This replaces "keep screening direction." No new direction-label study runs.

---

## 1. The honest diagnosis (root cause, not symptoms)

The app has been excellent at the *plumbing* and wrong at the *premise*. Six structural faults, in order of damage:

1. **Wrong objective.** It is built to predict tri-class **direction** of SPY/QQQ/IWM over 1–60 min. That is the single hardest, most efficient thing in markets to predict — closest to a coin flip after costs. There is **no economic reason** underneath it. World-class systems never start from "predict direction"; they start from "here is why someone over/underpays, and why it persists."
2. **Placeholder target.** `calibration/movement_target_thresholds_by_horizon_v1.json` — `selected_percentile: null`, `notes: "Placeholder thresholds … until percentile search runs."` Guessed constants, vol-unscaled, cost-unaware. **Every FP study was graded against a meaningless yardstick.** At short horizons the "move" band is *below* trading cost (SPY 1c ≈ 0.54bp).
3. **ATR miscast.** ATR is a **ruler** (a unit of "normal movement"), not a **signal**. It got promoted to a predictive feature/threshold. Nobody trades because of ATR; they measure *with* it. Demote it to invisible plumbing (target scaling, stops), remove it as a headline feature.
4. **Feature-family treadmill.** ~30 studies = the same question, same unit (one decision-log row), same screen, different features. That is *one* experiment in 30 costumes, not 30 experiments.
5. **Metric mismatch.** MCC-beats-persistence is a *statistics* test. Trading needs an *economics* test: expectancy net of costs. A balanced-but-meaningless label + a statistical metric = correctly-killed dust.
6. **No prior.** Searching a huge hypothesis space with no economic reason → multiplicity correction rightly kills everything. 0 PASS is the *expected* output of this setup, not a discovery about markets.

**Keep (genuinely good, do not touch):** Collect / Schwab-first pipeline, minute snapshots **+ the option chain you already store**, the refuse/gate/WAIT discipline, honest logging, the admission registry, the verification culture. This is the valuable part.

---

## 2. The pivot

**Stop predicting direction. Start trading a reason.**

Real edge lives in a handful of families with a mechanism: carry/risk-premium, trend, mean-reversion/stat-arb, liquidity provision (too fast for us), and **flow/events**. Our data (index option chain + minute microstructure) fits the **flow** family best. So the first real bet comes from there.

Reframe the app's job from **"which way?"** (coin flip) to **"what kind of day is this, and does a mechanical rule pay in that regime?"** (a real, easier, monitorable question — and the thing this app is actually shaped to do).

---

## 3. Stop-doing list (effective now)

- No new direction-classification studies on the placeholder label.
- No new model families until the target is fixed (§4) and the first card (§5) is run.
- No MCC-beats-baseline as an existence verdict. Retired.
- ATR removed from feature sets; retained only as a scaling unit.

---

## 4. Structural fixes (the foundation — must land before §5 model work)

**F1 — Real target.** Replace placeholder thresholds with a **cost-and-vol-scaled economic label** per ticker/horizon: a move "counts" only if it exceeds `max(k · ATR_horizon, round_trip_cost)`. Better, adopt **triple-barrier**: from the entry bar, up/down = which barrier (set at that scale) is hit first within the horizon; else flat. Recompute into `snapshots` + `calibration_decision_log`. Report per-ticker class balance and confirm no band sits below cost.

**F2 — Economic evaluator (single existence gate).** One module that scores any rule by **net expectancy under a conservative fill+cost model** (spread + fees + slippage), with block-bootstrap CI by day, Holm across the grid, and a 2×-cost + label-shuffle stress. This *is* the gate now. (Promote your FP-12/13 cost/stress work from follow-up to primary.)

**F3 — Leakage & integrity.** Close `FIND-LABEL-INTEGRITY-FORENSICS`; label-permutation test must give ≈0 skill; finish the ML-PIPE-V1 shuffled-label closeout. No model result counts until these are green.

---

## 5. FIRST REAL EXPERIMENT — card GEX-R1 (Dealer-Gamma Regime → reversion vs trend)

**Why this one:** it has a documented *mechanism*, it uses the **option chain you already collect**, and it asks "what kind of day" (regime) instead of "which way" (direction).

**Economic hypothesis:** When dealers are **net long gamma**, they hedge *against* moves (sell strength / buy weakness) → intraday moves are **damped → mean-reverting**. When **net short gamma**, they hedge *with* moves (buy strength / sell weakness) → moves are **amplified → trending**. So dealer-gamma sign/size near the open should separate **reversion days from trend days**, independent of direction.

**Signal (compute ~09:35 ET, per index SPY/QQQ/IWM):** a dealer gamma-exposure proxy
`GEX ≈ Σ_strikes gamma_i × open_interest_i × multiplier × spot`, with the standard dealer-sign convention (calls +, puts −), plus the **distance from spot to the zero-gamma / flip level**. Gamma from stored IV via Black-Scholes if not stored directly. Normalize (e.g., per 1% spot move). Output per day: `gex_sign`, `gex_magnitude`, `dist_to_flip`.

**Target (economic, NOT direction):** for each day, the **realized regime** = net expectancy (after costs, per F2) of a mechanical **VWAP/opening-range reversion** rule vs a **breakout/continuation** rule. Label the day by which paid.

**Test:** does `gex_sign`/magnitude at the open predict, **out-of-sample, walk-forward by day**, which rule pays — and does *conditioning* the rule on GEX beat running it unconditionally, net of costs?

**Model:** start **simple** — logistic regression / shallow gradient boosting on {gex_sign, gex_magnitude, dist_to_flip, open-gap, realized-vol regime}. No deep nets. The edge, if any, is in the hypothesis, not the model.

**Pass (GEX-R1 clears F2's gate):** GEX-conditioned rule shows **positive net expectancy, CI excludes 0 (block-bootstrap by day), beats the unconditional rule, survives 2× cost + day-shuffle.**

**Honest caveats — state these, don't bury them:**
- The **dealer-sign assumption is the crux.** If the GEX sign convention is wrong, the signal inverts. Validate the GEX build against a known reference month before trusting it.
- This is a **per-day** bet, so n = trading days = small. It accumulates slowly over a long calendar. That is acceptable — it is the *right kind* of question. Do not fake significance on thin n; the sample-size gate is hard.
- A pass is a *paper-trade* candidate, never a live trade. WAIT stays on the money path.

**If GEX-R1 fails its gate cleanly:** that is real information (not more dust), and we move to the next flow bet (opex/expiry pinning, or overnight-gap fade conditioned on vol regime) — a short, preregistered queue, not a 30-family zoo.

---

## 6. Division of labor

- **Cursor (build/measure under PAUSE→resume):** F1 label recompute; F2 economic evaluator + fill model; F3 integrity closeout; build the GEX proxy + the two mechanical rules; run GEX-R1 walk-forward; emit JSON proof.
- **Claude (design/verify/gatekeep):** co-spec F1/F2 and this card; **independently rebuild the GEX signal and re-check its sign** on a reference month; run the label-permutation check; adversarially verify any pass before it is called edge; block overclaim. I do not run studies or push.
- **Both:** nothing is "edge" until it clears F2 **and** my independent verify.

---

## 7. One sentence to hold onto

The months built the honest machine; they were pointed at the wrong target. We are not rebuilding the machine — we are re-aiming it at a question that has a reason behind it, and grading it in dollars after costs instead of statistics on a placeholder.

---

## 8. BUILD SPEC — GEX-R1 (enough detail to implement without guessing)

### 8.0 GO/NO-GO FIRST — answer before writing any model code
GEX needs the **entire option chain** (all strikes, near expiries) per day, not one selected contract. Cursor must first report:
- Does the DB store the **full chain historically** (all strikes/types/expiries, with OI + IV, per day)? → backtest is possible.
- Or only selected contracts (rec_strike etc.)? → GEX-R1 is **forward-only**: start snapshotting the full chain at ~09:35 ET daily and accept n accumulates over weeks.
- Does the stored chain already carry a **gamma** greek and **open_interest**? If yes, use them directly and skip the Black-Scholes recompute in 8.2. Report which fields exist (`gamma`, `open_interest`, `implied_volatility`, `days_to_expiration`, `strike`, `put_call`, underlying `spot`).

Do not proceed to 8.2+ until this is answered in a short data-availability note.

### 8.1 Signal snapshot
Once per session at **09:35 ET**, per underlying **SPY, QQQ, IWM**, capture the full chain: for each option `i` → {type∈(C,P), strike Kᵢ, open_interest OIᵢ, iv σᵢ, time_to_expiry Tᵢ (years), spot S}. Include expiries out to the next monthly (`T ≤ ~0.10y`); short-dated dominate gamma. Risk-free `r ≈ current 3m rate` (0.05 fine; low sensitivity), dividend `q` optional (ETF yield or 0).

### 8.2 Gamma (skip if a stored gamma greek exists — prefer stored)
Black-Scholes per-share gamma (same for calls and puts):
```
d1  = ( ln(S/Kᵢ) + (r − q + σᵢ²/2)·Tᵢ ) / ( σᵢ·√Tᵢ )
Γᵢ  = N'(d1) / ( S·σᵢ·√Tᵢ )          # N' = standard normal pdf
```
Guard: drop rows with `Tᵢ≤0`, `σᵢ≤0`, `OIᵢ` null.

### 8.3 Dealer gamma exposure (GEX) — with the sign assumption flagged
Dollar gamma per option = $-delta change per **1% move** in S:
```
gexᵢ = Γᵢ · OIᵢ · 100 · S² · 0.01
```
Baseline dealer-sign convention (SqueezeMetrics-style: dealers long calls / short puts vs customers):
```
GEX_total = Σ_calls gexᵢ  −  Σ_puts gexᵢ
gex_sign  = sign(GEX_total)      # +1 = long-gamma/expect reversion, −1 = short-gamma/expect trend
```
**This +call/−put sign is an ASSUMPTION and the single biggest failure risk — validate it in 8.7 before trusting any result.**

**Zero-gamma (flip) level:** recompute `GEX_total(S')` over a grid `S' ∈ [0.90S, 1.10S]` (0.1% steps), holding OIᵢ, σᵢ fixed and recomputing d1/Γ at each S'. `gamma_flip_price` = the zero-crossing nearest spot. `dist_to_flip = (S − gamma_flip_price)/S`.

**Normalize** (comparability across ticker/time): `gex_z` = robust z-score of `GEX_total` vs its trailing-20-session median/IQR, per ticker. Primary feature is `gex_sign`; `gex_z` and `dist_to_flip` secondary.

Per (day, index) signal row: `{gex_sign, gex_z, dist_to_flip}` + controls `{overnight_gap_in_ATR, prior_day_realized_vol_tercile}`.

### 8.4 The ruler
`σ_unit` = ATR(14) of the index in points (daily ATR). **This is ATR's only legitimate job here — a scaling unit, never a feature.** All rule distances/targets/stops are in multiples of `σ_intraday` (use a 1-minute-derived intraday sigma, or `σ_unit/√(bars_per_day)` as a simple proxy).

### 8.5 The two mechanical rules (they only *measure* the regime, in dollars)
RTH 09:30–16:00 ET, 1-min bars, one unit per entry, ≤ N entries/day, flat at close. Both use the **same F2 cost model** (spread + fees + slippage, conservative — e.g. ≥1 tick/side).

- **Rule A — Reversion (fade):** ref = session VWAP. On extension to `ref ± m·σ` (m=1.0), enter *against* it, target ref, stop `ref ± (m+1)·σ`. → `reversion_pnl_day` (net).
- **Rule B — Breakout (trend):** OR = high/low of first 30 min. On break beyond OR ± buffer, enter *with* it, target `+m·σ`, stop back inside OR. → `breakout_pnl_day` (net).

`m`, `N`, buffer are fixed constants declared in the card **before** running (no tuning to fit).

### 8.6 Target, model, evaluation
- **Economic target (no threshold guessing):** `regime_score_day = reversion_pnl_day − breakout_pnl_day` (net, in σ-units). Positive ⇒ fade paid; negative ⇒ trend paid.
- **Model (simple):** logistic `P(regime_score>0)` or a shallow GBM regressor on the 8.3 features. Walk-forward **by day** with an embargo; no leakage of same-day outcome.
- **Evaluation is economic, not accuracy:** build the *conditioned strategy* = each test day run whichever rule the model predicts will pay; compare **net daily expectancy** to (i) always-reversion, (ii) always-breakout, (iii) random-choice.
- **PASS (F2 gate):** conditioned strategy net expectancy > 0, **block-bootstrap CI over days excludes 0**, **beats the best unconditional rule**, and **survives 2×-cost + GEX→day-shuffle** (shuffling the signal-to-day map must kill the edge).

### 8.7 Sanity gates — run these BEFORE the model
1. **Sign validation:** unconditionally, do **positive-GEX days show smaller realized intraday range / more mean-reversion** than negative-GEX days? If the relationship is backwards, the 8.3 sign is inverted — fix it. (Cheap, decisive.)
2. **Sample floor:** ≥ ~60 test days per index across ≥2 vol regimes before any verdict. If history is thin (forward-only), say so and wait — do not manufacture n by pooling tickers that disagree.
3. **Shuffle null:** GEX→day-shuffle must reduce the conditioned edge to ≈0.

### 8.8 Deliverables (full-chain forward version)
`reports/gex_r1_signal_build_note.md` (8.0 data answer + sign-validation result), `reports/gex_r1_eval_latest.json` (per-index + pooled economic results with CIs), and the reusable evaluator from F2. No result is "edge" until it clears 8.6 **and** Claude's independent signal rebuild + verify.

---

## 9. GEX-R1-SCREEN — history screen on the stored 0DTE slice (run this FIRST; run forward collection in parallel)

**Why this exists:** §8.0 says full-chain history is absent, so §8.1–8.3 is forward-only. But the DB *does* hold a **consistent 0DTE front-expiry slice** (~40 ATM contracts with stored `gamma`, `openInterest`, `putCall`) for **~70 morning-days per index (SPY 72 / QQQ 69 / IWM 69, 2026-03-25→07-17)**. 0DTE is where intraday hedging pressure concentrates, so this is a legitimate **screen** of the regime hypothesis on history — no forward wait.

**Status label:** SCREEN, not verdict. A pass → justifies paying for the forward full-chain GEX-R1. A null → the mechanism is not obviously alive on 0DTE over this window; deprioritize before spending weeks collecting. Neither is edge.

**Do BOTH, starting now, in parallel:**
- **(a)** Run GEX-R1-SCREEN on the ~70-day history (below).
- **(b)** Turn on **forward full-chain capture** at ~09:35 ET (persist all strikes/near expiries, not just `selected_exp`) so clean data accrues from today regardless of the screen result. Non-blocking, cheap, no model work.

**Signal (per index, morning snapshot 09:30–10:15 ET, one row/day — the first with chain JSON):**
```
gex_0dte = Σ_calls (gammaᵢ · OIᵢ · 100 · S² · 0.01)  −  Σ_puts (gammaᵢ · OIᵢ · 100 · S² · 0.01)
```
Use the **stored per-contract `gamma`** (do NOT Black-Scholes recompute — 0DTE T→0 explodes the formula). Sign convention +call/−put (SqueezeMetrics-style) — **an assumption; sign-validate first (§8.7 gate 1)**. Outputs: `gex_sign`, `gex_z` (robust z vs trailing-20-session per ticker), and use snapshot `net_gamma` only as an independent **cross-check** of sign (agreement rate), never as the signal itself.

**Rules, target, model, evaluation, gates:** exactly §8.4–8.7 (VWAP-reversion vs OR-breakout, `regime_score_day` in dollars after costs, walk-forward by day, block-bootstrap CI, 2×-cost + shuffle, hard sample floor). ATR stays a ruler only.

**Honest limits to state in the report:** n≈70/ticker over ~4 months = one narrow vol regime; 40 contracts = an ATM window (far walls truncated); 0DTE morning read is noisier than a stable monthly GEX. A thin-n positive is "pursue," not "proven"; report per-index before any pooling (same-day cross-ticker rows are correlated — do not treat 3×70 as 210 independent).

**Deliverables:** `reports/gex_r1_screen_signbuild_note.md` (sign-validation result + net_gamma agreement rate), `reports/gex_r1_screen_eval_latest.json` (per-index + pooled economics with CIs), plus the reusable F2 evaluator. No result is "edge" until §8.6 clears **and** Claude independently rebuilds the 0DTE GEX + verifies sign.

**Division of labor unchanged (§6):** Cursor builds/runs (a) and stands up (b); Claude independently rebuilds `gex_0dte`, checks the sign against realized reversion, runs the shuffle null, and gatekeeps overclaim.

### 9.1 Timestamp-plumbing note (forensic 2026-07-17, read-only)

Clock forensic result: **host clock + timezone are CORRECT** (UTC/CT synced; ET conversion places RTH activity in 09:30–16:00 ET; stored `ts_et` matches `ts_utc`→ET at minute level). **`price_bars_1m` is 100% minute-aligned, 60s bars, all three tickers.** The only dislocation is that **snapshot write-timestamps are stamped at arbitrary poll-seconds**, not bar edges (uniform second-of-minute) — the same seconds-jitter behind the 29s join tol / FP-18/24 residual. It does NOT affect the price series or RTH filtering.

**Mandatory for GEX-R1 to avoid the jitter:**
- Run the reversion/breakout rules on **`price_bars_1m`** (clean, minute-aligned) — NOT on snapshot ts.
- Take the morning gamma read from the snapshot (seconds don't matter for a daily regime signal).
- Join gamma↔rules by **ET trading-day**, never by exact timestamp.
- VWAP/opening-range/ATR all computed from `price_bars_1m`.

**Durable Collect fix (separate track, NOT blocking GEX-R1):** stamp each snapshot/decision with the `bar_start_ts_utc` of the minute it was computed in, so snapshot↔bar↔outcome joins are exact by construction instead of tolerance-based. This retires the 29s-tol jitter class at the source; schedule it as a Collect-hardening item, do not fold it into the GEX bet.
