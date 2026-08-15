# ED Trading System — Consolidated Master Design Corpus
**Consolidated:** 2026-07-20 (operator directive: consolidate design documents, delete originals, review against current state)
**Source:** loose files formerly in `C:/Users/evarg/Documents/Trading/` — every document below is preserved VERBATIM; the originals are deleted.
**Repo-internal design lineage this corpus feeds:** `AGENTS.md` (charter, active) -> `governance/archive/2026-Q2/governance_md/INSTITUTIONAL_STANDARD_V2.md` -> `INSTITUTIONAL_STANDARD_V3.md` (recover: `git show 077754d^:governance/INSTITUTIONAL_STANDARD_V3.md`) -> `governance/Framework-ED-Decision-Engine-v1.1.md` (live) -> v2.0 blueprint (recover: `git show 0148e0d^:governance/IMPLEMENTATION_BLUEPRINT_V2.md`) -> `v2_decision/` code.
**Not consolidated, deleted as directed:** `riskstoc.pdf` (binary reference PDF), `~$ading Plan by Cursor Final.docx` (Word lock file).
**Explicitly untouched:** `ed_console_backup_20260716_9b124b3.db` (+ -shm/-wal) — the newest DB backup.

## Corpus map
| # | document | date | role |
|---|---|---|---|
| 1 | ROADMAP.md | 2026-03-03 | Earliest roadmap — the app's first written direction |
| 2 | institutional_trading_engine.md | 2026-03-30 | First 'institutional engine' articulation |
| 3 | pytorch_tensorflow_vs_my_stack.md | 2026-03-30 | THE STACK — framework comparison and the case for the chosen model stack |
| 4 | Ed_Trading_System_Issues_ChatGPT_MASTER.md | 2026-04-01 | Early issue master (ChatGPT era) |
| 5 | Ed_Trading_System_MASTER_v8_AUTHORITATIVE.md | 2026-04-01 | MASTER SPEC v8 — Predictive Trading Engine, authoritative |
| 6 | Ed_Trading_System_MASTER_v9_UPDATED.md | 2026-04-02 | MASTER SPEC v9 |
| 7 | Ed_Trading_System_MASTER_v11_AUTHORITATIVE.md | 2026-04-02 | MASTER SPEC v11 — authoritative master (baseline preserved inside) |
| 8 | Ed_Trading_System_MASTER_v12_additive_extension.md | 2026-04-02 | MASTER SPEC v12 — additive extension: full pipeline mapping, XGB/LSTM/Transformer stack interaction, similarity tiers |
| 9 | edwebconsole_future_state_architecture_spec_v1.md | 2026-04-09 | APP ARCHITECTURE — multi-plane future-state spec (planes, tiers, materiality engine, L1 contract) — the architecture actually built |
| 10 | ED INSTITUTIONAL DECISION ENGINE.docx | 2026-05-03 | Decision Engine research/build framework (became repo v1.1/V3) |
| 11 | IDEAL TRADING DECISION ENGINE.docx | 2026-05-04 | Ideal decision engine design |
| 12 | IDEAL TRADING DECISION ENGINE_V1.docx | 2026-05-04 | Maximum-edge unconstrained design variant |
| 13 | Trading Plan by Cursor Final.docx | 2026-05-04 | Trading plan (Cursor final) |
| 14 | ED_CONSOLE_MASTER_OPERATING_CONTRACT_AND_HANDOFF.md | 2026-07-11 | Master operating contract + handoff |
| 15 | daily_operations.md | 2026-04-03 | APPENDIX: daily operations checklist (operational, preserved for completeness) |
| 16 | three_account_plan.jsx | 2026-03-04 | APPENDIX: three-account capital plan (verbatim JSX artifact) |


====================================================================================================
# SOURCE DOCUMENT: ROADMAP.md
**Date:** 2026-03-03 | **Role:** Earliest roadmap — the app's first written direction | **Original size:** 18,545 bytes
====================================================================================================

# ED CONSOLE — PROJECT ROADMAP
**Last updated:** 2026-03-03 (Session 15)
**Paste this at the start of any new Claude session.**

---

## PROJECT OVERVIEW

Ed Console is a 0DTE options trading console built on FastAPI + vanilla JS.
It ingests live Schwab options chain data, computes Greek exposures (GEX/DEX),
charm flows, micro price-action structure, and produces three signal cards:
**Right Now** (rules-based), **The Call** (combined trade signal), and
**What the Data Says** (statistical prediction from historical snapshots).

**Tech stack:** Python 3.10+, FastAPI, SQLite, vanilla HTML/JS frontend.
**Active codebase:** 12 files + index.html frontend.
**Database:** ~8,700+ snapshots with 50+ columns each, outcomes labeled.

---

## ACTIVE FILES

| File | Purpose |
|---|---|
| server.py | FastAPI endpoints, polling loop, snapshot logging, accuracy tracking, IV tracker, debug endpoint, market context cache, ticker persistence |
| signals.py | Three signal cards, prediction engine, The Call with prediction-based targets |
| math_exposure.py | GEX/DEX aggregation, charm, vanna, walls, pins, zone helpers, parity |
| market_state.py | MarketState builder, zone classification, option recommendation |
| micro_structure.py | Candle pattern analysis, swing detection, BOS/CHoCH, regime detection |
| db.py | SQLite DB, schema, similar-setups query (uncapped), outcomes |
| chains.py | Options chain parsing/normalization |
| schwab_client.py | Schwab API auth + data fetching |
| market_context.py | Cross-instrument data (QQQ, IWM, VIX) |
| levels.py | Price level display helpers (used by server.py) |
| config.py | App config, API credentials, paths |
| index.html | Frontend — vanilla HTML/JS, renders all cards |
| ml_train.py | ML training pipeline — feature engineering, walk-forward CV, model saving |
| ml_predict.py | ML inference — loads model, provides predictions to signals.py |

**Deleted:** institutional_model.py (parity moved to math_exposure.py, rest was dead code)

**Archived (in archive/ folder):** ed_console_app.py, ui_gamma_delta.py,
ui_options_scanner.py, ui_placeholders.py, gameplan.py, barchart_ingest.py,
dump_chain_payload.py, market_scanner.py, migrate_horizons.py, migrate_zones.py,
migrate_9c_to_8c.py, relabel_outcomes.py

---

## COMPLETED WORK

### Session 1 (2026-02-25): Initial Audit
- Reviewed full codebase architecture
- Confirmed charm formula, card reactivity, prediction logic

### Session 2 (2026-02-26 AM): Three-Card Rebuild
- Identified 8 critical bugs in signal cards
- Built micro_structure.py engine (candle pattern analysis)
- Redesigned all three cards with trade type classification
- Implemented dual targets, confluence scoring

### Session 3 (2026-02-26 PM): Prediction Card Fix
- Diagnosed all-or-nothing matching → everything falling to Tier 5
- Implemented progressive relaxation (5-tier matching system)
- Updated confidence scoring to be tier-aware

### Session 4 (2026-02-26 PM): vwap_side NULL Fix
- Diagnosed vwap_side never being written to snapshots
- Fixed db.py and signals.py to populate vwap_side
- System now matching at Tier 1 instead of Tier 4

### Session 5 (2026-02-27): Codebase Audit + Housekeeping
- Built audit.py diagnostic tool
- Archived 8 Streamlit/dead files (saved ~6,100 lines)
- Cleaned 35 unused imports across 11 files
- Zero dead functions, zero orphan files, zero unused imports

### Session 6 (2026-02-27): Math Audit
- Produced three audit reports (math_audit.md, math_quality_assessment.md, architectural_math_audit.md)
- Identified 10 architectural issues and graded all formulas A through D

### Session 7 (2026-02-27): Math Centralization + Horizons
- ✅ Centralized all math to math_exposure.py (15 named constants)
- ✅ Direction classification → percentage-based (0.05% of spot, not fixed 0.10 pts)
- ✅ Pin strength → dollar-gamma (GEX) instead of raw gamma
- ✅ `_dominant()` name collision → `dominant_direction()`
- ✅ Magic numbers → named constants (DIRECTION_THRESHOLD_PCT, DIST_BUCKET_*, etc.)
- ✅ Horizons → 3c/5c/8c/13c (1c dropped, 8c/13c added)
- ✅ Migration: 6,006 historical labels relabeled with new threshold
- ✅ Accuracy tracking wired into server (10-min cycles, /api/accuracy endpoint)

### Session 8 (2026-02-27): Scoring Merge + Zones + Dead Channels + Frontend
- ✅ Option scoring merge — single scoring system
- ✅ Zone expansion — 6 zones (pin_bull/bear/neutral/chaos, breakout, breakdown)
- ✅ Dead data channels activated (prev_zone, zone_since_bars)
- ✅ 500 sample cap removed
- ✅ Horizons 9c → 8c (pure Fibonacci: 3, 5, 8, 13)
- ✅ Frontend updated for 4 horizon bars

### Session 9 (2026-03-02): Charm Null + Candle Fix
- ✅ Diagnosed charm returning nulls — missing parameters in build_market_state call
- ✅ Built candle accumulator (_CandleAccumulator) converting spot ticks to OHLC bars
- ✅ Fixed dataclass field ordering errors
- ✅ Verified charm formula methodology

### Session 10 (2026-03-02): Comprehensive Math Audit
- ✅ Audited all 11 formulas across math_exposure.py and signals.py
- ✅ Identified critical gaps: proximity weighting, magnitude gates, percentage-based stops
- ✅ Complete charm rewrite with 5 design principles

### Session 11 (2026-03-02): Charm Debug + Wiring
- ✅ Traced charm data flow through server → market_state → signals
- ✅ Fixed missing charm parameters in build_market_state call
- ✅ Added synthetic forward interpretation to frontend

### Session 12 (2026-03-03): Formula Audit Implementation (12 fixes)
- ✅ **CRITICAL: Magnitude gate bug** — was applied to gamma regime, causing zone
  misclassification. Fixed to apply only to delta direction. Gamma sign drives regime.
- ✅ Proximity weighting on CONSENSUS aggregation (ATM strikes dominate)
- ✅ GEX/DEX magnitude classification (large/moderate/small/negligible)
- ✅ Greek bias scaled by magnitude (negligible magnitude = no bias shift)
- ✅ Gamma pin constrained to ±5% of spot
- ✅ Percentage-based stop distances (0.18% of spot, not fixed 1.25 pts)
- ✅ Parity function centralized from institutional_model.py to math_exposure.py
- ✅ charm_magnitude column added to DB with auto-migration

### Session 13 (2026-03-03): Prediction Sample Count Debug
- ✅ Diagnosed sample count drop (4,429 → 199) — NOT a bug
- ✅ Zone changed from breakdown (5,560 samples) to breakout (207 samples)
- ✅ Added `/api/debug/prediction` endpoint showing zone, bias, magnitudes, DB distribution
- ✅ Created card_mockup.html showing current vs goal state for prediction card

### Session 14 (2026-03-03): Final Audit Pass + Target Fix
- ✅ **Wall detection minimum strength** — walls must exceed 1.5× median to qualify.
  Prevents $100 of gamma from being labeled "the wall" in a flat landscape.
- ✅ **Pin strength time multiplier removed** — live Greeks from API already reflect
  shrinking DTE. Adding a time boost double-counts the gamma magnification.
- ✅ **IV direction tracker** — stores last 6 ATM IV readings, derives
  expanding/contracting/flat. Fed into vanna wall context.
- ✅ **Vanna wall descriptions dynamic** — frontend shows "IV EXPANDING — vanna active"
  vs "IV flat — vanna dormant" based on live IV direction.
- ✅ **micro_structure.py audit:**
  - All fixed-point thresholds → percentage of spot (engulfing, hammer, flag, etc.)
  - BOS/CHoCH now highest priority over chop (breakout from noise = most actionable)
  - Flag detection scans backwards (finds most recent flag, not oldest)
  - detect_candle_patterns takes spot parameter for scaling
- ✅ **THE CALL TARGET FIX (major):** Targets now come from prediction engine
  (avg 5-bar move), not distant structural levels. Old behavior: gamma wall at 595
  with spot at 580 = 14:1 R:R fantasy. New behavior: prediction says +1.5 pts avg
  move, snaps to nearby VWAP at 582, R:R = 2.2:1. Structural levels used for
  snapping confirmation, not as primary targets. T1 capped at 5:1, T2 at 8:1.
- ✅ **institutional_model.py deleted** — parity function moved to math_exposure.py,
  nothing else was imported. ~500 lines of dead code removed.

### Session 15 (2026-03-03): API Optimization + Statistical Confidence + Phase 3 Complete
- ✅ **CORE_TICKERS expanded** — 3 → 12 (SPY, QQQ, IWM + NVDA, AAPL, MSFT, AMZN,
  META, TSLA, GOOGL, AVGO). All mega-caps now building prediction databases.
- ✅ **Market context cache** — 17 global API calls (VIX + indices + constituents +
  sectors) fetched ONCE per cycle, shared across all tickers. Was re-fetching per
  ticker = 51+ duplicate calls/cycle.
- ✅ **Ticker persistence** — any ticker viewed in UI auto-added to background logger,
  saved to `.logger_tickers.json`, survives server restarts.
- ✅ **Logger dedup** — if UI already logged a ticker this cycle, background logger
  skips it (avoids duplicate snapshots).
- ✅ **API budget: ~106 calls/min** (limit: 120) with 12 tickers at 30s cycle.
  Old code burned ~160/min with just 3 tickers.
- ✅ **GEX/DEX drivers on frontend** — top 3 strikes by exposure rendered in key
  levels table with color coding (yellow=GEX, cyan=DEX).
- ✅ **Binomial confidence test** — `determine_confidence` now uses one-sided binomial
  test against H0: p=1/3 (random 3-class). p-value shown in model note. Automatically
  scales with sample size (30 samples needs bigger skew than 3,000 samples).
- ✅ **Recency half-life tightened** — 21 days → 10 days. Setups from last week are
  weighted heavily, setups from a month ago are nearly invisible.
- ✅ **Vanna d1 correction tested and reverted** — numerically unstable for 0DTE.
  Current ATM approximation is correct because API vega encodes moneyness.
- ✅ **Charm normalization confirmed** — already uses net/gross ratio, no changes needed.
- ✅ **Expected shortfall (3b)** — reversal risk now shows avg damage in pts when
  reversal occurs + severity label (mild/moderate/severe). Severity scaled to % of
  spot so it works across instruments. Frontend shows alongside reversal probability.
- ✅ **Continuous cross-instrument scores (3e)** — replaced binary confirming/diverging
  with magnitude-aware scoring. Uses raw SPY/QQQ/IWM change% to measure alignment ×
  strength. Five levels: strong_confirm, confirming, neutral, diverging, strong_diverge.
  Divergence actively downgrades The Call conviction. Notes show basis points.
- ✅ **Accuracy trend chart (3.5)** — canvas sparkline in prediction card shows 5c
  accuracy over time. Fetches from /api/accuracy every 5 min. 33% random-chance
  baseline marked. Green dots above baseline, red below.

---

## CURRENT STATE

### Database
- ~8,700+ total snapshots (~78/day RTH per ticker, now 12 tickers)
- Zone distribution: breakdown=5,560, pin_bull=2,166, pin_neutral=541, pin_bear=237, breakout=207
- Horizons: 3c/5c/8c/13c (pure Fibonacci)
- Accuracy tracking: model_accuracy table, auto-computed every 10 min
- No artificial sample cap

### Architecture
- All math centralized in math_exposure.py with named constants
- Single option scoring system
- 6 distinct zones with transition detection
- Prediction-based targets with structural level snapping (not the other way around)
- IV direction tracking for vanna context
- Wall detection with minimum strength threshold
- Percentage-based thresholds throughout (scales across underlyings)
- Debug endpoint for live prediction diagnostics
- Market context cached once per cycle (17 calls shared, not duplicated per ticker)
- 12 core tickers logging continuously + any ticker viewed in UI persisted
- Binomial confidence test with p-value (replaces arbitrary thresholds)
- Recency half-life: 10 days (recent data weighted heavily)

### Known Data Issues
- pin_bear has only 237 samples (growing but still thin)
- breakout has only 207 samples (2.4% of total — genuinely rare)
- ~6,078 old snapshots have vwap_side=NULL (pre-fix)

---

## REMAINING WORK

### Quick Wins (next session)
- [x] **Surface top GEX/DEX drivers on frontend** — rendered in key levels table
  with yellow (GEX) and cyan (DEX) color coding, top 3 strikes each.

### Phase 2: Improve Prediction Quality
**Goal:** Use the data you're already collecting better.

- [x] **2a. Add time-of-day to matching** — session_bucket implemented
- [x] **2b. Add VIX regime to matching** — vix_bucket implemented
- [x] **2c. Time-weighted probabilities** — exponential decay (half_life=10 days)
- [x] **2e. Binomial confidence test** — one-sided binomial test replaces arbitrary
  thresholds. p-value displayed in model note. Confidence scales with sample size.

### Phase 3: Formula Upgrades
**Goal:** Institutional-grade math throughout.

- [x] **3a. Magnitude-aware bias classification** — GEX/DEX magnitude gates implemented
- [x] **3b. Expected shortfall** — when reversal occurs, shows avg damage in pts + severity
  (mild/moderate/severe) scaled to % of spot. Frontend shows alongside reversal probability.
- [x] **3c. Full vanna formula** — TESTED AND REVERTED. d1 correction is numerically
  unstable for 0DTE (σ√T ≈ 0.005 makes d1 blow up for any OTM strike). API-provided
  vega already captures moneyness. Current formula is correct for 0DTE.
- [x] **3d. Normalize charm threshold** — already uses net/gross ratio (inherently
  normalized across instruments). No change needed.
- [x] **3e. Continuous cross-instrument scores** — SPY/QQQ/IWM alignment scored by
  direction agreement × magnitude. strong_confirm/confirming/diverging/strong_diverge.
  Divergence actively downgrades conviction. Notes show basis points.

### Phase 3.5: Frontend Polish
- [x] Surface GEX/DEX top drivers in UI
- [x] Accuracy trend chart — canvas sparkline shows 5c accuracy history over time,
  fetched from /api/accuracy every 5 min. 33% random-chance baseline drawn.

### Phase 4: Machine Learning
**Goal:** Replace naive probability engine with gradient boosted trees.

- [x] **4a. Train XGBoost on 50+ features with clean labels** — ml_train.py extracts
  88 features (Greeks, distances, cross-instrument, VIX, time, zone, candle patterns).
  Walk-forward CV with 5 time-ordered folds. Uses XGBoost (preferred) or sklearn
  HistGradientBoosting (fallback).
- [x] **4b. Proper walk-forward cross-validation** — expanding window, always train on
  past and test on future. No data leakage.
- [x] **4c. Feature importance analysis** — ranked by model importance with category
  breakdown (Greek/Exposure, Price Action, Cross-Instrument, Volatility, Time, Zone).
- [x] **4d. Slot into pipeline** — ml_predict.py loads trained model, signals.py tries
  ML first for 5c horizon and falls back to rules engine. Both tracked for A/B comparison.
- [ ] **4e. A/B test** — run ML alongside rules engine, compare accuracy over 1 week
- [ ] **4f. Deploy** when ML proves ≥5% accuracy improvement over rules baseline

### Phase 5: Deep Learning (50K+ snapshots)
- [ ] Sequence models on candle + Greek time series
- [ ] Attention-based regime detection
- [ ] At current rate (~78/day), ~50K snapshots in ~18 months

---

## ML TRIGGER CRITERIA

**All five boxes checked:**

- [x] Direction labels fixed to percentage-based AND historical data relabeled
- [x] Zone classification expanded (6 zones, not collapsing 7 regimes into "pin")
- [x] Accuracy tracking wired up, running, and baseline numbers documented
- [x] At least 7 days of clean data collected with fixed labels (relabeled all 8,700+)
- [x] Baseline accuracy measured and recorded (rules engine numbers by tier)

**ML approach:** XGBoost (or sklearn HistGradientBoosting fallback) on 88 tabular features.
**ML replaces:** `compute_probs()` for 5c horizon in signals.py (probability engine only).
**ML does NOT replace:** GEX math, charm, breakout scoring, The Call logic, stops.
**Integration:** signals.py tries ML first, falls back to rules. Both tracked for A/B.

## HOW TO TRAIN & DEPLOY

```bash
# 1. Install XGBoost (one time)
pip install xgboost

# 2. Train model (run from ed_console directory)
python ml_train.py --db ed_console.db --compare --feature-importance

# 3. Check results — need avg accuracy > 38% (5pp over random)
#    Model saved to models/xgb_5c_direction.pkl

# 4. Restart server — ml_predict.py auto-loads model if present
#    Model note will show "Engine: ML (ml_v1)" when active

# 5. Monitor A/B for 1 week via /api/accuracy
#    Compare ML accuracy vs rules accuracy per zone
```

---

## KEY CONSTANTS (in math_exposure.py)

| Constant | Value | Purpose |
|---|---|---|
| DIRECTION_THRESHOLD_PCT | 0.05 | % of spot to classify up/down/flat |
| EXPOSURE_LARGE_RATIO | 0.50 | Net/gross ratio for "large" magnitude |
| EXPOSURE_MODERATE_RATIO | 0.25 | Net/gross ratio for "moderate" |
| EXPOSURE_SMALL_RATIO | 0.10 | Net/gross ratio for "small" (below = negligible) |
| STOP_BASE_PCT | 0.0018 | Stop distance as % of spot (0.18%) |
| STOP_VIX_HIGH_PCT | 0.0006 | Additional stop width for VIX > 30 |
| MIN_SAMPLES_STATISTICAL | 30 | Minimum for any prediction |
| MIN_SAMPLES_CONFIDENT | 150 | Minimum for medium+ confidence |
| WALL_MIN_MULT | 1.5 | Wall must be ≥1.5× median to qualify |
| RECENCY_HALF_LIFE_DAYS | 10.0 | Exponential decay: 10d ago = 50% weight |

## PREDICTION HORIZONS (Pure Fibonacci)

| Horizon | Bars | Time | Use |
|---|---|---|---|
| 3c | 3 | 15 min | Entry confirmation, initial reaction |
| 5c | 5 | 25 min | Primary trade horizon (setup plays out or fails) |
| 8c | 8 | 40 min | One session leg (open→mid, lunch→PM) |
| 13c | 13 | 65 min | Full 0DTE trade lifecycle |

## ZONE CLASSIFICATION

| Zone | Condition | Description |
|---|---|---|
| pin_bull | γ > 0, δ > 0 | Positive gamma pin, bullish lean |
| pin_bear | γ > 0, δ < 0 | Positive gamma pin, bearish lean |
| pin_neutral | γ > 0, δ ≈ 0 | Positive gamma pin, no lean |
| pin_chaos | γ > 0, pin weak | Very low pin strength, no structure |
| breakout | γ < 0, δ > 0 | Negative gamma, expanding up |
| breakdown | γ < 0, δ < 0 | Negative gamma, expanding down |

---

## HOW TO USE THIS ROADMAP

1. **Starting a new session:** Upload this file + relevant source files.
   Say "Here's my roadmap, let's continue with [Phase X, item Y]."

2. **After completing work:** Ask Claude to update the roadmap with
   checked boxes and any new findings.

3. **When ML is ready:** All trigger criteria checked + 7 days clean data +
   baseline accuracy documented. Paste roadmap and trigger ML discussion.

4. **Quick status check:** The checked/unchecked boxes tell the full story.


====================================================================================================
# SOURCE DOCUMENT: institutional_trading_engine.md
**Date:** 2026-03-30 | **Role:** First 'institutional engine' articulation | **Original size:** 1,819 bytes
====================================================================================================

# Institutional Liquidity, Positioning & Flow Engine

## How to See What Institutions See --- and Trade It

------------------------------------------------------------------------

## 1. CORE TRUTH (FOUNDATION)

Price moves to where liquidity exists.\
Execution happens at liquidity.\
Continuation or reversal is determined by positioning + hedging + flow.

------------------------------------------------------------------------

## 2. SYSTEM ARCHITECTURE

### Liquidity → Event → Reaction → Outcome

------------------------------------------------------------------------

## 3. LIQUIDITY MAP

Detect: - Equal highs / lows - Prior highs / lows - VWAP - Volume
profile (HVN / LVN) - Gamma walls

------------------------------------------------------------------------

## 4. POSITIONING ENGINE

Measure: - Gamma Exposure (GEX) - Delta Exposure - Call / Put skew

Regime: - Positive Gamma → Mean Reversion - Negative Gamma → Trend

------------------------------------------------------------------------

## 5. ORDER FLOW

Track: - Delta (buy vs sell) - Volume spikes - Imbalance

------------------------------------------------------------------------

## 6. ABSORPTION vs CONTINUATION

### Absorption (Reversal)

-   High volume
-   Strong delta
-   Price stalls

→ Institutions taking the other side

------------------------------------------------------------------------

### Continuation (Breakout)

-   Strong delta
-   Price expands
-   No rejection

→ Liquidity becomes fuel

------------------------------------------------------------------------

## 7. DECISION MODEL

Liquidity + Positioning + Reaction = Direction

------------------------------------------------------------------------

## 8. FINAL TRUTH

You do not trade where price is.\
You trade how price behaves at liquidity.


====================================================================================================
# SOURCE DOCUMENT: pytorch_tensorflow_vs_my_stack.md
**Date:** 2026-03-30 | **Role:** THE STACK — framework comparison and the case for the chosen model stack | **Original size:** 27,678 bytes
====================================================================================================

# PyTorch vs TensorFlow vs My Existing Trading Stack
**Prepared for review in Cursor**

---

## Purpose of This Document

This document is meant to help evaluate **how PyTorch and TensorFlow compare to my current trading system stack**, and whether either framework should be added, where they should be added, and where they should **not** be added.

This is not a generic machine-learning comparison. It is written specifically for a **custom institutional-style trading engine** that already includes:

- market data ingestion
- options chain analytics
- institutional positioning math
- feature engineering
- prediction models
- Monte Carlo / path logic
- fusion / ensemble logic
- signal generation
- trade planning
- UI / reporting / diagnostics
- model training / promotion / architecture comparison

The central question is **not**:

> “Should I replace my stack with PyTorch or TensorFlow?”

The real question is:

> “What parts of my stack already do the job, what parts are missing, and where do PyTorch or TensorFlow fit as targeted additions without corrupting the architecture?”

---

# 1) Core Conclusion

## Bottom line

PyTorch and TensorFlow are **deep learning frameworks**, not complete trading stacks.

My current system is already much broader than either of them.

They only belong inside the **model layer**, specifically for **sequence-based or neural-network-based models** such as:

- LSTM
- GRU
- Transformer
- temporal attention models
- possibly reinforcement learning later

They do **not** replace:

- Schwab data ingestion
- options chain parsing
- institutional exposure math
- gamma / delta / OI calculations
- Monte Carlo framework
- Bayesian fusion logic
- trade rules
- constraints
- UI / dashboard
- execution logic
- database / storage
- model freshness and promotion logic

## Architectural conclusion

The correct institutional-grade design is:

- keep the existing stack for ingestion, features, rules, institutional math, Monte Carlo, reporting, and execution
- keep XGBoost / tabular models for structured features
- add **PyTorch** for deep sequence models
- avoid using TensorFlow unless there is a strong deployment-specific reason

---

# 2) What My Current Stack Actually Is

One of the biggest sources of confusion is treating “AI framework” as though it were the whole application.

It is not.

My stack is already an **end-to-end trading platform**, not just a model library.

## My current stack should be understood as these major layers

### A. Data Layer
This includes:
- Schwab API connectivity
- quote retrieval
- option chain retrieval
- bar/history retrieval
- snapshot logging
- possibly Barchart or other enrichment sources
- timestamping / freshness / market session awareness

This layer answers:
- What is the current price?
- What are the option chains?
- What are the expiries?
- What is the current session?
- What data is fresh vs stale?
- What raw material do the models and logic operate on?

### B. Feature Engineering Layer
This includes:
- technical indicators
- volatility features
- market structure features
- options-related derived features
- institutional positioning features
- support / resistance / ORB / VWAP / ATR / gap logic
- regime classification inputs
- label generation

This layer answers:
- What does the raw market data mean?
- How do we convert market data into model-ready features?
- How do we build prediction targets and training labels?

### C. Institutional / Mechanical Market Layer
This includes:
- gamma exposure logic
- delta pressure logic
- OI walls / pins / inflections
- strike-level mechanical pressure
- support/resistance interpretation from options positioning
- later vanna / charm / dealer gravity logic

This layer answers:
- Where are dealers or large participants likely mechanically pinned or forced to react?
- Where can price accelerate?
- Where are likely support/resistance zones from positioning?
- Where is pin risk, acceleration risk, or reversal risk?

### D. Model Layer
This includes:
- XGBoost
- sklearn baselines
- future LSTM / Transformer / sequence models
- Monte Carlo
- volatility forecasting
- model comparison
- parallel vs cascade experimentation
- promotion logic

This layer answers:
- What is the likely direction?
- What is the probability distribution?
- What is the expected move?
- Which model architecture is currently performing best?

### E. Constraint / Sanity Layer
This includes:
- ATR realism checks
- price bound logic
- session-aware constraints
- liquidity constraints
- institutional-level constraints
- no-trade or degraded-trade conditions

This layer answers:
- Even if a model predicts something, is it actually tradable?
- Is the target realistic?
- Is the market state appropriate for action?

### F. Decision Layer
This includes:
- trade signal generation
- call/put recommendation
- entry / stop / target selection
- confidence scoring
- reasoning / explanation
- signal path reporting

This layer answers:
- What should be done?
- Is the trade a call, put, or wait?
- How strong is the signal?
- Why did the engine decide that?

### G. Application Layer
This includes:
- dashboard
- scanner
- watchlist ranking
- diagnostics
- training status
- logging
- historical persistence
- report generation
- alerting
- potentially execution hooks

This layer answers:
- How does the user interact with the system?
- How do results appear?
- How do we inspect health, freshness, and errors?

## Important architecture insight

This means my “stack” is already:

- software architecture
- data architecture
- feature architecture
- model architecture
- decision architecture
- user interface architecture

PyTorch and TensorFlow operate in only **one subsection** of that total system.

---

# 3) What PyTorch and TensorFlow Actually Are

## PyTorch
PyTorch is a deep learning framework strongly favored for:
- research
- experimentation
- custom architectures
- sequence models
- neural nets requiring flexible design
- fast iteration
- easier debugging

It is especially strong when building:
- LSTMs
- Transformers
- custom temporal models
- multi-input neural architectures

## TensorFlow
TensorFlow is also a deep learning framework and can build many of the same model types. It is often used in:
- production environments
- Keras-based workflows
- enterprise pipelines already standardized around TensorFlow

It can absolutely perform the same general class of tasks:
- dense nets
- LSTMs
- Transformers
- sequence models
- GPU-accelerated training

## Critical clarification
Neither PyTorch nor TensorFlow is:
- a brokerage integration layer
- a market data framework
- an options analytics system
- a UI framework
- a complete trading engine
- a signal engine by itself
- a business-rules engine
- a Monte Carlo system by default
- a gamma exposure engine
- a confluence engine

They are tools for training and running neural networks.

That is all.

That is very important, because many architecture mistakes come from trying to force them into areas they do not belong.

---

# 4) Where PyTorch / TensorFlow Fit in My Stack

## They belong inside the Model Layer only

More specifically, they belong in the **deep sequence model section** of the model layer.

### Examples of where they fit correctly
- LSTM that consumes the last 30–120 bars
- Transformer that consumes multi-timeframe sequences
- temporal pattern classifier for continuation vs reversal
- sequence-based breakout/failure model
- neural model for short-term path-shape classification
- potentially an execution model later

### Examples of where they do not fit
- API authentication
- Schwab chain fetches
- price history downloads
- options strike normalization
- gamma/delta/OI exposure calculations
- ATR bands
- pivot calculations
- VWAP calculations
- expiry matching logic
- stale/fresh file diagnostics
- UI tables
- report formatting
- signal labeling logic that is deterministic
- database snapshots
- scheduler orchestration
- model registry management

## Clean architectural mapping

```text
[Market Data] -> [Feature Engineering] -> [Model Layer] -> [Constraints] -> [Decision Engine] -> [UI/Execution]
```

PyTorch/TensorFlow are only part of:

```text
[Model Layer]
```

not the whole chain.

---

# 5) How My Stack Should Be Structured Conceptually

## Correct end-to-end architecture

```text
[Market Data Sources]
    Schwab API
    Options Chains
    Bars / OHLCV
    Quotes / Greeks / Expiries
    External enrichments (optional)

        ↓

[Ingestion / Validation Layer]
    quote fetchers
    chain fetchers
    bar fetchers
    snapshot logging
    freshness / session state
    error handling

        ↓

[Feature Engineering Layer]
    technical indicators
    volatility features
    market structure
    institutional positioning features
    session / regime features
    labels / targets

        ↓

[Model Layer]
    Tabular models (XGBoost / sklearn)
    Sequence models (PyTorch LSTM / Transformer)
    Volatility forecasting
    Monte Carlo / path simulation
    Fusion / ensemble logic

        ↓

[Constraint Layer]
    ATR sanity
    support/resistance proximity
    session constraints
    liquidity / spread constraints
    institutional level checks

        ↓

[Decision Layer]
    call / put / wait
    confidence
    entry / stop / target
    explanation and diagnostics

        ↓

[Application Layer]
    dashboard
    scanner
    alerts
    logs
    training status
    reports
    execution hooks
```

## Key takeaway

If PyTorch or TensorFlow are introduced, they should be introduced **surgically**, not broadly.

They should **augment** the model layer, not hijack the architecture.

---

# 6) Why My Current Stack Still Needs XGBoost Even if PyTorch Is Added

A common mistake is assuming that once deep learning is added, classical models should be removed.

That is usually wrong in trading systems.

## Why XGBoost still matters

XGBoost is extremely strong for:
- tabular engineered features
- structured market features
- low-latency retraining
- feature importance analysis
- robustness on medium-sized datasets
- strong performance on noisy financial data

Examples of features XGBoost handles very well:
- RSI
- VWAP distance
- ATR ratio
- EMA stack state
- realized volatility
- gap percentage
- volume surge
- gamma wall distance
- delta imbalance
- OI skew
- regime flags
- session flags
- confluence counts
- support/resistance proximity

These are all structured features.

That is XGBoost territory.

## Why PyTorch still matters

PyTorch matters when the information is encoded in the **sequence itself**, such as:
- the order of bars
- the tempo of price movement
- evolving momentum shape
- sequence of pullbacks and rejections
- bar-by-bar transition behavior
- multi-timeframe sequence interactions

This is where sequence models add value.

## Correct conclusion

The best design is not:

> XGBoost or PyTorch

It is:

> XGBoost for structured features + PyTorch for sequence intelligence

---

# 7) Why PyTorch Is a Better Fit Than TensorFlow for My Use Case

## Practical reason #1: custom research flexibility

My stack is not a generic tutorial project.
It is a custom institutional-style system with:
- hybrid models
- nonstandard features
- options-driven institutional logic
- rule overlays
- architecture comparisons
- path simulation
- promotion logic
- lots of iteration

PyTorch is generally better suited to:
- custom experimentation
- nonstandard architectures
- debugging intermediate tensors
- fast iteration during model development

## Practical reason #2: easier mental model

PyTorch tends to feel more like normal Python.
That matters in a system where:
- there is a lot of custom logic
- there are many interfaces between modules
- the model has to coexist with rules, diagnostics, and constraint logic

## Practical reason #3: sequence modeling pathway

My future neural use cases are more aligned with:
- LSTM
- Transformer
- temporal attention
- sequence classification
- multi-input time-series models

PyTorch is especially well suited to those workflows.

## Practical reason #4: cleaner fit with a hybrid quant engine

Because the broader engine already includes:
- XGBoost
- custom Python logic
- Monte Carlo
- Bayesian fusion
- institutional math
- decision heuristics

PyTorch works cleanly as one part of a larger Python-native research system.

## When TensorFlow might still make sense

TensorFlow might make sense if:
- deployment tooling is already built around TensorFlow
- the environment is already standardized on Keras/TensorFlow
- there is a strong external reason tied to infrastructure or engineering team preference

Absent that, PyTorch is usually the better choice here.

---

# 8) What PyTorch Should Be Used For First

The first deployment of PyTorch should be modest and high-value.

It should not begin as a giant multi-branch Transformer monster.

## Best first use case
Start with a **PyTorch LSTM**.

## Why LSTM first
- lower complexity than Transformer
- easier to validate
- easier to debug
- lighter compute burden
- easier to compare directly against XGBoost
- strong enough to test whether sequence learning adds measurable edge

## Good first prediction targets
A first LSTM could predict one of the following:

### Option A: next-N-bar direction
Input:
- last 60 one-minute bars
- OHLCV
- VWAP distance
- EMA spread / stack
- RSI / MACD state
- ATR context
- gamma / delta / OI context
- regime features

Output:
- probability of upward move over next 5 bars
- probability of downward move over next 5 bars

### Option B: target-first / stop-first probability
Input:
- recent bar sequence plus context features

Output:
- probability that +1 ATR is hit before -1 ATR
- probability that -1 ATR is hit before +1 ATR

This is often more useful than simple direction classification.

### Option C: breakout continuation vs failure
Input:
- pre-breakout sequence
- distance to key level
- volume context
- dealer pressure context
- volatility compression/expansion features

Output:
- continuation probability
- failure probability
- chop / pin probability

## Why this matters
This gives a controlled way to test whether sequence modeling is adding value without destabilizing the system.

---

# 9) What the First Transformer Should Be Used For

Only after the LSTM proves useful should the architecture move to a Transformer.

## Good Transformer use cases
- longer sequence windows
- multi-timeframe sequence fusion
- attention over mixed input channels
- regime-shift awareness over longer horizons
- pattern recognition that depends on nonlocal sequence relationships

## Example
A Transformer could consume:
- 1-minute sequence for last 90 bars
- 5-minute sequence for last 60 bars
- 15-minute compressed context
- volatility channel
- institutional feature channel
- session/time embedding

and output:
- continuation / reversal / pin probabilities
- expected move band
- confidence conditioned on regime

## Important caution
A Transformer should not be introduced just because it is fashionable.
It should be introduced because:
- sequence length and structure justify it
- the LSTM baseline is no longer sufficient
- the data volume and compute budget support it

---

# 10) How PyTorch Should Interact with the Rest of the Engine

This is one of the most important architecture rules in the entire document.

## Correct interaction pattern

```text
PyTorch model output
    ↓
Fusion layer
    ↓
Constraint layer
    ↓
Decision engine
    ↓
Trade plan
```

## Incorrect interaction pattern

```text
PyTorch predicts up
    ↓
Immediately buy call
```

That is not acceptable.

## Why not
Because a neural net by itself does not know:
- whether price is directly under a major gamma wall
- whether the target is unrealistic relative to ATR
- whether the session is illiquid
- whether expiration structure makes continuation unlikely
- whether spread/liquidity makes the trade untradeable
- whether the predicted move conflicts with strong mechanical positioning

The model should provide **probabilistic intelligence**, not unilateral authority.

## Better institutional logic

The full engine should work like this:

1. PyTorch estimates sequence-based directional/path probability
2. XGBoost estimates structured-feature probability
3. Monte Carlo estimates path distribution
4. institutional positioning layer identifies mechanical constraints
5. fusion layer combines all evidence
6. constraint layer downgrades or blocks invalid trades
7. decision layer generates final trade recommendation

That is a professional design.

---

# 11) Recommended Model Stack for My System

## Recommended stack

### Structured / tabular model
- XGBoost as a core baseline model

### Deep sequence model
- PyTorch LSTM first
- PyTorch Transformer second

### Volatility / path model
- GARCH or similar rolling volatility forecast
- Monte Carlo with step-specific volatility if available

### Fusion layer
- Bayesian aggregation or weighted ensemble
- confidence calibration
- architecture comparison / promotion logic

### Mechanical / institutional overlay
- gamma walls
- delta pressure
- OI walls / pins / inflections
- later vanna / charm
- key support / resistance / pin zones

### Decision layer
- call / put / wait
- target / stop / entry
- regime-aware explanation
- confidence + blocker reasons

---

# 12) What Should Stay Pure Python and Not Be Moved into PyTorch

This is a critical engineering boundary.

## Keep in standard Python modules
- options chain normalization
- chain expiry filtering
- gamma / delta / OI exposure formulas
- support/resistance derivation
- institutional level ranking
- ATR calculations
- VWAP calculations
- pivot points
- ORB logic
- regime flags
- data cleaning
- timestamp and freshness logic
- API wrappers
- database operations
- report assembly
- dashboard formatting
- signal explanation text
- training scheduler logic
- model registry / promotion logic

## Why
Because these are:
- deterministic calculations
- domain logic
- business logic
- infrastructure logic
- orchestration logic

PyTorch is not the right tool for those jobs.

---

# 13) Anti-Patterns to Avoid

## Anti-pattern 1: replacing the entire stack with a deep learning framework
This would be a category error.
A deep learning framework is not an entire trading system.

## Anti-pattern 2: using deep learning where tabular models are better
Not every problem needs a neural network.
Many trading features are tabular and well-suited to XGBoost.

## Anti-pattern 3: letting the neural network override institutional logic
A model should not overrule strong mechanical constraints without being checked.

## Anti-pattern 4: skipping a baseline
Every deep model should be compared against:
- XGBoost baseline
- simple heuristic baseline
- regime-aware baseline

If it does not beat those, it should not be promoted.

## Anti-pattern 5: adding TensorFlow and PyTorch simultaneously without a reason
That usually adds complexity with little benefit.
Choose one deep-learning framework unless there is a compelling reason otherwise.

## Anti-pattern 6: starting with a Transformer before validating simpler sequence models
This increases complexity before proving value.

## Anti-pattern 7: mixing model code with UI code
Model math and signal logic should stay outside UI modules.

## Anti-pattern 8: black-box confidence without diagnostics
Every model output should be inspectable:
- probability
- confidence
- freshness
- feature completeness
- model version
- training time
- architecture identity

---

# 14) Recommended Module Boundaries

## Clean Python module layout

```text
data/
    schwab_client.py
    chain_loader.py
    bars_loader.py
    quote_loader.py
    snapshot_store.py

features/
    technical_features.py
    volatility_features.py
    market_structure_features.py
    institutional_features.py
    regime_features.py
    labels.py

models/
    xgb_model.py
    pytorch_lstm.py
    pytorch_transformer.py
    volatility_model.py
    monte_carlo.py
    fusion_model.py
    calibration.py

constraints/
    atr_constraints.py
    institutional_constraints.py
    liquidity_constraints.py
    session_constraints.py
    price_sanity.py

engine/
    prediction_engine.py
    signal_engine.py
    trade_plan_engine.py
    ranking_engine.py

training/
    train_xgb.py
    train_lstm.py
    train_transformer.py
    compare_models.py
    promote_model.py
    artifact_registry.py

ui/
    dashboard.py
    reports.py
    alerts.py
    diagnostics.py
```

## Important rule
PyTorch should live in the `models/` and `training/` areas, not across the entire codebase.

---

# 15) Recommended Evaluation Framework

Before adding PyTorch to the production decision stack, it should be evaluated rigorously.

## The evaluation should answer:

### A. Does the sequence model outperform XGBoost?
Metrics could include:
- directional accuracy
- Brier score
- calibration
- expectancy after costs/slippage assumptions
- target-first vs stop-first discrimination
- regime-specific performance
- performance near institutional levels

### B. Is the performance stable across regimes?
For example:
- trend day
- chop day
- high-volatility session
- low-volatility session
- opening drive
- midday drift
- close / pin behavior

### C. Does it improve the ensemble?
Even if it is not the best standalone model, it may still improve the fused stack.

### D. Does it remain interpretable enough operationally?
The user should still be able to see:
- current model version
- architecture type
- last trained time
- current freshness
- whether it is active or experimental
- probability output
- any blockers applied downstream

---

# 16) Recommended Decision Matrix

## What to keep as-is
- market data layer
- options chain layer
- institutional math layer
- Monte Carlo framework
- trade decision framework
- UI / reporting / alerts
- training/promotion architecture
- XGBoost baseline

## What to add
- PyTorch LSTM
- later PyTorch Transformer

## What to avoid unless necessary
- TensorFlow
- redundant framework duplication
- broad architectural rewrites for “AI branding”
- neural-net-only signal logic

---

# 17) The Correct Framing for Cursor

The right prompt framing for Cursor is not:

> “Should I switch my stack to PyTorch?”

The better framing is:

> “Audit my existing stack and tell me exactly where PyTorch would provide real value, where XGBoost remains the better choice, where TensorFlow adds no practical benefit, and how to integrate sequence models without disturbing my institutional math, rule engine, Monte Carlo, or decision architecture.”

---

# 18) Questions Cursor Should Answer About My Stack

## Architecture audit questions
1. Which parts of my stack are already correctly separated into:
   - data
   - features
   - models
   - constraints
   - decision logic
   - UI

2. Are any current files mixing:
   - UI logic with model logic
   - model logic with institutional math
   - data fetching with feature generation
   - prediction logic with decision logic

3. Are deep-learning responsibilities isolated enough that PyTorch can be added cleanly?

## Model-fit questions
4. Which current prediction tasks are tabular enough that XGBoost should remain primary?

5. Which current prediction tasks are sequence-dependent enough that PyTorch would likely improve performance?

6. Is there any current model logic pretending to be sequence-aware while actually operating on flattened tabular snapshots?

## TensorFlow vs PyTorch questions
7. Is there any technical reason in my current environment that would make TensorFlow preferable to PyTorch?

8. Is there any deployment, packaging, or infrastructure reason to keep TensorFlow in consideration?

9. If not, should PyTorch be the only deep-learning framework added?

## Integration questions
10. Where exactly should a first `pytorch_lstm.py` module plug into the current stack?

11. What training pipeline changes are required to support a sequence model cleanly?

12. How should sequence data windows be generated from my existing snapshots/history?

13. How should sequence-model outputs be fused with:
   - XGBoost outputs
   - Monte Carlo outputs
   - institutional constraints
   - decision scoring

## Production-control questions
14. How should model freshness, last-trained timestamp, and architecture identity be surfaced in the UI?

15. How should promotion work between:
   - parallel vs cascade
   - XGBoost vs LSTM
   - LSTM vs Transformer
   - standalone vs fused ensemble

16. What diagnostics should be mandatory before a deep model influences live signals?

---

# 19) Suggested Prompt to Give Cursor

Use this as the working prompt:

```md
Audit my existing trading stack against the following architecture standard:

- Keep market data ingestion, options chain processing, institutional math, Monte Carlo, constraints, decision logic, UI, logging, and model-promotion logic outside of any deep-learning framework.
- Keep XGBoost as the primary tabular model for engineered structured features.
- Add PyTorch only for sequence-based models such as LSTM or Transformer.
- Treat TensorFlow as unnecessary unless there is a concrete infrastructure reason to prefer it.

I want you to evaluate my current codebase and answer these questions in detail:

1. Which parts of my stack are already modular and correctly separated by concern?
2. Which files currently mix responsibilities and should be refactored before adding PyTorch?
3. Which prediction problems in my code are best handled by XGBoost?
4. Which prediction problems are sequence-dependent enough to justify a PyTorch LSTM?
5. Is there any real reason to use TensorFlow instead of PyTorch in my current environment?
6. Where exactly should the first PyTorch module plug into the current stack?
7. What data windowing / dataset-building pipeline is required for sequence modeling from my existing snapshots and history?
8. How should PyTorch model outputs be fused with XGBoost, Monte Carlo, and institutional constraints?
9. What diagnostics, freshness checks, and promotion controls should be required before a deep model is allowed to influence live trade signals?
10. Give me a recommended refactor plan that preserves the existing app behavior while making the model layer institution-grade and modular.

Do not give generic AI advice. Evaluate this specifically as a hybrid institutional trading system with:
- options positioning
- gamma/delta/OI logic
- Monte Carlo
- Bayesian/ensemble fusion
- trade constraints
- live dashboard/reporting requirements
- model freshness and promotion requirements
```

---

# 20) Final Recommendation

## Final technical judgment

My current stack should be viewed as an **institutional-style trading platform** with multiple layers, not as a simple ML notebook.

Because of that:

- PyTorch is **not** a replacement for the stack
- TensorFlow is **not** a replacement for the stack
- XGBoost should remain a core model
- PyTorch should be introduced selectively for sequence intelligence
- TensorFlow should only be considered if there is a specific deployment reason
- the broader architecture should remain Python-centric and modular
- deep learning should augment the prediction layer, not consume the rest of the system

## Final recommendation in one sentence

The right design is:

**keep the existing platform architecture, keep XGBoost for tabular prediction, add PyTorch for sequence models, and force all model outputs through institutional constraints and the decision engine before they can affect live trade recommendations.**

---

====================================================================================================
# SOURCE DOCUMENT: Ed_Trading_System_Issues_ChatGPT_MASTER.md
**Date:** 2026-04-01 | **Role:** Early issue master (ChatGPT era) | **Original size:** 3,140 bytes
====================================================================================================

# ED INSTITUTIONAL PREDICTIVE TRADING ENGINE
## FULL SYSTEM SPECIFICATION + ACTIVE TRACKERS (UPDATED)

---

# 1. SYSTEM PHILOSOPHY

> Every number must be explainable, reproducible, and derived from a consistent definition.

This system is built on data contracts, not assumptions.

---

# 2. ARCHITECTURE OVERVIEW

Raw Data → price_bars_1m → snapshots → outcomes → features → models → decisions → UI

---

# 3. CORE DATA CONTRACT

Source of truth:
- price_bars_1m (UTC-aligned 1m bars)

---

# 4. HORIZON SYSTEM

outcome_Nc = classify(anchor_close → forward_close)

1c / 5c / 15c / 60c (true bar-based)

---

# 5. ANCHOR SYSTEM

anchor_close = last completed 1m bar where bar_end ≤ snapshot_ts

---

# 6. OUTCOME ENGINE

pts = forward_close - anchor_close  
direction = up / down / flat  

Schema: v3

---

# 7. INSUFFICIENCY POLICY

If insufficient:
- no probabilities
- show counts + required + remaining

Dynamic + reversible

---

# 8. INTERNAL LOGIC CONTRACT

Missing data:
- stays None
- becomes NaN for ML
- never replaced with neutral

---

# 9. FEATURE CONTRACT

- identical training + inference
- NaN preserved
- no silent substitution

---

# 10. MODEL CONTRACT

Required fields:
- label_config_version
- horizon_outcome_schema_version
- anchor_contract_version
- feature_schema_version
- missingness_contract_version

Rule:
NO PROOF = NO LOAD

---

# 11. CURRENT MODEL STATE

All models: BLOCKED  
Reason: no valid contract metadata

---

# 12. PRIMARY ISSUE TRACKER

## CLOSED
1. Timeframe integrity  
2. Remove non-target horizons  
3. Universal horizon standardization  
4. Anchor standardization  
5. Fallback policy formalization  
6. Internal decision integrity  
7. Feature/schema parity / model enforcement  
8. UI bug (hint)  
9. Confluence render hardening  
12. Full UI null-guard hardening  

## OPEN
10. Universe persistence / DB population parity  
11. ML retraining / horizon expansion  
13. Decision engine alignment  

---

# 13. DRIFT / RESIDUAL ISSUE TRACKER

## ACTIVE DRIFT

D2. UTC vs session alignment  
- Bars are UTC-based, not session-aware  

D3. Backfill window limitation  
- Older rows may remain NULL  

D4. Cold-start data gaps  
- Missing bars prevent label formation  

D5. Historical continuity gap  
- Multiple label regimes historically  

D7. Anchor boundary edge-case  
- Exact boundary behavior must remain defined  

D8. Feature vs anchor timing mismatch  
- Features may reflect newer data than anchor  

D10. Control-state ambiguity  
- "flat / 0.0 / low" may represent missingness  

---

# 14. NEXT STEPS (ORDERED)

## Issue 10 — Universe persistence
Ensure:
- all fetched tickers populate DB
- not dependent on UI selection

## Issue 11 — ML retraining
Rebuild:
- XGBoost
- LSTM
- Transformer

Under:
- correct horizons
- correct anchor
- correct missingness

## Issue 13 — Decision engine alignment
Ensure:
- no logic assumes fake or stale data
- all outputs consistent with contracts

---

# 15. SYSTEM GUARANTEE

This system guarantees:
- no hidden assumptions
- no fabricated probabilities
- no mixed definitions
- no unverified model usage

---

# END


====================================================================================================
# SOURCE DOCUMENT: Ed_Trading_System_MASTER_v8_AUTHORITATIVE.md
**Date:** 2026-04-01 | **Role:** MASTER SPEC v8 — Predictive Trading Engine, authoritative | **Original size:** 44,865 bytes
====================================================================================================

# ED INSTITUTIONAL PREDICTIVE TRADING ENGINE
## MASTER SPEC + LIVE ISSUE TRACKERS (AUTHORITATIVE MASTER — v8)

---

# 0. BASELINE SOURCE FILE PRESERVATION

This master document uses the original file provided at the start of this session as the project baseline.

## Original baseline file text

```markdown
# ED INSTITUTIONAL PREDICTIVE TRADING ENGINE
## MASTER SPEC + LIVE ISSUE TRACKERS (UPDATED AFTER ISSUE 11)

---

# SYSTEM STATE (CURRENT)

The system now has:
- Correct bar-based horizons
- Canonical anchor
- Honest missingness (no synthetic probabilities)
- Auto-expanding universe with background persistence
- Fully hardened UI (no runtime crashes)
- Valid 1c ML stack restored for compliant tickers

Limitations:
- Some tickers (PCG, SMCI) blocked by insufficient data for promotion
- Multi-horizon ML not yet implemented

---

# PRIMARY ISSUE TRACKER

## CLOSED
1. Timeframe integrity  
2. Remove non-target horizons  
3. Universal horizon standardization  
4. Anchor standardization  
5. Fallback policy formalization  
6. Internal decision integrity  
7. Feature/schema parity / model enforcement  
8. UI bug (hint)  
9. Confluence render hardening  
10. Universe persistence / auto-expanding universe  
11. Restore valid 1c ML stack  
12. Full UI null-guard hardening  

## OPEN
13. Decision engine alignment  
14. Per-horizon training dataset independence  
15. ML horizon expansion: 5c  
16. ML horizon expansion: 15c  
17. ML horizon expansion: 60c  
18. Bring low-data tickers (PCG, SMCI) to promotable depth  

---

# DRIFT / RESIDUAL TRACKER

D2. UTC vs session alignment  
D3. Backfill window limitation  
D4. Cold-start data gaps  
D5. Historical continuity gap  
D7. Anchor boundary edge-case  
D8. Feature vs anchor timing mismatch  
D10. Control-state ambiguity  
D12. Training row eligibility tied to all-horizon outcome_filled  

---

# ML SYSTEM STATE

## Current
- All models trained on outcome_1c
- Artifacts:
  - xgb_{ticker}_1c.pkl
  - lstm_{ticker}_1c.pt
  - transformer_{ticker}_1c.pt
- Contract enforcement active and validated
- Loaders require full metadata compliance

## Not yet implemented
- 5c ML
- 15c ML
- 60c ML
- Per-horizon training eligibility

---

# DATA PIPELINE

price_bars_1m → snapshots → outcome_* → features → ML → decision engine → UI

Persistence:
- All tracked tickers now written to DB via background logger
- No dependency on UI selection

---

# NEXT STEPS (STRICT ORDER)

## Issue 13 — Decision Engine Alignment
- Verify how ML outputs are used
- Confirm no stale assumptions
- Align confidence / signal logic

## Issue 14 — Per-horizon dataset independence
- Remove dependence on outcome_filled for all horizons
- Allow horizon-specific training eligibility

## Issue 15–17 — Multi-horizon ML
- Implement 5c, then 15c, then 60c

---

# GUARANTEES

The system enforces:
- No fake data
- No hidden fallbacks
- No contract violations
- No UI crashes
- No stale model usage

---

# END

```

The remainder of this document preserves that baseline and layers in all validated updates, issue history, architecture clarification, confirmed decisions, and future roadmap items discussed and agreed during this session.

---

# 1. SYSTEM STATE (CURRENT)

The system now has:
- Correct bar-based horizons
- Canonical anchor
- Honest missingness (no synthetic probabilities in production decision flow)
- Auto-expanding universe with background persistence
- Fully hardened UI (no runtime crashes from missing / null values)
- Valid 1c ML stack restored for compliant tickers
- CanonicalForecast as the single runtime decision authority
- Single live inference path for the active runtime stack
- Explicit decision trace logging through `DECISION_BUNDLE`
- Fusion-unavailable states explicitly forced to `WAIT`
- Conviction bounded by canonical forward probabilities / confidence, not allowed to exceed canonical forecast strength

## Limitations
- Some tickers (notably PCG and SMCI) remain blocked by insufficient data for promotion depth
- Multi-horizon ML is not yet implemented
- Per-horizon dataset independence is not yet implemented
- Multi-horizon canonical forecasting is not yet implemented
- Market-state-aware adaptive feature weighting is not yet implemented
- Position sizing is not yet fully derived purely from canonical probabilities
- Parallel vs cascade training architecture has not yet been converged to one winner

## Current operating truth
The system is no longer allowed to run with multiple competing runtime decision truths.  
The runtime stack must resolve to one canonical decision object before a trade decision is produced.

---

# 2. PRIMARY ISSUE TRACKER

## CLOSED

1. Timeframe integrity  
2. Remove non-target horizons  
3. Universal horizon standardization  
4. Anchor standardization  
5. Fallback policy formalization  
6. Internal decision integrity  
7. Feature/schema parity / model enforcement  
8. UI bug (hint)  
9. Confluence render hardening  
10. Universe persistence / auto-expanding universe  
11. Restore valid 1c ML stack  
12. Full UI null-guard hardening  
13. Decision engine alignment  

## OPEN

14. Per-horizon training dataset independence  
15. ML horizon expansion: 5c  
16. ML horizon expansion: 15c  
17. ML horizon expansion: 60c  
18. Bring low-data tickers (PCG, SMCI) to promotable depth  

---

# 3. ISSUE HISTORY — COMPLETE RECORD

## Issue 1 — Timeframe integrity

**Original issue title:** Timeframe integrity

**Historical status:** Closed before this session.  
**Current status:** Still closed.  
**Effect of later work:** No reversal. Issue 13 reinforced the importance of strict timeframe integrity by eliminating mixed-horizon runtime decision behavior.

### What this issue represented
This issue established that the system needed clean timeframe handling and could not tolerate ambiguous or inconsistent horizon semantics.

### Why it mattered
Without timeframe integrity:
- labels become unreliable
- training targets become ambiguous
- decision logic can mix incompatible horizons
- evaluation becomes misleading

### What later work changed
Later work, especially Issue 13, did **not** reopen Issue 1, but it did make its importance more explicit by removing runtime horizon mixing and insisting that live decisions be derived from one coherent forecast object rather than mixed horizon fragments.

### Current interpretation
Issue 1 remains closed and structurally valid.

---

## Issue 2 — Remove non-target horizons

**Original issue title:** Remove non-target horizons

**Historical status:** Closed before this session.  
**Current status:** Still closed.  
**Effect of later work:** No reversal.

### What this issue represented
This issue removed horizon handling that was outside the intended target design.

### Why it mattered
The system needed to stop reasoning over horizons that were not part of the active target framework, because that creates noise, inconsistent UI semantics, and invalid downstream assumptions.

### What later work changed
Issue 13 later eliminated a different but related problem: not just non-target horizon presence, but mixed-horizon decision usage. That means Issue 2 remains correct and closed, while Issue 13 completed the runtime decision integrity that Issue 2 conceptually pointed toward.

### Current interpretation
Issue 2 remains closed and valid.

---

## Issue 3 — Universal horizon standardization

**Original issue title:** Universal horizon standardization

**Historical status:** Closed before this session.  
**Current status:** Still closed.  
**Effect of later work:** No reversal. Future multi-horizon expansion will build on this.

### What this issue represented
The system needed one consistent way to name, interpret, and use horizons throughout training, evaluation, UI, and decision logic.

### Why it mattered
Without universal standardization:
- models and UI can refer to different meanings for the same horizon
- gates can accidentally compare incompatible objects
- logs become unreliable

### What later work changed
Issue 13 exposed that even with closed standardization work, runtime decision logic could still accidentally mix horizon-derived quantities. That later issue did not invalidate Issue 3; it completed the enforcement of its intent.

### Current interpretation
Issue 3 remains closed and is foundational for the later future state of:
- `canonical_1c`
- `canonical_5c`
- `canonical_15c`
- `canonical_60c`

---

## Issue 4 — Anchor standardization

**Original issue title:** Anchor standardization

**Historical status:** Closed before this session.  
**Current status:** Still closed.  
**Effect of later work:** No reversal.

### What this issue represented
The system needed a canonical anchor convention for runtime and training reference points.

### Why it mattered
Without anchor standardization:
- feature timing can drift
- labels can misalign with the intended reference
- downstream signals can appear correct while being built on inconsistent temporal anchoring

### What later work changed
The residual tracker still contains:
- D7. Anchor boundary edge-case
- D8. Feature vs anchor timing mismatch

This does **not** reopen Issue 4. It means the broad standardization is complete, while edge cases and residual drift remain tracked.

### Current interpretation
Issue 4 remains closed; residual anchor-related items remain under drift tracking, not as a reopened core issue.

---

## Issue 5 — Fallback policy formalization

**Original issue title:** Fallback policy formalization

**Historical status:** Closed before this session.  
**Current status:** Closed and materially reinforced by Issue 13.

### What this issue represented
The system needed explicit rules for what happens when preferred inputs or model states are unavailable.

### Why it mattered
Unformalized fallback behavior is dangerous because it can:
- silently fabricate confidence
- hide missingness
- create misleading trade bias
- weaken trust in the system

### What later work changed
Issue 13 materially tightened Issue 5. The system now enforces:
- no synthetic probabilities in production decision flow
- explicit `WAIT` when fusion/canonical posterior is unavailable
- constraints on override behavior so fake probabilities cannot silently influence live decisions

### Current interpretation
Issue 5 remains closed, but its operational meaning is now stricter than before:
- fallback may protect rendering or continuity
- fallback may **not** invent tradable confidence or direction

---

## Issue 6 — Internal decision integrity

**Original issue title:** Internal decision integrity

**Historical status:** Closed before this session.  
**Current status:** Closed and fully finalized by Issue 13.

### What this issue represented
The system needed its internal decisions to be logically coherent and not allow contradictory states across submodules.

### Why it mattered
A trading system cannot claim integrity if:
- one layer says bullish and another silently governs bearish
- confidence and direction come from different uncoordinated truths
- the UI and runtime logic describe different states

### What later work changed
Issue 13 is the full realization of Issue 6. It:
- introduced `CanonicalForecast`
- removed competing prediction truths
- aligned readiness, gating, conviction, and signal logic
- enforced one runtime decision authority

### Current interpretation
Issue 6 is not merely closed; it is fully completed by the Issue 13 alignment work.

---

## Issue 7 — Feature/schema parity / model enforcement

**Original issue title:** Feature/schema parity / model enforcement

**Historical status:** Closed before this session.  
**Current status:** Closed.  
**Effect of later work:** Reinforced by Issue 11 and Issue 13.

### What this issue represented
The system needed strict agreement between:
- feature generation
- expected model schema
- loader assumptions
- live inference expectations

### Why it mattered
Without schema parity:
- live inference can silently break
- active models can become unusable
- evaluation and deployment diverge

### What later work changed
Issue 11 reinforced this through strict loader compliance and model contract enforcement.  
Issue 13 reinforced it again by forcing a single runtime inference path and removing duplicate semantic access paths.

### Current interpretation
Issue 7 remains closed and continues to govern the strictness of live model loading and inference compatibility.

---

## Issue 8 — UI bug (hint)

**Original issue title:** UI bug (hint)

**Historical status:** Closed before this session.  
**Current status:** Closed.  
**Effect of later work:** Reinforced by Issue 12.

### What this issue represented
A UI-level defect existed and was corrected.

### Why it mattered
Even when backend logic is correct, UI bugs can mislead the operator, hide state, or present inconsistent information.

### What later work changed
Issue 12 later extended UI stability significantly with full null-guard hardening.

### Current interpretation
Issue 8 remains closed and sits upstream of the more comprehensive UI stability work completed later.

---

## Issue 9 — Confluence render hardening

**Original issue title:** Confluence render hardening

**Historical status:** Closed before this session.  
**Current status:** Closed.  
**Effect of later work:** No reversal.

### What this issue represented
Render logic needed hardening around confluence-related outputs.

### Why it mattered
Confluence information is often incomplete or conditional. The UI and runtime state must not fail because one element of confluence is absent or delayed.

### What later work changed
Issue 12 generalized this safety principle beyond confluence and across the UI.

### Current interpretation
Issue 9 remains closed.

---

## Issue 10 — Universe persistence / auto-expanding universe

**Original issue title:** Universe persistence / auto-expanding universe

**Historical status:** Closed before this session.  
**Current status:** Closed.  
**Effect of later work:** No reversal.

### What this issue represented
The system needed symbol persistence independent of whether a user was looking at a symbol in the UI.

### Why it mattered
A live trading / research system cannot depend on UI focus for data collection.  
Persistence must happen in the background.

### What later work changed
Nothing in Issues 11–13 reversed this. The current data pipeline still preserves:
- background logging
- all tracked tickers written via background logger
- no dependency on UI selection

### Current interpretation
Issue 10 remains closed and valid.

---

## Issue 11 — Restore valid 1c ML stack

**Original issue title:** Restore valid 1c ML stack

**Historical status:** Open in baseline, resolved during this broader period.  
**Current status:** Closed.

### Problem definition
The valid 1c model stack for compliant tickers needed to be restored, but promotion and loader-contract issues were preventing correct recovery of active artifacts.

### Root cause
The core problem was not just missing training. It was a promotion deadlock:
- active model sets could be contract-noncompliant
- retrained candidates could be valid
- but promotion logic could still allow stale active metadata to block promotion

This meant a broken active set could remain in place even when a valid replacement existed.

### What changed

#### 11.1 Promotion behavior when active models fail the loader contract
When `verify_active_models.check_artifact_compliance` reported that an active model set was non-compliant, and `--force-retrain` was used:
- `_promotion_existing_prov` was cleared
- `validate_for_promotion(...)` no longer let legacy noncompliant active metadata act as a tie-breaker against the new contract-complete candidate

**Effect:**  
A newly valid candidate could replace a broken active set.

#### 11.2 `--promote-from-manifests`
A new path allowed promotion without retraining:
- load `scheduler_run_manifest.json`
- compare candidate evaluation from:
  - `models/parallel/{ticker}`
  - `models/cascade/{ticker}`
- reapply normal comparison logic
- promote a winning contract-complete candidate into `models/active/{ticker}`

**Why this mattered:**  
It avoided unnecessary multi-hour retrains when the correct artifacts already existed.

#### 11.3 `ED_ML_SCHEDULER_TICKERS`
An optional environment variable allowed targeting specific symbols only.

**Why this mattered:**  
It enabled targeted repair and isolated retraining / promotion work for affected tickers.

### What did NOT change
Issue 11 did **not** relax standards:
- no weakening of `model_contract`
- no weakening of loader metadata requirements
- no bypass of artifact completeness
- no silent acceptance of noncompliant active artifacts

### Impact
Issue 11 restored the valid 1c stack for compliant tickers and resolved the promotion deadlock that could leave legacy/broken artifacts active.

### What it did NOT solve
Issue 11 did **not** solve:
- low-data tickers lacking promotable depth
- multi-horizon ML
- per-horizon dataset independence
- decision-engine alignment

Those remained future or later issues.

### Current interpretation
Issue 11 is closed and forms the basis of the current live 1c model availability.

---

## Issue 12 — Full UI null-guard hardening

**Original issue title:** Full UI null-guard hardening

**Historical status:** Open in baseline, later resolved.  
**Current status:** Closed.

### Problem definition
The UI could crash or render inconsistently when values were absent, partial, or delayed.

### Root cause
The UI and payload layers were still assuming the presence of some values that are not guaranteed during:
- cold starts
- partial model availability
- sparse confluence states
- incomplete decision payloads

### What changed
Issue 12 hardened the UI against:
- null / None values
- missing fields
- incomplete confluence
- absent model outputs

### What the fix did
- protected rendering paths
- allowed the system to remain honest about missing data
- prevented crashes without fabricating replacement data

### Why it mattered
This issue made the system operationally stable without corrupting truthfulness.  
That distinction matters because many systems become “stable” by inventing defaults. This one needed to remain truthful.

### What it did NOT change
Issue 12 was a UI/render resilience issue. It did **not**:
- change model logic
- change trade logic
- create synthetic confidence
- change the source of runtime decision authority

### Impact
The UI can remain up and usable even when portions of the backend state are incomplete or still loading.

### Current interpretation
Issue 12 is closed and remains foundational for stability.

---

## Issue 13 — Decision engine alignment

**Original issue title:** Decision engine alignment

**Historical status:** Open in baseline, fully resolved during this session.  
**Current status:** Closed.

### Original objective
- verify how ML outputs were actually being used
- confirm there were no stale assumptions
- align confidence / signal logic
- remove contradictions between runtime submodules

### Problem definition
Before Issue 13, the system had multiple competing notions of “prediction” and more than one implicit decision truth.

Examples of the misalignment included:
- fusion direction versus empirical 5c dominant direction
- mixed-horizon probability gating
- fragmented confidence semantics
- readiness logic not perfectly aligned with final gated state
- duplicate ML-access paths
- override behavior that could inject synthetic probability structures into decision flow

### Root cause
The system had evolved into a state where:
- empirical context
- model outputs
- fusion outputs
- signal generation
- conviction
- readiness
- gating

were not all driven by a single canonical object.  
That created structural contradiction, even when individual components looked internally reasonable.

### Full fix set

#### 13.1 Canonical decision object
A new `CanonicalForecast` was introduced and made the single forward directional belief for the decision stack.

It contains:
- direction
- probability_up
- probability_down
- probability_flat
- confidence
- provenance

This object became the required source for:
- stack vote
- prediction agreement logic
- probability gates
- readiness direction
- final decision alignment

#### 13.2 Empirical vs forward separation
The predictive layer was refactored so that:
- empirical 5c statistics are historical context
- forward direction is carried by canonical / fusion output
- these two concepts are no longer allowed to masquerade as the same object

**Why this mattered:**  
Historical context can be useful, but it must not pretend to be the active forward trade forecast.

#### 13.3 Stack vote alignment
Prediction-vote logic was moved onto canonical-only semantics.

**Why this mattered:**  
The final runtime stack must vote using one actual forward belief, not a hybrid of historical and forward objects.

#### 13.4 Mixed-horizon gate removal
Trade gates no longer mix:
- one horizon’s directional label
with
- another horizon’s probability values

**Why this mattered:**  
That was mathematically incoherent and violated the spirit of Issue 1 and Issue 3.

#### 13.5 Override safety
`pred_override` was constrained so synthetic probabilities cannot silently enter production trade flow.

**Why this mattered:**  
Debug controls are acceptable only when clearly contained and auditable.

#### 13.6 Single ML inference path
The live stack now uses one inference path:
- `run_base_models_once(...)`

This prevents semantically divergent access paths from competing in runtime logic.

#### 13.7 Readiness alignment
Readiness now uses:
- canonical direction
- post-gate final state
- actual gate result

This prevents readiness from describing a different truth than the final decision state.

#### 13.8 Confidence semantics separation
The system now separates:
- empirical confidence
- forward / fusion confidence
- call conviction

This avoids the prior misuse where a displayed “confidence” label could refer to a different underlying concept depending on context.

#### 13.9 API / logging visibility
Structured decision logging was added through `DECISION_BUNDLE`.

This allows runtime validation of:
- canonical probabilities
- fusion availability
- final signal
- conviction
- gate summary
- size decision
- override state

#### 13.10 Stale-path cleanup
Unused or misleading live-path logic was removed or isolated.

### Final closeout refinement

Issue 13 required a closeout pass because three alignment gaps still remained:
- conviction authority
- explicit fusion-unavailable policy
- API consistency around canonical truth

#### 13.10.1 Conviction authority
`call.conviction` is now seeded from:
- canonical confidence
- canonical dominant-probability margin

Environmental layers may only **downgrade** conviction.

They may not invent higher conviction than the canonical forecast supports.

#### 13.10.2 Fusion-unavailable policy
If canonical provenance is:
- `fusion_unavailable`
- `missing_canonical_fallback`

then directional trades are not allowed.

The system must force `WAIT`.

This is an explicit runtime behavior rule, not just a label.

#### 13.10.3 API truth consistency
Canonical-driven summary fields and provenance were carried outward into runtime state so that the external state matches the real runtime decision truth.

### Impact
Issue 13 is the issue that fully completed runtime decision integrity.

After Issue 13:
- there is one canonical runtime decision object
- there is no horizon mixing in live decision logic
- there is no independent conviction authority
- synthetic probabilities cannot silently drive production decisions
- fusion-unavailable states are non-tradable
- the runtime stack is traceable and auditable

### Current interpretation
Issue 13 is closed and is one of the core pillars of the system’s present integrity.

---

## Issue 14 — Per-horizon training dataset independence

**Historical status:** Open.  
**Current status:** Still open.

### What it means
Training eligibility and dataset handling need to become independent per horizon.

### Why it matters
The future system cannot support true multi-horizon forecasting if horizon data eligibility is coupled.  
One horizon should not be blocked because another horizon is missing or ineligible.

### What it is expected to solve
- horizon-specific training eligibility
- removal of all-horizon dependence for row usage
- cleaner path toward true 5c / 15c / 60c ML

### Why it is next
This issue is the foundation for multi-horizon ML and must be solved before the horizon-expansion issues can be correctly completed.

---

## Issue 15 — ML horizon expansion: 5c

**Historical status:** Open.  
**Current status:** Still open.

### What it means
The system must add true 5c ML, not just historical 5c context.

### Why it matters
The future architecture explicitly intends for 5c to become:
- a real predictive object
- part of the multi-horizon canonical framework

### Dependency
Issue 14 should come first.

---

## Issue 16 — ML horizon expansion: 15c

**Historical status:** Open.  
**Current status:** Still open.

### What it means
The system must add true 15c forward ML.

### Why it matters
15c is part of the future intraday-bias horizon and is essential for a real multi-horizon decision framework.

### Dependency
Issue 14 should come first; Issue 15 likely comes before this.

---

## Issue 17 — ML horizon expansion: 60c

**Historical status:** Open.  
**Current status:** Still open.

### What it means
The system must add true 60c forward ML.

### Why it matters
60c is part of the future session-bias layer and allows the system to distinguish between execution timing and higher-order session directional context.

### Dependency
Issue 14 should come first; 15 and 16 likely precede this.

---

## Issue 18 — Bring low-data tickers (PCG, SMCI) to promotable depth

**Historical status:** Open.  
**Current status:** Still open.

### What it means
Certain tickers still lack sufficient historical depth or qualifying data conditions to support promotion.

### Why it matters
A universal trading system cannot remain biased toward only data-rich symbols if the roadmap intends broad symbol coverage.

### What it is expected to solve
- data sufficiency for low-depth symbols
- promotion viability for currently blocked tickers

---

# 4. DRIFT / RESIDUAL TRACKER

D2. UTC vs session alignment  
D3. Backfill window limitation  
D4. Cold-start data gaps  
D5. Historical continuity gap  
D7. Anchor boundary edge-case  
D8. Feature vs anchor timing mismatch  
D10. Control-state ambiguity  
D12. Training row eligibility tied to all-horizon `outcome_filled`  

These remain tracked residual items and should not be lost even when primary issue work continues.

---

# 5. CURRENT ML SYSTEM STATE

## Current
- All active live models are currently trained on `outcome_1c`
- Artifacts include:
  - `xgb_{ticker}_1c.pkl`
  - `lstm_{ticker}_1c.pt`
  - `transformer_{ticker}_1c.pt`
- Contract enforcement is active and validated
- Loaders require full metadata compliance
- The live runtime uses a single inference truth path
- Fusion currently resolves the active forward directional belief into one canonical runtime object

## Not yet implemented
- 5c ML
- 15c ML
- 60c ML
- Per-horizon training eligibility independence
- Multi-horizon canonical forecasting
- Regime-aware adaptive feature weighting
- Full canonical-probability-only position sizing

---

# 6. CURRENT DATA PIPELINE

## High-level pipeline
`price_bars_1m → snapshots → outcome_* → features → ML → decision engine → UI`

## Persistence state
- All tracked tickers are written to the DB via the background logger
- Persistence no longer depends on whether a ticker is selected in the UI

## Why this matters
A live research / decision system cannot rely on user focus to maintain continuity of data collection.  
Background persistence is therefore a required architectural property, not just a convenience.

---

# 7. FULL ARCHITECTURE — CURRENT RUNTIME SYSTEM

## 7.1 Feature ingestion

### Entry point
`market_state.py`
- `build_market_state(...)`

### Purpose
This is where the live market slice is assembled and the runtime input object is constructed.

### Primary inputs
- prices
- walls / level context
- broader market context
- DB handle / stored state
- session/runtime context

### Output
- `SignalInput`

### Why this matters
`SignalInput` is the common raw/context container for the downstream runtime stack.

---

## 7.2 Feature transformation

### Orchestration
`signals.py`
- `compute_signals(...)`
- `_compute_signals_impl(...)`

### Runtime sub-layers consuming `SignalInput`
- `rules_engine.compute_rules(...)`
- `volatility_regime.classify_volatility_regime(...)`
- `regime_engine.classify_regime(...)`
- `prediction_engine.build_ml_snapshot_for_fusion(...)`

### What this means
Features are **not** all consumed by one universal flat weighted formula at the point of ingestion.

Instead:
- raw/context features are assembled first
- different runtime layers consume the same input differently
- model-ready feature snapshots are then built for ML/fusion use

### Why this matters
This architecture keeps:
- raw market state
- rule interpretation
- regime interpretation
- feature engineering
- model inference

as related but distinct layers.

---

## 7.3 Model layer

### Current live model path
`ml_predict.run_base_models_once(...)`

### Active model families in the live path
- XGBoost
- LSTM
- Transformer

### What happens here
The active model stack runs once per live inference pass and produces the model outputs needed for the downstream combined runtime stack.

### Why this matters
Issue 13 required a single ML inference truth path, so the runtime does not allow duplicated or semantically divergent model access to compete in live decision logic.

---

## 7.4 Simulation layer

### Monte Carlo
`monte_carlo.simulate(...)`

### Role
Monte Carlo contributes forward path / scenario context into the combined runtime stack.

### Why it matters
The system is not purely a classifier stack.  
It also uses simulation context as part of the combined evidence system.

---

## 7.5 Fusion layer

### Bayesian fusion
`bayesian_fusion.fuse(...)`

### Role
Fusion takes the relevant model and contextual evidence and resolves it into a combined forward posterior.

### Output
That posterior is then transformed into:
- `CanonicalForecast`

### Why this matters
The runtime decision system is not allowed to choose among multiple competing forward truths at the decision layer.  
Fusion is the stage that resolves that plurality into one combined forward belief.

---

## 7.6 Decision layer

### Decision object
`CanonicalForecast`

### Current runtime decision rule
All tradable live decisions must derive from:
- canonical direction
- canonical probabilities
- canonical confidence
- canonical provenance

### Decision consumption
The decision layer uses canonical for:
- stack vote
- prediction agreement logic
- gates
- readiness
- conviction seed
- final signal alignment

### Why this matters
This is the answer to “what actually drives the trade?”  
The trade is no longer allowed to come from a hybrid or ambiguous source.

---

## 7.7 Output layer

### Output objects / path
- `SignalOutput`
- `MarketState`
- `server.py`
- JSON / UI
- `DECISION_BUNDLE`

### Why this matters
The outward-facing state must reflect the same runtime truth that the decision engine used.

That is why Issue 13 explicitly carried canonical truth outward into state and logs.

---

## 7.8 Current runtime flow diagram

```text
LIVE MARKET / DB / CONTEXT
    │
    ▼
market_state.py
build_market_state(...)
    │
    ▼
SignalInput
    │
    ├── rules_engine.compute_rules(...)
    │        │
    │        ▼
    │     RulesCard
    │
    ├── volatility_regime.classify_volatility_regime(...)
    │        │
    │        ▼
    │     Volatility Policy
    │
    ├── regime_engine.classify_regime(...)
    │        │
    │        ▼
    │     Regime Payload
    │
    └── prediction_engine.build_ml_snapshot_for_fusion(...)
             │
             ▼
        ML Feature Snapshot
             │
             ▼
        ml_predict.run_base_models_once(...)
             │
             ├── XGBoost
             ├── LSTM
             └── Transformer
             │
             ▼
        Base Model Outputs
             │
             ├── monte_carlo.simulate(...)
             │        │
             │        ▼
             │     Monte Carlo Output
             │
             ▼
        bayesian_fusion.fuse(...)
             │
             ▼
        CanonicalForecast
        (single forward directional truth)
             │
             ├── prediction_engine.compute_prediction(...)
             │        ├── Historical view
             │        └── Forward / canonical view
             │
             ▼
        call_engine.compute_call(...)
             ├── stack vote
             ├── gates
             ├── readiness
             ├── conviction
             └── sizing / risk
             │
             ▼
        SignalOutput
             │
             ▼
        MarketState
             │
             ▼
        server.py / JSON / UI / DECISION_BUNDLE logs
```

---

# 8. WEIGHTING — CURRENT STATE VS FUTURE STATE

## 8.1 Current weighting state

### What is true today
The system does **not** currently use one explicit central weighting table that says:
- feature A gets X weight
- feature B gets Y weight
- dynamically updated every regime step

Instead, weighting currently happens in layered form:

#### Rules layer
Uses thresholds / logic / pattern interpretation

#### Volatility / regime layers
Provide policy and contextual interpretation

#### ML models
Learn internal importance implicitly from training

#### Fusion layer
Combines evidence into a posterior

#### Decision layer
Uses canonical confidence / probability and applies policy downgrades

### Why this matters
Features are not “just dumped in raw with no weighting,” but their weighting is not yet managed by one explicit regime-aware weighting engine either.

The current system is therefore:
- partially weighted
- partially learned
- partially policy-shaped

but **not yet** fully market-state-aware in the way the future design intends.

---

## 8.2 What is NOT yet implemented

The system does **not yet** have a formal mechanism that says, for example:
- in unstable volatility, trust trend continuation less
- near key positioning zones, trust dealer/flow features more
- in compression, trust breakout-related evidence more

This is the missing future enhancement:
> market-state-aware adaptive feature weighting

---

## 8.3 Future weighting direction (confirmed)

The future design should implement:

### Market-state-aware adaptive feature weighting
This means the system should adjust feature-group trust / weighting based on identified market condition.

Examples:
- higher volatility / unstable regime should reduce trust in slow trend continuation and raise caution
- trending / expansion regime should increase trust in continuation-related evidence
- structural liquidity / hedging context should influence how much weight flow / positioning signals carry

### Design principle
This should be:
- learned where possible
- policy-aware where necessary
- not arbitrary static multipliers

### Why this is the correct direction
Not all features matter equally in all market states.  
A serious institutional system should adapt trust based on context.

---

# 9. MODEL ARCHITECTURE CLARIFICATION

## 9.1 Training layer
Parallel and Cascade are currently:
- model training / evaluation / promotion strategies
- not live competing decision engines

## 9.2 Runtime layer
The live app uses:
> a SINGLE COMBINED DECISION STACK

Meaning:
- models run
- Monte Carlo runs
- fusion resolves evidence
- `CanonicalForecast` becomes decision authority
- decision logic consumes that canonical object

There is no competing runtime logic after Issue 13.

---

## 9.3 Meaning of the three terms

### Combined stack
The runtime decision pipeline that turns all available evidence into one trade decision.

### Parallel stack
A training/model-family architecture in which models operate independently and are compared or fused later.

### Cascade stack
A training/model-family architecture in which later stages depend on prior stages in a sequential structure.

---

## 9.4 Promotion rule
Parallel and Cascade candidates may be evaluated and promoted into active.

The combined runtime stack is not itself promoted to parallel or cascade.

Instead:
- trained model families produce candidate artifacts
- promotion selects the winning artifact family
- the live combined runtime stack consumes the active artifacts

### Why this matters
This answers the distinction:
- parallel / cascade = training architecture choices
- combined stack = runtime decision orchestration

---

# 10. DECISION AUTHORITY RULES

## Current runtime decision authority
Only:
- `CanonicalForecast`

## CanonicalForecast governs
- direction
- probabilities
- confidence
- gates
- readiness
- conviction seed
- final signal alignment

## What must NOT act as independent decision authority
- historical empirical 5c context
- confluence counts
- raw rule outputs
- synthetic override probabilities
- duplicate inference-path outputs
- fusion-unavailable fallback posteriors

### Why this matters
The system must know exactly which object owns the trade decision.  
If multiple submodules can each silently become the authority, the system loses integrity.

---

# 11. NON-TRADABLE STATES

If canonical provenance indicates there is no real usable posterior, including:
- `fusion_unavailable`
- `missing_canonical_fallback`

then:
- the system must force `WAIT`
- a directional trade is not tradable

### Why this matters
This prevents the system from turning uncertainty or missingness into false confidence.

---

# 12. CONVICTION MODEL

## Current rule
Conviction is seeded from:
- canonical confidence
- canonical dominant-probability margin

## Environmental modifiers
Conviction may then be downgraded by environment, such as:
- divergence
- event risk
- reversal-prone regime
- volatility caution
- structural transition caution

## Explicit limit
Conviction may **not** exceed what the canonical forecast supports.

### Why this matters
The system is not allowed to become more confident than its own canonical forward posterior justifies.

---

# 13. LOGGING / TRACEABILITY

The system emits structured `DECISION_BUNDLE` logging for validation.

## Logged decision data includes
- canonical probabilities
- canonical provenance
- fusion state
- final signal
- conviction
- gate summary
- size decision
- override application state (if any)

### Why this matters
A serious trading system must be auditable.  
The operator must be able to answer:
- what did the system believe?
- why did it take or reject the trade?
- what object actually drove that belief?

---

# 14. NEXT STEPS (STRICT ORDER)

## Issue 14 — Per-horizon dataset independence
- remove dependence on `outcome_filled` for all horizons
- allow horizon-specific training eligibility
- make horizon data independence real

## Issue 15 — ML horizon expansion: 5c
- add true 5c ML
- not just historical 5c context

## Issue 16 — ML horizon expansion: 15c
- add true 15c forward ML

## Issue 17 — ML horizon expansion: 60c
- add true 60c forward ML

## Issue 18 — Low-data ticker promotion depth
- bring PCG / SMCI and similar low-depth symbols to promotable depth

---

# 15. CONFIRMED FUTURE ARCHITECTURE DECISIONS

## 15.1 Current main prediction object
The current main prediction object remains:

> the canonical forward forecast built from the active model stack

This is the correct present-state design.

---

## 15.2 Transition to multi-horizon canonical forecasting
When multi-horizon ML is built, the system should move from:
- one single canonical directional object

to:
- a **multi-horizon canonical framework**

This decision is confirmed and must remain on the roadmap.

---

## 15.3 Planned horizon labels
Future horizon labeling is confirmed as:

- **Execution bias**
- **Scalp bias**
- **Intraday bias**
- **Session bias**

Mapped as:
- `canonical_1c`   → Execution bias
- `canonical_5c`   → Scalp bias
- `canonical_15c`  → Intraday bias
- `canonical_60c`  → Session bias

---

## 15.4 Future trade design
The future preferred design is:
- one primary trade recommendation based on the user-selected trade horizon
- plus a multi-horizon alignment panel

### Why this matters
Markets can show different directional behavior on different horizons.  
The system should not pretend those are contradictions when they may be normal multi-horizon structure.  
The correct answer is not four chaotic headline calls, but:
- one primary call for the selected trade mode
- one multi-horizon context layer

---

## 15.5 Decision 10.1 — confirmed
Confirmed choice:
- do **not** keep 5c as historical-only context forever
- **do** move to full multi-horizon forward forecasting

Meaning:
- 1c, 5c, 15c, 60c should all become true predictive model objects
- 5c should not remain the main prediction object on its own
- the future state should be multi-horizon canonical, not single-horizon forever

---

## 15.6 Decision 10.2 — confirmed
Confirmed direction:
- continue parallel + cascade evaluation for now
- but eventually converge to one winning architecture
- do not converge prematurely
- make that decision only after later evaluation is mature enough

### Why this matters
The system is still in an architecture-evaluation phase.  
Premature convergence would sacrifice learning before the multi-horizon framework is complete.

---

# 16. FUTURE ENHANCEMENTS / FOLLOW-UP ITEMS TO PRESERVE

## 16.1 Adaptive feature weighting
The system should implement:
> market-state-aware adaptive feature weighting

### Goal
Adjust feature/group importance based on identified market conditions and regime.

### Examples
- higher volatility / instability should change how much trust is given to certain signals
- trending environments should shift weighting differently than reversal-prone or unstable conditions
- liquidity / hedging / structural context should affect trust and weighting

### Design intent
- learned where possible
- policy-aware where needed
- not arbitrary static multipliers

---

## 16.2 Position sizing refinement
Future refinement decision:
- move position sizing to pure canonical-probability / canonical-forecast-based sizing
- not confluence-count-based scaling

This was explicitly chosen and must not be forgotten.

---

## 16.3 Multi-horizon canonical architecture
Future roadmap should explicitly include:
- `canonical_1c`
- `canonical_5c`
- `canonical_15c`
- `canonical_60c`
- horizon-specific trade calls / bias layers
- horizon alignment logic
- user-selectable primary trade horizon
- adaptive weighting by market regime

---

# 17. GUIDING PRINCIPLE FOR THE FUTURE SYSTEM

The system evolves from:
- single canonical forecast
→
- multi-horizon canonical system
→
- adaptive, market-aware predictive engine

BUT ALWAYS:

> ONE unified runtime decision truth

Never:
- multiple competing runtime forecasts
- multiple independent runtime decision engines
- ambiguous decision ownership

---

# 18. STATUS SUMMARY

| Component | Status |
|----------|--------|
| Issue 11 (restore valid 1c ML stack) | Complete |
| Issue 12 (UI null-guard hardening) | Complete |
| Issue 13 (decision engine alignment) | Complete |
| Per-horizon dataset independence | Pending |
| 5c ML | Pending |
| 15c ML | Pending |
| 60c ML | Pending |
| Low-data ticker promotion depth | Pending |
| Adaptive weighting | Planned |
| Pure canonical sizing refinement | Planned |
| Parallel vs cascade convergence | Future decision |
| Multi-horizon canonical framework | Planned |

---

# 19. OPERATIONAL HANDOFF SUMMARY

If a later conversation needs to resume from this file, the most important truths are:

1. Issue 13 is complete
2. `CanonicalForecast` is the current live decision authority
3. The system now uses one combined runtime decision stack
4. Parallel and Cascade are still training/evaluation architectures
5. The next strict issue is Issue 14
6. The future direction is multi-horizon canonical forecasting with adaptive weighting and eventual architecture convergence

---

# 20. END OF MASTER DOCUMENT


====================================================================================================
# SOURCE DOCUMENT: Ed_Trading_System_MASTER_v9_UPDATED.md
**Date:** 2026-04-02 | **Role:** MASTER SPEC v9 | **Original size:** 62,741 bytes
====================================================================================================

# ED INSTITUTIONAL PREDICTIVE TRADING ENGINE
## MASTER SPEC + LIVE ISSUE TRACKERS (AUTHORITATIVE MASTER — v8)

---

# 0. BASELINE SOURCE FILE PRESERVATION

This master document uses the original file provided at the start of this session as the project baseline.

## Original baseline file text

```markdown
# ED INSTITUTIONAL PREDICTIVE TRADING ENGINE
## MASTER SPEC + LIVE ISSUE TRACKERS (UPDATED AFTER ISSUE 11)

---

# SYSTEM STATE (CURRENT)

The system now has:
- Correct bar-based horizons
- Canonical anchor
- Honest missingness (no synthetic probabilities)
- Auto-expanding universe with background persistence
- Fully hardened UI (no runtime crashes)
- Valid 1c ML stack restored for compliant tickers

Limitations:
- Some tickers (PCG, SMCI) blocked by insufficient data for promotion
- Multi-horizon ML not yet implemented

---

# PRIMARY ISSUE TRACKER

## CLOSED
1. Timeframe integrity  
2. Remove non-target horizons  
3. Universal horizon standardization  
4. Anchor standardization  
5. Fallback policy formalization  
6. Internal decision integrity  
7. Feature/schema parity / model enforcement  
8. UI bug (hint)  
9. Confluence render hardening  
10. Universe persistence / auto-expanding universe  
11. Restore valid 1c ML stack  
12. Full UI null-guard hardening  

## OPEN
13. Decision engine alignment  
14. Per-horizon training dataset independence  
15. ML horizon expansion: 5c  
16. ML horizon expansion: 15c  
17. ML horizon expansion: 60c  
18. Bring low-data tickers (PCG, SMCI) to promotable depth  

---

# DRIFT / RESIDUAL TRACKER

D2. UTC vs session alignment  
D3. Backfill window limitation  
D4. Cold-start data gaps  
D5. Historical continuity gap  
D7. Anchor boundary edge-case  
D8. Feature vs anchor timing mismatch  
D10. Control-state ambiguity  
D12. Training row eligibility tied to all-horizon outcome_filled  

---

# ML SYSTEM STATE

## Current
- All models trained on outcome_1c
- Artifacts:
  - xgb_{ticker}_1c.pkl
  - lstm_{ticker}_1c.pt
  - transformer_{ticker}_1c.pt
- Contract enforcement active and validated
- Loaders require full metadata compliance

## Not yet implemented
- 5c ML
- 15c ML
- 60c ML
- Per-horizon training eligibility

---

# DATA PIPELINE

price_bars_1m → snapshots → outcome_* → features → ML → decision engine → UI

Persistence:
- All tracked tickers now written to DB via background logger
- No dependency on UI selection

---

# NEXT STEPS (STRICT ORDER)

## Issue 13 — Decision Engine Alignment
- Verify how ML outputs are used
- Confirm no stale assumptions
- Align confidence / signal logic

## Issue 14 — Per-horizon dataset independence
- Remove dependence on outcome_filled for all horizons
- Allow horizon-specific training eligibility

## Issue 15–17 — Multi-horizon ML
- Implement 5c, then 15c, then 60c

---

# GUARANTEES

The system enforces:
- No fake data
- No hidden fallbacks
- No contract violations
- No UI crashes
- No stale model usage

---

# END

```

The remainder of this document preserves that baseline and layers in all validated updates, issue history, architecture clarification, confirmed decisions, and future roadmap items discussed and agreed during this session.

---

# 1. SYSTEM STATE (CURRENT)

The system now has:
- Correct bar-based horizons
- Canonical anchor
- Honest missingness (no synthetic probabilities in production decision flow)
- Auto-expanding universe with background persistence
- Fully hardened UI (no runtime crashes from missing / null values)
- Valid 1c ML stack restored for compliant tickers
- CanonicalForecast as the single runtime decision authority
- Single live inference path for the active runtime stack
- Explicit decision trace logging through `DECISION_BUNDLE`
- Fusion-unavailable states explicitly forced to `WAIT`
- Conviction bounded by canonical forward probabilities / confidence, not allowed to exceed canonical forecast strength
- Per-horizon training dataset independence implemented for ML eligibility
- True 5c ML training, artifact generation, evaluation, manifesting, and promotion lane support implemented
- Separate non-1c active model roots and architecture-state files for training/evaluation isolation
- Horizon-aware cache keys, dataset fingerprints, artifact names, metadata, and scheduler paths for 5c

## Limitations
- Some tickers (notably PCG and SMCI) remain blocked by insufficient data for promotion depth
- 15c ML is not yet implemented
- 60c ML is not yet implemented
- `outcome_15c` and `outcome_60c` were observed as unpopulated in current proof runs, so label/backfill validation is required before Issues 16 and 17 can responsibly proceed
- Multi-horizon canonical forecasting is not yet implemented
- Market-state-aware adaptive feature weighting is not yet implemented
- Position sizing is not yet fully derived purely from canonical probabilities
- Parallel vs cascade training architecture has not yet been converged to one winner
- Live runtime decisioning remains intentionally 1c-default; 5c currently exists as a true ML training/evaluation/promotion lane, not yet as a live runtime decision authority

## Current operating truth
The system is no longer allowed to run with multiple competing runtime decision truths.  
The runtime stack must resolve to one canonical decision object before a trade decision is produced.

---

# 2. PRIMARY ISSUE TRACKER

## CLOSED

1. Timeframe integrity  
2. Remove non-target horizons  
3. Universal horizon standardization  
4. Anchor standardization  
5. Fallback policy formalization  
6. Internal decision integrity  
7. Feature/schema parity / model enforcement  
8. UI bug (hint)  
9. Confluence render hardening  
10. Universe persistence / auto-expanding universe  
11. Restore valid 1c ML stack  
12. Full UI null-guard hardening  
13. Decision engine alignment  
14. Per-horizon training dataset independence  

## OPEN

15. ML horizon expansion: 5c  
16. ML horizon expansion: 15c  
17. ML horizon expansion: 60c  
18. Bring low-data tickers (PCG, SMCI) to promotable depth  

---
# 3. ISSUE HISTORY — COMPLETE RECORD

## Issue 1 — Timeframe integrity

**Original issue title:** Timeframe integrity

**Historical status:** Closed before this session.  
**Current status:** Still closed.  
**Effect of later work:** No reversal. Issue 13 reinforced the importance of strict timeframe integrity by eliminating mixed-horizon runtime decision behavior.

### What this issue represented
This issue established that the system needed clean timeframe handling and could not tolerate ambiguous or inconsistent horizon semantics.

### Why it mattered
Without timeframe integrity:
- labels become unreliable
- training targets become ambiguous
- decision logic can mix incompatible horizons
- evaluation becomes misleading

### What later work changed
Later work, especially Issue 13, did **not** reopen Issue 1, but it did make its importance more explicit by removing runtime horizon mixing and insisting that live decisions be derived from one coherent forecast object rather than mixed horizon fragments.

### Current interpretation
Issue 1 remains closed and structurally valid.

---

## Issue 2 — Remove non-target horizons

**Original issue title:** Remove non-target horizons

**Historical status:** Closed before this session.  
**Current status:** Still closed.  
**Effect of later work:** No reversal.

### What this issue represented
This issue removed horizon handling that was outside the intended target design.

### Why it mattered
The system needed to stop reasoning over horizons that were not part of the active target framework, because that creates noise, inconsistent UI semantics, and invalid downstream assumptions.

### What later work changed
Issue 13 later eliminated a different but related problem: not just non-target horizon presence, but mixed-horizon decision usage. That means Issue 2 remains correct and closed, while Issue 13 completed the runtime decision integrity that Issue 2 conceptually pointed toward.

### Current interpretation
Issue 2 remains closed and valid.

---

## Issue 3 — Universal horizon standardization

**Original issue title:** Universal horizon standardization

**Historical status:** Closed before this session.  
**Current status:** Still closed.  
**Effect of later work:** No reversal. Future multi-horizon expansion will build on this.

### What this issue represented
The system needed one consistent way to name, interpret, and use horizons throughout training, evaluation, UI, and decision logic.

### Why it mattered
Without universal standardization:
- models and UI can refer to different meanings for the same horizon
- gates can accidentally compare incompatible objects
- logs become unreliable

### What later work changed
Issue 13 exposed that even with closed standardization work, runtime decision logic could still accidentally mix horizon-derived quantities. That later issue did not invalidate Issue 3; it completed the enforcement of its intent.

### Current interpretation
Issue 3 remains closed and is foundational for the later future state of:
- `canonical_1c`
- `canonical_5c`
- `canonical_15c`
- `canonical_60c`

---

## Issue 4 — Anchor standardization

**Original issue title:** Anchor standardization

**Historical status:** Closed before this session.  
**Current status:** Still closed.  
**Effect of later work:** No reversal.

### What this issue represented
The system needed a canonical anchor convention for runtime and training reference points.

### Why it mattered
Without anchor standardization:
- feature timing can drift
- labels can misalign with the intended reference
- downstream signals can appear correct while being built on inconsistent temporal anchoring

### What later work changed
The residual tracker still contains:
- D7. Anchor boundary edge-case
- D8. Feature vs anchor timing mismatch

This does **not** reopen Issue 4. It means the broad standardization is complete, while edge cases and residual drift remain tracked.

### Current interpretation
Issue 4 remains closed; residual anchor-related items remain under drift tracking, not as a reopened core issue.

---

## Issue 5 — Fallback policy formalization

**Original issue title:** Fallback policy formalization

**Historical status:** Closed before this session.  
**Current status:** Closed and materially reinforced by Issue 13.

### What this issue represented
The system needed explicit rules for what happens when preferred inputs or model states are unavailable.

### Why it mattered
Unformalized fallback behavior is dangerous because it can:
- silently fabricate confidence
- hide missingness
- create misleading trade bias
- weaken trust in the system

### What later work changed
Issue 13 materially tightened Issue 5. The system now enforces:
- no synthetic probabilities in production decision flow
- explicit `WAIT` when fusion/canonical posterior is unavailable
- constraints on override behavior so fake probabilities cannot silently influence live decisions

### Current interpretation
Issue 5 remains closed, but its operational meaning is now stricter than before:
- fallback may protect rendering or continuity
- fallback may **not** invent tradable confidence or direction

---

## Issue 6 — Internal decision integrity

**Original issue title:** Internal decision integrity

**Historical status:** Closed before this session.  
**Current status:** Closed and fully finalized by Issue 13.

### What this issue represented
The system needed its internal decisions to be logically coherent and not allow contradictory states across submodules.

### Why it mattered
A trading system cannot claim integrity if:
- one layer says bullish and another silently governs bearish
- confidence and direction come from different uncoordinated truths
- the UI and runtime logic describe different states

### What later work changed
Issue 13 is the full realization of Issue 6. It:
- introduced `CanonicalForecast`
- removed competing prediction truths
- aligned readiness, gating, conviction, and signal logic
- enforced one runtime decision authority

### Current interpretation
Issue 6 is not merely closed; it is fully completed by the Issue 13 alignment work.

---

## Issue 7 — Feature/schema parity / model enforcement

**Original issue title:** Feature/schema parity / model enforcement

**Historical status:** Closed before this session.  
**Current status:** Closed.  
**Effect of later work:** Reinforced by Issue 11 and Issue 13.

### What this issue represented
The system needed strict agreement between:
- feature generation
- expected model schema
- loader assumptions
- live inference expectations

### Why it mattered
Without schema parity:
- live inference can silently break
- active models can become unusable
- evaluation and deployment diverge

### What later work changed
Issue 11 reinforced this through strict loader compliance and model contract enforcement.  
Issue 13 reinforced it again by forcing a single runtime inference path and removing duplicate semantic access paths.

### Current interpretation
Issue 7 remains closed and continues to govern the strictness of live model loading and inference compatibility.

---

## Issue 8 — UI bug (hint)

**Original issue title:** UI bug (hint)

**Historical status:** Closed before this session.  
**Current status:** Closed.  
**Effect of later work:** Reinforced by Issue 12.

### What this issue represented
A UI-level defect existed and was corrected.

### Why it mattered
Even when backend logic is correct, UI bugs can mislead the operator, hide state, or present inconsistent information.

### What later work changed
Issue 12 later extended UI stability significantly with full null-guard hardening.

### Current interpretation
Issue 8 remains closed and sits upstream of the more comprehensive UI stability work completed later.

---

## Issue 9 — Confluence render hardening

**Original issue title:** Confluence render hardening

**Historical status:** Closed before this session.  
**Current status:** Closed.  
**Effect of later work:** No reversal.

### What this issue represented
Render logic needed hardening around confluence-related outputs.

### Why it mattered
Confluence information is often incomplete or conditional. The UI and runtime state must not fail because one element of confluence is absent or delayed.

### What later work changed
Issue 12 generalized this safety principle beyond confluence and across the UI.

### Current interpretation
Issue 9 remains closed.

---

## Issue 10 — Universe persistence / auto-expanding universe

**Original issue title:** Universe persistence / auto-expanding universe

**Historical status:** Closed before this session.  
**Current status:** Closed.  
**Effect of later work:** No reversal.

### What this issue represented
The system needed symbol persistence independent of whether a user was looking at a symbol in the UI.

### Why it mattered
A live trading / research system cannot depend on UI focus for data collection.  
Persistence must happen in the background.

### What later work changed
Nothing in Issues 11–13 reversed this. The current data pipeline still preserves:
- background logging
- all tracked tickers written via background logger
- no dependency on UI selection

### Current interpretation
Issue 10 remains closed and valid.

---

## Issue 11 — Restore valid 1c ML stack

**Original issue title:** Restore valid 1c ML stack

**Historical status:** Open in baseline, resolved during this broader period.  
**Current status:** Closed.

### Problem definition
The valid 1c model stack for compliant tickers needed to be restored, but promotion and loader-contract issues were preventing correct recovery of active artifacts.

### Root cause
The core problem was not just missing training. It was a promotion deadlock:
- active model sets could be contract-noncompliant
- retrained candidates could be valid
- but promotion logic could still allow stale active metadata to block promotion

This meant a broken active set could remain in place even when a valid replacement existed.

### What changed

#### 11.1 Promotion behavior when active models fail the loader contract
When `verify_active_models.check_artifact_compliance` reported that an active model set was non-compliant, and `--force-retrain` was used:
- `_promotion_existing_prov` was cleared
- `validate_for_promotion(...)` no longer let legacy noncompliant active metadata act as a tie-breaker against the new contract-complete candidate

**Effect:**  
A newly valid candidate could replace a broken active set.

#### 11.2 `--promote-from-manifests`
A new path allowed promotion without retraining:
- load `scheduler_run_manifest.json`
- compare candidate evaluation from:
  - `models/parallel/{ticker}`
  - `models/cascade/{ticker}`
- reapply normal comparison logic
- promote a winning contract-complete candidate into `models/active/{ticker}`

**Why this mattered:**  
It avoided unnecessary multi-hour retrains when the correct artifacts already existed.

#### 11.3 `ED_ML_SCHEDULER_TICKERS`
An optional environment variable allowed targeting specific symbols only.

**Why this mattered:**  
It enabled targeted repair and isolated retraining / promotion work for affected tickers.

### What did NOT change
Issue 11 did **not** relax standards:
- no weakening of `model_contract`
- no weakening of loader metadata requirements
- no bypass of artifact completeness
- no silent acceptance of noncompliant active artifacts

### Impact
Issue 11 restored the valid 1c stack for compliant tickers and resolved the promotion deadlock that could leave legacy/broken artifacts active.

### What it did NOT solve
Issue 11 did **not** solve:
- low-data tickers lacking promotable depth
- multi-horizon ML
- per-horizon dataset independence
- decision-engine alignment

Those remained future or later issues.

### Current interpretation
Issue 11 is closed and forms the basis of the current live 1c model availability.

---

## Issue 12 — Full UI null-guard hardening

**Original issue title:** Full UI null-guard hardening

**Historical status:** Open in baseline, later resolved.  
**Current status:** Closed.

### Problem definition
The UI could crash or render inconsistently when values were absent, partial, or delayed.

### Root cause
The UI and payload layers were still assuming the presence of some values that are not guaranteed during:
- cold starts
- partial model availability
- sparse confluence states
- incomplete decision payloads

### What changed
Issue 12 hardened the UI against:
- null / None values
- missing fields
- incomplete confluence
- absent model outputs

### What the fix did
- protected rendering paths
- allowed the system to remain honest about missing data
- prevented crashes without fabricating replacement data

### Why it mattered
This issue made the system operationally stable without corrupting truthfulness.  
That distinction matters because many systems become “stable” by inventing defaults. This one needed to remain truthful.

### What it did NOT change
Issue 12 was a UI/render resilience issue. It did **not**:
- change model logic
- change trade logic
- create synthetic confidence
- change the source of runtime decision authority

### Impact
The UI can remain up and usable even when portions of the backend state are incomplete or still loading.

### Current interpretation
Issue 12 is closed and remains foundational for stability.

---

## Issue 13 — Decision engine alignment

**Original issue title:** Decision engine alignment

**Historical status:** Open in baseline, fully resolved during this session.  
**Current status:** Closed.

### Original objective
- verify how ML outputs were actually being used
- confirm there were no stale assumptions
- align confidence / signal logic
- remove contradictions between runtime submodules

### Problem definition
Before Issue 13, the system had multiple competing notions of “prediction” and more than one implicit decision truth.

Examples of the misalignment included:
- fusion direction versus empirical 5c dominant direction
- mixed-horizon probability gating
- fragmented confidence semantics
- readiness logic not perfectly aligned with final gated state
- duplicate ML-access paths
- override behavior that could inject synthetic probability structures into decision flow

### Root cause
The system had evolved into a state where:
- empirical context
- model outputs
- fusion outputs
- signal generation
- conviction
- readiness
- gating

were not all driven by a single canonical object.  
That created structural contradiction, even when individual components looked internally reasonable.

### Full fix set

#### 13.1 Canonical decision object
A new `CanonicalForecast` was introduced and made the single forward directional belief for the decision stack.

It contains:
- direction
- probability_up
- probability_down
- probability_flat
- confidence
- provenance

This object became the required source for:
- stack vote
- prediction agreement logic
- probability gates
- readiness direction
- final decision alignment

#### 13.2 Empirical vs forward separation
The predictive layer was refactored so that:
- empirical 5c statistics are historical context
- forward direction is carried by canonical / fusion output
- these two concepts are no longer allowed to masquerade as the same object

**Why this mattered:**  
Historical context can be useful, but it must not pretend to be the active forward trade forecast.

#### 13.3 Stack vote alignment
Prediction-vote logic was moved onto canonical-only semantics.

**Why this mattered:**  
The final runtime stack must vote using one actual forward belief, not a hybrid of historical and forward objects.

#### 13.4 Mixed-horizon gate removal
Trade gates no longer mix:
- one horizon’s directional label
with
- another horizon’s probability values

**Why this mattered:**  
That was mathematically incoherent and violated the spirit of Issue 1 and Issue 3.

#### 13.5 Override safety
`pred_override` was constrained so synthetic probabilities cannot silently enter production trade flow.

**Why this mattered:**  
Debug controls are acceptable only when clearly contained and auditable.

#### 13.6 Single ML inference path
The live stack now uses one inference path:
- `run_base_models_once(...)`

This prevents semantically divergent access paths from competing in runtime logic.

#### 13.7 Readiness alignment
Readiness now uses:
- canonical direction
- post-gate final state
- actual gate result

This prevents readiness from describing a different truth than the final decision state.

#### 13.8 Confidence semantics separation
The system now separates:
- empirical confidence
- forward / fusion confidence
- call conviction

This avoids the prior misuse where a displayed “confidence” label could refer to a different underlying concept depending on context.

#### 13.9 API / logging visibility
Structured decision logging was added through `DECISION_BUNDLE`.

This allows runtime validation of:
- canonical probabilities
- fusion availability
- final signal
- conviction
- gate summary
- size decision
- override state

#### 13.10 Stale-path cleanup
Unused or misleading live-path logic was removed or isolated.

### Final closeout refinement

Issue 13 required a closeout pass because three alignment gaps still remained:
- conviction authority
- explicit fusion-unavailable policy
- API consistency around canonical truth

#### 13.10.1 Conviction authority
`call.conviction` is now seeded from:
- canonical confidence
- canonical dominant-probability margin

Environmental layers may only **downgrade** conviction.

They may not invent higher conviction than the canonical forecast supports.

#### 13.10.2 Fusion-unavailable policy
If canonical provenance is:
- `fusion_unavailable`
- `missing_canonical_fallback`

then directional trades are not allowed.

The system must force `WAIT`.

This is an explicit runtime behavior rule, not just a label.

#### 13.10.3 API truth consistency
Canonical-driven summary fields and provenance were carried outward into runtime state so that the external state matches the real runtime decision truth.

### Impact
Issue 13 is the issue that fully completed runtime decision integrity.

After Issue 13:
- there is one canonical runtime decision object
- there is no horizon mixing in live decision logic
- there is no independent conviction authority
- synthetic probabilities cannot silently drive production decisions
- fusion-unavailable states are non-tradable
- the runtime stack is traceable and auditable

### Current interpretation
Issue 13 is closed and is one of the core pillars of the system’s present integrity.

---

## Issue 14 — Per-horizon training dataset independence

**Historical status:** Open.  
**Current status:** Closed.

### Original objective
- remove dependence on all-horizon completeness for training eligibility
- allow each target horizon to form its own valid dataset
- make future 5c / 15c / 60c ML structurally possible

### Problem definition
Before Issue 14, the training pipeline was claiming horizon support at the label level while still coupling training eligibility to an all-horizons-complete condition.

A row could contain a valid `outcome_1c` or `outcome_5c`, but still be excluded from training because a longer-horizon label such as `outcome_60c` was still missing.  
That made the effective dataset logic dishonest relative to the intended architecture.

### Root cause
The root coupling came from the use of `outcome_filled` in ML eligibility logic.

In `db.fill_outcomes`, `outcome_filled = 1` means:
- all bar-spec horizons in `OUTCOME_BAR_SPECS` are present on the row

That is a backfill-completeness flag, not a per-horizon training-eligibility flag.

The training path, however, was using logic equivalent to:

```sql
outcome_filled = 1 AND outcome_1c IS NOT NULL
```

That meant:
- a row with valid `outcome_1c` but missing `outcome_60c` was excluded from 1c training
- a row with valid `outcome_5c` but missing longer horizons was excluded from horizon-specific training eligibility
- shorter-horizon model eligibility was implicitly tied to longer-horizon completion

This was the exact cross-horizon coupling captured in residual item `D12`.

### What changed

#### 14.1 New per-label training eligibility contract
A new label-specific SQL contract was introduced:

- `training_label_where_clause(label_column)`

Its meaning is:
- one label column in
- one `IS NOT NULL` predicate out
- validated against the allowed horizon outcome columns

Examples:
- `training_label_where_clause("outcome_1c")` → `outcome_1c IS NOT NULL`
- `training_label_where_clause("outcome_5c")` → `outcome_5c IS NOT NULL`

This formalized the correct rule:

> a row is valid for horizon H if and only if its label column for H is present and valid

#### 14.2 Legacy alias corrected
`outcome_where_clause()` was retained only as a legacy alias for the default canonical training lane and now resolves to:

- `training_label_where_clause("outcome_1c")`

It no longer depends on `outcome_filled`.

#### 14.3 Data loader updates
The training/data path was updated so that the following no longer use all-horizon completeness as the gate:

- `ml_train.py` data loading
- `lstm_data.py` extraction logic
- LSTM ticker discovery
- training/evaluation support utilities
- readiness/audit queries that should reflect trainability by label rather than total row completeness

#### 14.4 Sequence path confirmation
LSTM and Transformer sequence generation were validated and confirmed to already use:

- the target horizon on the current bar of the sequence window
- no other horizon columns as gates
- no `outcome_filled` dependency in the sequence construction path

The bug in sequence-related behavior was therefore not the windowing logic itself, but the upstream row-fetch predicate that incorrectly excluded otherwise valid rows.

#### 14.5 Diagnostics and tests
Tests were added to prove:
- the SQL fragment is per-label
- unknown labels are rejected
- row counts differ by horizon when they should
- sequence loaders are not referencing `outcome_filled`
- LSTM/Transformer source rows are filtered only by the target label column

### Execution proof
Issue 14 was not accepted on theory alone. It was supported by direct proof:

- legacy 1c eligibility (`outcome_filled = 1 AND outcome_1c IS NOT NULL`) produced fewer rows than the corrected 1c predicate (`outcome_1c IS NOT NULL`)
- the proof run on the workspace DB showed:

  - legacy 1c rows: 10,409
  - corrected 1c rows: 10,698
  - `outcome_5c IS NOT NULL`: 11,295
  - `outcome_15c IS NOT NULL`: 0
  - `outcome_60c IS NOT NULL`: 0

This proved three things at once:

1. the old filter was excluding valid 1c rows  
2. horizon datasets now genuinely differ by horizon  
3. 15c and 60c absence is currently a label/data-state issue, not a dataset-coupling issue

### Impact
After Issue 14:
- horizon eligibility is independent
- training no longer depends on all-horizon backfill completeness
- 1c training uses more valid rows than before
- the system now has a truthful foundation for true multi-horizon ML

### What Issue 14 did NOT do
Issue 14 did **not**:
- add 5c, 15c, or 60c trained models by itself
- change live runtime decision authority
- solve missing 15c / 60c label population
- create multi-horizon canonical forecasting

### Current interpretation
Issue 14 is closed and is the required data-pipeline foundation for all later multi-horizon ML work.

---

## Issue 15 — ML horizon expansion: 5c

**Historical status:** Open.  
**Current status:** Open — functionally implemented, architecturally closeout pending.

### Original objective
- add true 5c ML
- make 5c a real trained/evaluated artifact lane
- do so without breaking 1c
- make the implementation compatible with later 15c / 60c expansion and eventual multi-horizon canonical forecasting

### Problem definition
Before Issue 15, the system had only one real ML lane:

- `outcome_1c`
- `*_1c` artifacts
- 1c-centric scheduler/evaluation/reporting assumptions

The codebase could store `outcome_5c`, but 5c was not a true trained horizon in the ML stack.  
That meant the project had label-level theoretical horizon breadth but only one actual trained predictive horizon.

### Root cause
The 1c-only limitation was spread across multiple layers:

- label and SQL selection were 1c-default or hardcoded
- artifact naming was 1c-specific
- metadata and manifests did not carry horizon identity cleanly
- scheduler/caching/fingerprinting were effectively 1c-based
- evaluation always scored against `outcome_1c`
- promotion/reporting paths assumed the active lane was 1c
- inference helpers defaulted to 1c artifacts

This was not one bug.  
It was a system-wide horizon-hardcoding problem.

### What changed

#### 15.1 Horizon slug propagation
A true horizon identity was propagated across the ML stack using a horizon slug concept.

The design now carries horizon identity through:
- target/label selection
- dataset filtering
- cache keys
- dataset fingerprints
- artifact basenames
- manifests
- evaluation labels
- promotion roots
- architecture-state files for non-1c lanes

#### 15.2 Horizon utility alignment
`ml_horizon.py` became the shared horizon contract layer, providing a single mapping for:
- horizon slug
- target outcome column
- target definition text
- promotion naming behavior

This is the correct abstraction because it stops each downstream module from inventing its own horizon semantics.

#### 15.3 True 5c artifact lane
The system now supports true 5c artifact generation, including paths consistent with:
- `xgb_{ticker}_5c.pkl`
- `lstm_{ticker}_5c.pt`
- `transformer_{ticker}_5c.pt`

Metadata and provenance now identify 5c correctly through:
- target column
- target definition
- horizon slug

#### 15.4 Scheduler and promotion separation
The scheduler gained horizon-aware execution and promotion behavior.

Key changes include:
- non-1c active roots such as `models/active_5c/`
- non-1c architecture state files such as `arch_state_5c.json`
- manifest horizon-awareness so 1c and 5c runs cannot be confused or skipped against each other
- horizon-aware cache/fingerprint behavior so 5c work does not masquerade as 1c work

This matters because a functional 5c lane that overwrites or contaminates the 1c lane would be architecturally unacceptable.

#### 15.5 Evaluation correctness
Evaluation paths were updated so they score against the correct target column rather than always reading `row["outcome_1c"]`.

The evaluation stack now:
- builds `y_true` from the horizon-aligned target column
- sets inference horizon context so 5c evaluation loads 5c artifacts
- preserves separation between 1c and 5c metrics

#### 15.6 Inference-context isolation for evaluation
A horizon-aware inference context mechanism was added so the scheduler/evaluation path can load 5c artifacts during evaluation without redefining the live runtime’s current 1c-default lane.

This is the correct design for current project phase because:
- training/evaluation can become multi-horizon
- live runtime can remain 1c-default until explicit product/runtime design changes are made

#### 15.7 Training cache / manifest repair
A corrupted `build_manifest` in `training_cache.py` was repaired and an `ml_horizon_suffix` field was added.

This is important because a broken or horizon-blind manifest layer would undermine reproducibility and could cause incorrect cache reuse across horizons.

### Execution proof
Issue 15 was supported by direct proof rather than design intent alone.

A real 5c training run produced:
- `outcome_5c` class distribution:
  - `flat`: 561
  - `down`: 300
  - `up`: 266
- XGBoost training on SPY with:
  - 1,127 rows
  - horizon `5c`
  - target `outcome_5c`
- saved artifact:
  - `xgb_SPY_5c.pkl`
- saved metadata/provenance including:
  - `target_column: outcome_5c`
  - `target_definition: outcome_5c ~5 min ahead (5×1m bars)`

The test suite also advanced from the Issue 14 proof state and reported:
- `74 passed`

That matters because it confirms:
- 1c did not regress
- 5c did not exist only on paper
- scheduler/evaluation/training paths remained executable

### Impact
After Issue 15 functional implementation:
- the system can build a 5c dataset
- the system can train 5c XGBoost/LSTM/Transformer lanes
- the system can save 5c artifacts with correct naming and provenance
- the system can evaluate against `outcome_5c`
- the system can keep 1c and 5c artifact lanes separate
- the system is materially closer to true multi-horizon ML

### Why Issue 15 is not yet marked closed
Issue 15 is not yet being treated as fully closed because the session also established a stricter engineering standard:

> functional implementation is not enough if shared ML infrastructure still carries non-deferred 1c hardcoding where proper horizon parameterization should now exist

The current evidence indicates:
- 5c works end-to-end in training/evaluation/promotion lanes
- but some paths remain explicitly 1c-default or legacy-hardcoded
- those remaining paths must be classified cleanly as either:
  - intentionally 1c-only by current product/runtime design
  - or still requiring generalization to satisfy a truly clean Issue 15 closeout

### What remains to be proven/closed out for Issue 15
The required closeout pass is:
- search all remaining 1c hardcoding in shared ML infrastructure
- classify each occurrence as:
  - already correct
  - must generalize now
  - intentionally deferred by product/runtime design
- eliminate all non-deferred 1c hardcoding
- prove both 1c and 5c still work after the cleanup pass

### Current interpretation
Issue 15 is no longer “not started.”  
It is now:

- functionally implemented
- materially validated
- not yet architecturally closed

That distinction must be preserved so later work does not pretend the codebase is cleaner than it really is.

---

## Issue 16 — ML horizon expansion: 15c

**Historical status:** Open.  
**Current status:** Open — blocked pending label availability validation.

### What it means
The system must add true 15c forward ML.

### Why it matters
15c is the intended intraday-bias horizon and is necessary for a real multi-horizon decision framework.

### Current blocker
The Issue 14 proof run showed:
- `outcome_15c IS NOT NULL`: 0

That means the immediate blocker is not architecture for horizon-specific training.  
That blocker has been removed.  
The blocker is current 15c label availability.

### Dependency
Issue 15 closeout should be completed first, and 15c label/backfill integrity must be proven before implementation proceeds.

---

## Issue 17 — ML horizon expansion: 60c

**Historical status:** Open.  
**Current status:** Open — blocked pending label availability validation.

### What it means
The system must add true 60c forward ML.

### Why it matters
60c is the intended session-bias horizon and is necessary for separating execution timing from broader session directional structure.

### Current blocker
The Issue 14 proof run showed:
- `outcome_60c IS NOT NULL`: 0

That means the immediate blocker is current 60c label availability, not the concept of horizon-specific training itself.

### Dependency
Issue 15 closeout should be completed first, and 60c label/backfill integrity must be proven before implementation proceeds.

---

## Issue 18 — Bring low-data tickers (PCG, SMCI) to promotable depth

**Historical status:** Open.  
**Current status:** Still open.

### What it means
Certain tickers still lack sufficient historical depth or qualifying data conditions to support promotion.

### Why it matters
A universal trading system cannot remain biased toward only data-rich symbols if the roadmap intends broad symbol coverage.

### What it is expected to solve
- data sufficiency for low-depth symbols
- promotion viability for currently blocked tickers
- consistency of model availability across a broader tradable universe

### Dependency
This issue remains downstream of the core horizon-work foundation, but it should not be forgotten while multi-horizon buildout continues.

---

# 4. DRIFT / RESIDUAL TRACKER


D2. UTC vs session alignment  
D3. Backfill window limitation  
D4. Cold-start data gaps  
D5. Historical continuity gap  
D7. Anchor boundary edge-case  
D8. Feature vs anchor timing mismatch  
D10. Control-state ambiguity  

## Resolved residual item
- D12. Training row eligibility tied to all-horizon `outcome_filled` — resolved by Issue 14

These residual items remain tracked and should not be lost even when primary issue work continues.

---

# 5. CURRENT ML SYSTEM STATE

## Current
- All active live runtime models are still currently anchored to the `outcome_1c` lane
- Active runtime artifacts include:
  - `xgb_{ticker}_1c.pkl`
  - `lstm_{ticker}_1c.pt`
  - `transformer_{ticker}_1c.pt`
- Contract enforcement is active and validated
- Loaders require full metadata compliance
- The live runtime uses a single inference truth path
- Fusion currently resolves the active forward directional belief into one canonical runtime object
- Per-horizon training eligibility is now independent by label column
- A true 5c ML lane now exists for training/evaluation/promotion, including horizon-specific:
  - dataset filtering
  - fingerprints
  - cache keys
  - manifests
  - artifact names
  - evaluation labels
  - promotion roots
  - architecture-state files

## Current 5c proof state
- Real 5c XGBoost training was demonstrated on SPY using `outcome_5c`
- Proof run showed 1,127 rows used for that training example
- Artifact proof included `xgb_SPY_5c.pkl`
- Metadata/provenance proof included `target_column: outcome_5c`

## Not yet implemented
- Issue 15 architectural closeout pass
- 15c ML
- 60c ML
- Multi-horizon canonical forecasting
- Regime-aware adaptive feature weighting
- Full canonical-probability-only position sizing
- Live multi-horizon runtime selection / routing
- Horizon-aware runtime trade-plan integration

## Data constraint discovered during Issue 14 proof
- `outcome_15c IS NOT NULL`: 0 in the referenced proof run
- `outcome_60c IS NOT NULL`: 0 in the referenced proof run

That means Issues 16 and 17 are presently blocked by label/backfill availability, not by the horizon-training architecture itself.

---

# 6. CURRENT DATA PIPELINE

## High-level pipeline
`price_bars_1m → snapshots → outcome_* → features → ML → decision engine → UI`

## Persistence state
- All tracked tickers are written to the DB via the background logger
- Persistence no longer depends on whether a ticker is selected in the UI

## Why this matters
A live research / decision system cannot rely on user focus to maintain continuity of data collection.  
Background persistence is therefore a required architectural property, not just a convenience.

---

# 7. FULL ARCHITECTURE — CURRENT RUNTIME SYSTEM

## 7.1 Feature ingestion

### Entry point
`market_state.py`
- `build_market_state(...)`

### Purpose
This is where the live market slice is assembled and the runtime input object is constructed.

### Primary inputs
- prices
- walls / level context
- broader market context
- DB handle / stored state
- session/runtime context

### Output
- `SignalInput`

### Why this matters
`SignalInput` is the common raw/context container for the downstream runtime stack.

---

## 7.2 Feature transformation

### Orchestration
`signals.py`
- `compute_signals(...)`
- `_compute_signals_impl(...)`

### Runtime sub-layers consuming `SignalInput`
- `rules_engine.compute_rules(...)`
- `volatility_regime.classify_volatility_regime(...)`
- `regime_engine.classify_regime(...)`
- `prediction_engine.build_ml_snapshot_for_fusion(...)`

### What this means
Features are **not** all consumed by one universal flat weighted formula at the point of ingestion.

Instead:
- raw/context features are assembled first
- different runtime layers consume the same input differently
- model-ready feature snapshots are then built for ML/fusion use

### Why this matters
This architecture keeps:
- raw market state
- rule interpretation
- regime interpretation
- feature engineering
- model inference

as related but distinct layers.

---

## 7.3 Model layer

### Current live model path
`ml_predict.run_base_models_once(...)`

### Active model families in the live path
- XGBoost
- LSTM
- Transformer

### What happens here
The active model stack runs once per live inference pass and produces the model outputs needed for the downstream combined runtime stack.

### Why this matters
Issue 13 required a single ML inference truth path, so the runtime does not allow duplicated or semantically divergent model access to compete in live decision logic.

---

## 7.4 Simulation layer

### Monte Carlo
`monte_carlo.simulate(...)`

### Role
Monte Carlo contributes forward path / scenario context into the combined runtime stack.

### Why it matters
The system is not purely a classifier stack.  
It also uses simulation context as part of the combined evidence system.

---

## 7.5 Fusion layer

### Bayesian fusion
`bayesian_fusion.fuse(...)`

### Role
Fusion takes the relevant model and contextual evidence and resolves it into a combined forward posterior.

### Output
That posterior is then transformed into:
- `CanonicalForecast`

### Why this matters
The runtime decision system is not allowed to choose among multiple competing forward truths at the decision layer.  
Fusion is the stage that resolves that plurality into one combined forward belief.

---

## 7.6 Decision layer

### Decision object
`CanonicalForecast`

### Current runtime decision rule
All tradable live decisions must derive from:
- canonical direction
- canonical probabilities
- canonical confidence
- canonical provenance

### Decision consumption
The decision layer uses canonical for:
- stack vote
- prediction agreement logic
- gates
- readiness
- conviction seed
- final signal alignment

### Why this matters
This is the answer to “what actually drives the trade?”  
The trade is no longer allowed to come from a hybrid or ambiguous source.

---

## 7.7 Output layer

### Output objects / path
- `SignalOutput`
- `MarketState`
- `server.py`
- JSON / UI
- `DECISION_BUNDLE`

### Why this matters
The outward-facing state must reflect the same runtime truth that the decision engine used.

That is why Issue 13 explicitly carried canonical truth outward into state and logs.

---

## 7.8 Current runtime flow diagram

```text
LIVE MARKET / DB / CONTEXT
    │
    ▼
market_state.py
build_market_state(...)
    │
    ▼
SignalInput
    │
    ├── rules_engine.compute_rules(...)
    │        │
    │        ▼
    │     RulesCard
    │
    ├── volatility_regime.classify_volatility_regime(...)
    │        │
    │        ▼
    │     Volatility Policy
    │
    ├── regime_engine.classify_regime(...)
    │        │
    │        ▼
    │     Regime Payload
    │
    └── prediction_engine.build_ml_snapshot_for_fusion(...)
             │
             ▼
        ML Feature Snapshot
             │
             ▼
        ml_predict.run_base_models_once(...)
             │
             ├── XGBoost
             ├── LSTM
             └── Transformer
             │
             ▼
        Base Model Outputs
             │
             ├── monte_carlo.simulate(...)
             │        │
             │        ▼
             │     Monte Carlo Output
             │
             ▼
        bayesian_fusion.fuse(...)
             │
             ▼
        CanonicalForecast
        (single forward directional truth)
             │
             ├── prediction_engine.compute_prediction(...)
             │        ├── Historical view
             │        └── Forward / canonical view
             │
             ▼
        call_engine.compute_call(...)
             ├── stack vote
             ├── gates
             ├── readiness
             ├── conviction
             └── sizing / risk
             │
             ▼
        SignalOutput
             │
             ▼
        MarketState
             │
             ▼
        server.py / JSON / UI / DECISION_BUNDLE logs
```

---

# 8. WEIGHTING — CURRENT STATE VS FUTURE STATE

## 8.1 Current weighting state

### What is true today
The system does **not** currently use one explicit central weighting table that says:
- feature A gets X weight
- feature B gets Y weight
- dynamically updated every regime step

Instead, weighting currently happens in layered form:

#### Rules layer
Uses thresholds / logic / pattern interpretation

#### Volatility / regime layers
Provide policy and contextual interpretation

#### ML models
Learn internal importance implicitly from training

#### Fusion layer
Combines evidence into a posterior

#### Decision layer
Uses canonical confidence / probability and applies policy downgrades

### Why this matters
Features are not “just dumped in raw with no weighting,” but their weighting is not yet managed by one explicit regime-aware weighting engine either.

The current system is therefore:
- partially weighted
- partially learned
- partially policy-shaped

but **not yet** fully market-state-aware in the way the future design intends.

---

## 8.2 What is NOT yet implemented

The system does **not yet** have a formal mechanism that says, for example:
- in unstable volatility, trust trend continuation less
- near key positioning zones, trust dealer/flow features more
- in compression, trust breakout-related evidence more

This is the missing future enhancement:
> market-state-aware adaptive feature weighting

---

## 8.3 Future weighting direction (confirmed)

The future design should implement:

### Market-state-aware adaptive feature weighting
This means the system should adjust feature-group trust / weighting based on identified market condition.

Examples:
- higher volatility / unstable regime should reduce trust in slow trend continuation and raise caution
- trending / expansion regime should increase trust in continuation-related evidence
- structural liquidity / hedging context should influence how much weight flow / positioning signals carry

### Design principle
This should be:
- learned where possible
- policy-aware where necessary
- not arbitrary static multipliers

### Why this is the correct direction
Not all features matter equally in all market states.  
A serious institutional system should adapt trust based on context.

---

# 9. MODEL ARCHITECTURE CLARIFICATION

## 9.1 Training layer
Parallel and Cascade are currently:
- model training / evaluation / promotion strategies
- not live competing decision engines

## 9.2 Runtime layer
The live app uses:
> a SINGLE COMBINED DECISION STACK

Meaning:
- models run
- Monte Carlo runs
- fusion resolves evidence
- `CanonicalForecast` becomes decision authority
- decision logic consumes that canonical object

There is no competing runtime logic after Issue 13.

---

## 9.3 Meaning of the three terms

### Combined stack
The runtime decision pipeline that turns all available evidence into one trade decision.

### Parallel stack
A training/model-family architecture in which models operate independently and are compared or fused later.

### Cascade stack
A training/model-family architecture in which later stages depend on prior stages in a sequential structure.

---

## 9.4 Promotion rule
Parallel and Cascade candidates may be evaluated and promoted into active.

The combined runtime stack is not itself promoted to parallel or cascade.

Instead:
- trained model families produce candidate artifacts
- promotion selects the winning artifact family
- the live combined runtime stack consumes the active artifacts

### Why this matters
This answers the distinction:
- parallel / cascade = training architecture choices
- combined stack = runtime decision orchestration

---

# 10. DECISION AUTHORITY RULES

## Current runtime decision authority
Only:
- `CanonicalForecast`

## CanonicalForecast governs
- direction
- probabilities
- confidence
- gates
- readiness
- conviction seed
- final signal alignment

## What must NOT act as independent decision authority
- historical empirical 5c context
- confluence counts
- raw rule outputs
- synthetic override probabilities
- duplicate inference-path outputs
- fusion-unavailable fallback posteriors

### Why this matters
The system must know exactly which object owns the trade decision.  
If multiple submodules can each silently become the authority, the system loses integrity.

---

# 11. NON-TRADABLE STATES

If canonical provenance indicates there is no real usable posterior, including:
- `fusion_unavailable`
- `missing_canonical_fallback`

then:
- the system must force `WAIT`
- a directional trade is not tradable

### Why this matters
This prevents the system from turning uncertainty or missingness into false confidence.

---

# 12. CONVICTION MODEL

## Current rule
Conviction is seeded from:
- canonical confidence
- canonical dominant-probability margin

## Environmental modifiers
Conviction may then be downgraded by environment, such as:
- divergence
- event risk
- reversal-prone regime
- volatility caution
- structural transition caution

## Explicit limit
Conviction may **not** exceed what the canonical forecast supports.

### Why this matters
The system is not allowed to become more confident than its own canonical forward posterior justifies.

---

# 13. LOGGING / TRACEABILITY

The system emits structured `DECISION_BUNDLE` logging for validation.

## Logged decision data includes
- canonical probabilities
- canonical provenance
- fusion state
- final signal
- conviction
- gate summary
- size decision
- override application state (if any)

### Why this matters
A serious trading system must be auditable.  
The operator must be able to answer:
- what did the system believe?
- why did it take or reject the trade?
- what object actually drove that belief?

---

# 14. NEXT STEPS (STRICT ORDER)

## Issue 15 — 5c architectural closeout
- perform a full clean-code closeout pass on the 5c expansion
- search all remaining 1c hardcoding in shared ML infrastructure
- classify each occurrence as:
  - already correct
  - must generalize now
  - intentionally deferred by current product/runtime design
- eliminate all non-deferred 1c hardcoding in the 5c training/evaluation/promotion infrastructure
- prove 1c still works
- prove 5c still works
- do not treat Issue 15 as fully closed until the implementation is both functionally correct and architecturally clean

## Label pipeline validation before Issues 16 and 17
- validate why `outcome_15c` and `outcome_60c` were observed as empty in proof runs
- inspect backfill / fill-outcome logic for 15c and 60c
- confirm whether the problem is:
  - missing label generation
  - insufficient history window
  - scheduler/backfill coverage gap
  - historical data continuity issue
- do not proceed to 15c or 60c ML until label availability is real and proven

## Issue 16 — ML horizon expansion: 15c
- add true 15c forward ML
- implement the same standard reached for 5c, not a shortcut
- keep 1c and 5c intact
- preserve artifact separation and metadata integrity

## Issue 17 — ML horizon expansion: 60c
- add true 60c forward ML
- preserve clean horizon separation
- use the same no-shortcut standard as 5c and 15c

## Issue 18 — Low-data ticker promotion depth
- bring PCG / SMCI and similar low-depth symbols to promotable depth
- address data sufficiency rather than lowering standards
- keep promotion integrity intact

---

# 15. CONFIRMED FUTURE ARCHITECTURE DECISIONS

## 15.1 Current main prediction object
The current main prediction object remains:

> the canonical forward forecast built from the active model stack

This is the correct present-state design.

---

## 15.2 Transition to multi-horizon canonical forecasting
When multi-horizon ML is built, the system should move from:
- one single canonical directional object

to:
- a **multi-horizon canonical framework**

This decision is confirmed and must remain on the roadmap.

---

## 15.3 Planned horizon labels
Future horizon labeling is confirmed as:

- **Execution bias**
- **Scalp bias**
- **Intraday bias**
- **Session bias**

Mapped as:
- `canonical_1c`   → Execution bias
- `canonical_5c`   → Scalp bias
- `canonical_15c`  → Intraday bias
- `canonical_60c`  → Session bias

---

## 15.4 Future trade design
The future preferred design is:
- one primary trade recommendation based on the user-selected trade horizon
- plus a multi-horizon alignment panel

### Why this matters
Markets can show different directional behavior on different horizons.  
The system should not pretend those are contradictions when they may be normal multi-horizon structure.  
The correct answer is not four chaotic headline calls, but:
- one primary call for the selected trade mode
- one multi-horizon context layer

---

## 15.5 Decision 10.1 — confirmed
Confirmed choice:
- do **not** keep 5c as historical-only context forever
- **do** move to full multi-horizon forward forecasting

Meaning:
- 1c, 5c, 15c, 60c should all become true predictive model objects
- 5c should not remain the main prediction object on its own
- the future state should be multi-horizon canonical, not single-horizon forever

---

## 15.6 Decision 10.2 — confirmed
Confirmed direction:
- continue parallel + cascade evaluation for now
- but eventually converge to one winning architecture
- do not converge prematurely
- make that decision only after later evaluation is mature enough

### Why this matters
The system is still in an architecture-evaluation phase.  
Premature convergence would sacrifice learning before the multi-horizon framework is complete.

---

## 15.7 Multi-horizon model separation
The confirmed design is **not** one model predicting multiple horizons simultaneously.

It is:
- one independent 1c predictive stack
- one independent 5c predictive stack
- one future independent 15c predictive stack
- one future independent 60c predictive stack

Each stack trains on:
- the same underlying market-state family
- a different forward target column

This distinction matters because:
- horizon-specific prediction problems are materially different
- the model, label, and expected hold semantics change by horizon
- architectural honesty requires horizon separation rather than one blended pseudo-horizon object

---

## 15.8 Horizon-specific trade-plan design
It is confirmed that each horizon can theoretically and architecturally have its own:
- entry
- stop
- target
- expected hold time
- confidence
- trade style

That means future system design may validly produce different trade plans for:
- 1c execution
- 5c scalp
- 15c intraday
- 60c session

This is not a contradiction.  
It is a consequence of different predictive horizons solving different trade problems.

---

## 15.9 Primary-horizon authority with secondary-horizon context
The future system should not emit four equal trade authorities simultaneously.

The confirmed preferred structure is:

1. each horizon computes its own forecast / trade intent
2. one user-selected or strategy-selected horizon becomes the **primary trade authority**
3. other horizons become:
   - confirmation
   - contradiction detection
   - entry-timing refinement
   - hold-management context
   - risk-adjustment context

This preserves:
- one final trade authority
- multi-horizon informational richness
- no chaotic multi-call output design

---

## 15.10 Expected usage model
The intended future interpretation is:

- 1c → entry timing / execution horizon
- 5c → scalp or immediate directional move horizon
- 15c → intraday structure horizon
- 60c → session bias horizon

A practical usage example is:
- 15c and 60c bullish
- 5c bullish
- 1c temporarily bearish

Correct interpretation:
- higher-order trade bias remains bullish
- immediate action is to wait for 1c re-alignment before entering
- the lower horizon refines timing, not direction authority

---

# 16. FUTURE ENHANCEMENTS / FOLLOW-UP ITEMS TO PRESERVE

## 16.1 Adaptive feature weighting
The system should implement:
> market-state-aware adaptive feature weighting

### Goal
Adjust feature/group importance based on identified market conditions and regime.

### Examples
- higher volatility / instability should change how much trust is given to certain signals
- trending environments should shift weighting differently than reversal-prone or unstable conditions
- liquidity / hedging / structural context should affect trust and weighting

### Design intent
- learned where possible
- policy-aware where needed
- not arbitrary static multipliers

---

## 16.2 Position sizing refinement
Future refinement decision:
- move position sizing to pure canonical-probability / canonical-forecast-based sizing
- not confluence-count-based scaling

This was explicitly chosen and must not be forgotten.

---

## 16.3 Multi-horizon canonical architecture
Future roadmap should explicitly include:
- `canonical_1c`
- `canonical_5c`
- `canonical_15c`
- `canonical_60c`
- horizon-specific trade calls / bias layers
- horizon alignment logic
- user-selectable primary trade horizon
- adaptive weighting by market regime

---

## 16.4 Horizon-specific trade-plan generation
Future roadmap should explicitly preserve the ability for each horizon to produce its own:
- entry zone / entry number
- stop-loss
- primary target
- stretch target
- expected hold duration
- confidence and risk notes

This should later feed into:
- one selected primary trade plan
- plus multi-horizon confirmation / contradiction context

---

## 16.5 Label/backfill validation for 15c and 60c
A required follow-up item is to validate and repair, if necessary, the outcome pipeline for:
- `outcome_15c`
- `outcome_60c`

This is a prerequisite for responsible completion of Issues 16 and 17.

---

## 16.6 Issue 15 clean-code closeout standard
The project standard established in this session is:

- functional is not enough
- shared ML infrastructure must be clean
- any remaining 1c-only logic must be either:
  - intentionally product-scoped
  - or generalized now

This standard must persist for later horizon expansions as well.

---

# 17. GUIDING PRINCIPLE FOR THE FUTURE SYSTEM

The system evolves from:
- single canonical forecast
→
- multi-horizon canonical system
→
- adaptive, market-aware predictive engine

BUT ALWAYS:

> ONE unified runtime decision truth

Never:
- multiple competing runtime forecasts
- multiple independent runtime decision engines
- ambiguous decision ownership

The multi-horizon future is therefore not a return to ambiguity.  
It is an increase in structured context under one explicit decision hierarchy.

---

# 18. STATUS SUMMARY

| Component | Status |
|----------|--------|
| Issue 11 (restore valid 1c ML stack) | Complete |
| Issue 12 (UI null-guard hardening) | Complete |
| Issue 13 (decision engine alignment) | Complete |
| Issue 14 (per-horizon dataset independence) | Complete |
| Issue 15 (5c ML horizon expansion) | Functionally implemented; architecturally open pending closeout pass |
| Issue 16 (15c ML) | Blocked by current 15c label availability proof gap |
| Issue 17 (60c ML) | Blocked by current 60c label availability proof gap |
| Issue 18 (low-data ticker promotion depth) | Pending |
| Adaptive weighting | Planned |
| Pure canonical sizing refinement | Planned |
| Parallel vs cascade convergence | Future decision |
| Multi-horizon canonical framework | Planned |
| Horizon-specific trade-plan framework | Planned |
| 15c/60c label pipeline validation | Required next-step prerequisite |

---

# 19. OPERATIONAL HANDOFF SUMMARY

If a later conversation needs to resume from this file, the most important truths are:

1. Issue 13 is complete
2. `CanonicalForecast` is the current live decision authority
3. The system now uses one combined runtime decision stack
4. Parallel and Cascade are still training/evaluation architectures
5. Issue 14 is complete
6. Issue 15 is functionally implemented for 5c but not yet architecturally closed
7. Live runtime remains intentionally 1c-default
8. 5c now exists as a true ML training/evaluation/promotion lane
9. `outcome_15c` and `outcome_60c` must be validated before Issues 16 and 17
10. The future direction is multi-horizon canonical forecasting with adaptive weighting, primary-horizon trade authority, horizon-specific trade plans, and eventual architecture convergence

---

# 20. END OF MASTER DOCUMENT


====================================================================================================
# SOURCE DOCUMENT: Ed_Trading_System_MASTER_v11_AUTHORITATIVE.md
**Date:** 2026-04-02 | **Role:** MASTER SPEC v11 — authoritative master (baseline preserved inside) | **Original size:** 56,801 bytes
====================================================================================================


# ED INSTITUTIONAL PREDICTIVE TRADING ENGINE
## MASTER SPEC + LIVE ISSUE TRACKERS (AUTHORITATIVE MASTER — v10)

---

# 0. BASELINE SOURCE FILE PRESERVATION

This master document uses the original file provided at the start of this session as the project baseline.

## Original baseline file text

```markdown
# ED INSTITUTIONAL PREDICTIVE TRADING ENGINE
## MASTER SPEC + LIVE ISSUE TRACKERS (UPDATED AFTER ISSUE 11)

---

# SYSTEM STATE (CURRENT)

The system now has:
- Correct bar-based horizons
- Canonical anchor
- Honest missingness (no synthetic probabilities)
- Auto-expanding universe with background persistence
- Fully hardened UI (no runtime crashes)
- Valid 1c ML stack restored for compliant tickers

Limitations:
- Some tickers (PCG, SMCI) blocked by insufficient data for promotion
- Multi-horizon ML not yet implemented

---

# PRIMARY ISSUE TRACKER

## CLOSED
1. Timeframe integrity  
2. Remove non-target horizons  
3. Universal horizon standardization  
4. Anchor standardization  
5. Fallback policy formalization  
6. Internal decision integrity  
7. Feature/schema parity / model enforcement  
8. UI bug (hint)  
9. Confluence render hardening  
10. Universe persistence / auto-expanding universe  
11. Restore valid 1c ML stack  
12. Full UI null-guard hardening  

## OPEN
13. Decision engine alignment  
14. Per-horizon training dataset independence  
15. ML horizon expansion: 5c  
16. ML horizon expansion: 15c  
17. ML horizon expansion: 60c  
18. Bring low-data tickers (PCG, SMCI) to promotable depth  

---

# DRIFT / RESIDUAL TRACKER

D2. UTC vs session alignment  
D3. Backfill window limitation  
D4. Cold-start data gaps  
D5. Historical continuity gap  
D7. Anchor boundary edge-case  
D8. Feature vs anchor timing mismatch  
D10. Control-state ambiguity  
D12. Training row eligibility tied to all-horizon outcome_filled  

---

# ML SYSTEM STATE

## Current
- All models trained on outcome_1c
- Artifacts:
  - xgb_{ticker}_1c.pkl
  - lstm_{ticker}_1c.pt
  - transformer_{ticker}_1c.pt
- Contract enforcement active and validated
- Loaders require full metadata compliance

## Not yet implemented
- 5c ML
- 15c ML
- 60c ML
- Per-horizon training eligibility

---

# DATA PIPELINE

price_bars_1m → snapshots → outcome_* → features → ML → decision engine → UI

Persistence:
- All tracked tickers now written to DB via background logger
- No dependency on UI selection

---

# NEXT STEPS (STRICT ORDER)

## Issue 13 — Decision Engine Alignment
- Verify how ML outputs are used
- Confirm no stale assumptions
- Align confidence / signal logic

## Issue 14 — Per-horizon dataset independence
- Remove dependence on outcome_filled for all horizons
- Allow horizon-specific training eligibility

## Issue 15–17 — Multi-horizon ML
- Implement 5c, then 15c, then 60c

---

# GUARANTEES

The system enforces:
- No fake data
- No hidden fallbacks
- No contract violations
- No UI crashes
- No stale model usage

---

# END
```

The remainder of this document preserves that baseline and layers in all validated updates, issue history, architecture clarification, confirmed decisions, execution outcomes, roadmap decisions, and future system design that were agreed and refined during this session.

---

# 1. SYSTEM STATE (CURRENT)

The system now has:

- Correct bar-based horizons
- Canonical anchor
- Honest missingness in production decision flow
- Auto-expanding universe with background persistence
- Fully hardened UI against null / missing render crashes
- Valid restored 1c ML stack for compliant tickers
- Clean per-horizon dataset independence
- True ML training support for 1c, 5c, 15c, and 60c
- Populated and verified `outcome_15c` and `outcome_60c`
- Scheduler-managed synchronization between `snapshots` and `snapshots_1m_normalized`
- Horizon-aware manifests, cache keys, metadata, artifact names, promotion roots, and archive paths
- CanonicalForecast as the single current runtime decision authority
- Single current live inference truth path for the active runtime stack
- Explicit decision trace logging through `DECISION_BUNDLE`
- Fusion-unavailable states explicitly forced to `WAIT`
- Conviction bounded by canonical forward probability / confidence rather than allowed to outrun canonical strength

## Limitations

- Some tickers, especially lower-history or lower-depth cases such as PCG and SMCI, may still remain blocked by insufficient promotable depth
- Runtime decisioning is still intentionally 1c-centric by current product policy
- Multi-horizon canonical decision logic is not yet implemented
- Cross-horizon alignment, contradiction handling, and primary-horizon trade selection are not yet implemented
- Market-state-aware adaptive feature weighting is not yet implemented
- Position sizing is not yet fully driven by canonical probabilities alone
- Parallel vs cascade has not yet been converged to one permanent winning architecture
- Full scheduler completion and manifest refresh still must be run on the current workspace to finalize latest artifact evaluation state after the newest horizon additions

## Current operating truth

The system is not allowed to run with multiple competing runtime decision truths.

Today:
- the runtime stack must resolve to one canonical decision object before a trade decision is produced
- the live runtime authority remains the current canonical 1c-oriented stack

At the same time, the training and evaluation system has now expanded into a true multi-horizon ML foundation across:
- 1c
- 5c
- 15c
- 60c

That means the system has crossed the boundary from:
- single-horizon ML
to:
- multi-horizon ML foundation with single-horizon runtime authority

The next major step is therefore no longer data repair or horizon expansion.  
The next major step is:
- **Multi-Horizon Decision Engine**

---

# 2. PRIMARY ISSUE TRACKER

## CLOSED

1. Timeframe integrity  
2. Remove non-target horizons  
3. Universal horizon standardization  
4. Anchor standardization  
5. Fallback policy formalization  
6. Internal decision integrity  
7. Feature/schema parity / model enforcement  
8. UI bug (hint)  
9. Confluence render hardening  
10. Universe persistence / auto-expanding universe  
11. Restore valid 1c ML stack  
12. Full UI null-guard hardening  
13. Decision engine alignment  
14. Per-horizon training dataset independence  
15. ML horizon expansion: 5c  
16. ML horizon expansion: 15c  
17. ML horizon expansion: 60c  

## OPEN

18. Bring low-data tickers (PCG, SMCI) to promotable depth  

## NEXT PHASE AFTER ISSUE TRACKER

The next major phase is:

- **Multi-Horizon Decision Engine**
  - combine 1c / 5c / 15c / 60c into one structured trade-decision system
  - define primary-vs-supporting horizon authority
  - create alignment / contradiction logic
  - convert horizon forecasts into trade plans
  - preserve one unified runtime decision truth

---

# 3. ISSUE HISTORY — COMPLETE RECORD

## Issue 1 — Timeframe integrity

**Original issue title:** Timeframe integrity

**Historical status:** Closed before this session.  
**Current status:** Still closed.  
**Effect of later work:** No reversal. Issue 13 reinforced the importance of strict timeframe integrity by eliminating mixed-horizon runtime decision behavior.

### What this issue represented
This issue established that the system needed clean timeframe handling and could not tolerate ambiguous or inconsistent horizon semantics.

### Why it mattered
Without timeframe integrity:
- labels become unreliable
- training targets become ambiguous
- decision logic can mix incompatible horizons
- evaluation becomes misleading

### What later work changed
Later work, especially Issue 13, did **not** reopen Issue 1, but it did make its importance more explicit by removing runtime horizon mixing and insisting that live decisions be derived from one coherent forecast object rather than mixed horizon fragments.

### Current interpretation
Issue 1 remains closed and structurally valid.

---

## Issue 2 — Remove non-target horizons

**Original issue title:** Remove non-target horizons

**Historical status:** Closed before this session.  
**Current status:** Still closed.  
**Effect of later work:** No reversal.

### What this issue represented
This issue removed horizon handling that was outside the intended target design.

### Why it mattered
The system needed to stop reasoning over horizons that were not part of the active target framework, because that creates noise, inconsistent UI semantics, and invalid downstream assumptions.

### What later work changed
Issue 13 later eliminated a different but related problem: not just non-target horizon presence, but mixed-horizon decision usage. That means Issue 2 remains correct and closed, while Issue 13 completed the runtime decision integrity that Issue 2 conceptually pointed toward.

### Current interpretation
Issue 2 remains closed and valid.

---

## Issue 3 — Universal horizon standardization

**Original issue title:** Universal horizon standardization

**Historical status:** Closed before this session.  
**Current status:** Still closed.  
**Effect of later work:** No reversal. Future multi-horizon expansion was built on this foundation.

### What this issue represented
The system needed one consistent way to name, interpret, and use horizons throughout training, evaluation, UI, and decision logic.

### Why it mattered
Without universal standardization:
- models and UI can refer to different meanings for the same horizon
- gates can accidentally compare incompatible objects
- logs become unreliable

### What later work changed
Issue 13 exposed that even with closed standardization work, runtime decision logic could still accidentally mix horizon-derived quantities. That later issue did not invalidate Issue 3; it completed the enforcement of its intent.

Issue 15 and later horizon-expansion work also proved why Issue 3 mattered. Clean horizon-aware naming across:
- dataset labels
- artifact names
- manifests
- cache keys
- active roots
- arch state paths

was only possible because horizon semantics had already been standardized conceptually.

### Current interpretation
Issue 3 remains closed and is foundational for:
- `canonical_1c`
- `canonical_5c`
- `canonical_15c`
- `canonical_60c`

and for the future multi-horizon canonical design.

---

## Issue 4 — Anchor standardization

**Original issue title:** Anchor standardization

**Historical status:** Closed before this session.  
**Current status:** Still closed.  
**Effect of later work:** No reversal.

### What this issue represented
The system needed a canonical anchor convention for runtime and training reference points.

### Why it mattered
Without anchor standardization:
- feature timing can drift
- labels can misalign with the intended reference
- downstream signals can appear correct while being built on inconsistent temporal anchoring

### What later work changed
The residual tracker still contains:
- D7. Anchor boundary edge-case
- D8. Feature vs anchor timing mismatch

This does **not** reopen Issue 4. It means the broad standardization is complete, while edge cases and residual drift remain tracked.

### Current interpretation
Issue 4 remains closed; residual anchor-related items remain under drift tracking, not as a reopened core issue.

---

## Issue 5 — Fallback policy formalization

**Original issue title:** Fallback policy formalization

**Historical status:** Closed before this session.  
**Current status:** Closed and materially reinforced by Issue 13.

### What this issue represented
The system needed explicit rules for what happens when preferred inputs or model states are unavailable.

### Why it mattered
Unformalized fallback behavior is dangerous because it can:
- silently fabricate confidence
- hide missingness
- create misleading trade bias
- weaken trust in the system

### What later work changed
Issue 13 materially tightened Issue 5. The system now enforces:
- no synthetic probabilities in production decision flow
- explicit `WAIT` when fusion / canonical posterior is unavailable
- constraints on override behavior so fake probabilities cannot silently influence live decisions

### Current interpretation
Issue 5 remains closed, but its operational meaning is now stricter than before:
- fallback may protect rendering or continuity
- fallback may **not** invent tradable confidence or direction

---

## Issue 6 — Internal decision integrity

**Original issue title:** Internal decision integrity

**Historical status:** Closed before this session.  
**Current status:** Closed and fully finalized by Issue 13.

### What this issue represented
The system needed its internal decisions to be logically coherent and not allow contradictory states across submodules.

### Why it mattered
A trading system cannot claim integrity if:
- one layer says bullish and another silently governs bearish
- confidence and direction come from different uncoordinated truths
- the UI and runtime logic describe different states

### What later work changed
Issue 13 is the full realization of Issue 6. It:
- introduced `CanonicalForecast`
- removed competing prediction truths
- aligned readiness, gating, conviction, and signal logic
- enforced one runtime decision authority

### Current interpretation
Issue 6 is not merely closed; it is fully completed by the Issue 13 alignment work.

---

## Issue 7 — Feature/schema parity / model enforcement

**Original issue title:** Feature/schema parity / model enforcement

**Historical status:** Closed before this session.  
**Current status:** Closed.  
**Effect of later work:** Reinforced by Issue 11 and Issue 13, and extended by the later multi-horizon work.

### What this issue represented
The system needed strict agreement between:
- feature generation
- expected model schema
- loader assumptions
- live inference expectations

### Why it mattered
Without schema parity:
- live inference can silently break
- active models can become unusable
- evaluation and deployment diverge

### What later work changed
Issue 11 reinforced this through strict loader compliance and model contract enforcement.  
Issue 13 reinforced it again by forcing a single runtime inference path and removing duplicate semantic access paths.

Issues 15–17 proved that feature/schema parity also has a horizon dimension. True 15c and 60c support required not just artifact naming and label routing, but feature-contract parity so that product horizons had symmetric rule features, spread features, and confidence features.

### Current interpretation
Issue 7 remains closed and continues to govern the strictness of:
- live model loading
- inference compatibility
- horizon-specific feature contracts

---

## Issue 8 — UI bug (hint)

**Original issue title:** UI bug (hint)

**Historical status:** Closed before this session.  
**Current status:** Closed.  
**Effect of later work:** Reinforced by Issue 12.

### What this issue represented
A UI-level defect existed and was corrected.

### Why it mattered
Even when backend logic is correct, UI bugs can mislead the operator, hide state, or present inconsistent information.

### What later work changed
Issue 12 later extended UI stability significantly with full null-guard hardening.

### Current interpretation
Issue 8 remains closed and sits upstream of the more comprehensive UI stability work completed later.

---

## Issue 9 — Confluence render hardening

**Original issue title:** Confluence render hardening

**Historical status:** Closed before this session.  
**Current status:** Closed.  
**Effect of later work:** No reversal.

### What this issue represented
Render logic needed hardening around confluence-related outputs.

### Why it mattered
Confluence information is often incomplete or conditional. The UI and runtime state must not fail because one element of confluence is absent or delayed.

### What later work changed
Issue 12 generalized this safety principle beyond confluence and across the UI.

### Current interpretation
Issue 9 remains closed.

---

## Issue 10 — Universe persistence / auto-expanding universe

**Original issue title:** Universe persistence / auto-expanding universe

**Historical status:** Closed before this session.  
**Current status:** Closed.  
**Effect of later work:** No reversal.

### What this issue represented
The system needed symbol persistence independent of whether a user was looking at a symbol in the UI.

### Why it mattered
A live trading / research system cannot depend on UI focus for data collection.  
Persistence must happen in the background.

### What later work changed
Nothing in Issues 11–17 reversed this. The current data pipeline still preserves:
- background logging
- all tracked tickers written via background logger
- no dependency on UI selection

### Current interpretation
Issue 10 remains closed and valid.

---

## Issue 11 — Restore valid 1c ML stack

**Original issue title:** Restore valid 1c ML stack

**Historical status:** Open in baseline, resolved during this broader period.  
**Current status:** Closed.

### Problem definition
The valid 1c model stack for compliant tickers needed to be restored, but promotion and loader-contract issues were preventing correct recovery of active artifacts.

### Root cause
The core problem was not just missing training. It was a promotion deadlock:
- active model sets could be contract-noncompliant
- retrained candidates could be valid
- but promotion logic could still allow stale active metadata to block promotion

This meant a broken active set could remain in place even when a valid replacement existed.

### Full fix set

#### 11.1 Promotion behavior when active models fail the loader contract
When `verify_active_models.check_artifact_compliance` reported that an active model set was non-compliant, and `--force-retrain` was used:
- `_promotion_existing_prov` was cleared
- `validate_for_promotion(...)` no longer let legacy noncompliant active metadata act as a tie-breaker against the new contract-complete candidate

**Effect:**  
A newly valid candidate could replace a broken active set.

#### 11.2 `--promote-from-manifests`
A new path allowed promotion without retraining:
- load `scheduler_run_manifest.json`
- compare candidate evaluation from:
  - `models/parallel/{ticker}`
  - `models/cascade/{ticker}`
- reapply normal comparison logic
- promote a winning contract-complete candidate into `models/active/{ticker}`

**Why this mattered:**  
It avoided unnecessary multi-hour retrains when the correct artifacts already existed.

#### 11.3 `ED_ML_SCHEDULER_TICKERS`
An optional environment variable allowed targeting specific symbols only.

**Why this mattered:**  
It enabled targeted repair and isolated retraining / promotion work for affected tickers.

### What did NOT change
Issue 11 did **not** relax standards:
- no weakening of `model_contract`
- no weakening of loader metadata requirements
- no bypass of artifact completeness
- no silent acceptance of noncompliant active artifacts

### Impact
Issue 11 restored the valid 1c stack for compliant tickers and resolved the promotion deadlock that could leave legacy/broken artifacts active.

### What it did NOT solve
Issue 11 did **not** solve:
- low-data tickers lacking promotable depth
- multi-horizon ML
- per-horizon dataset independence
- decision-engine alignment

Those remained future or later issues.

### Current interpretation
Issue 11 is closed and forms the basis of the current live 1c model availability.

---

## Issue 12 — Full UI null-guard hardening

**Original issue title:** Full UI null-guard hardening

**Historical status:** Open in baseline, later resolved.  
**Current status:** Closed.

### Problem definition
The UI could crash or render inconsistently when values were absent, partial, or delayed.

### Root cause
The UI and payload layers were still assuming the presence of some values that are not guaranteed during:
- cold starts
- partial model availability
- sparse confluence states
- incomplete decision payloads

### What changed
Issue 12 hardened the UI against:
- null / None values
- missing fields
- incomplete confluence
- absent model outputs

### What the fix did
- protected rendering paths
- allowed the system to remain honest about missing data
- prevented crashes without fabricating replacement data

### Why it mattered
This issue made the system operationally stable without corrupting truthfulness.  
That distinction matters because many systems become “stable” by inventing defaults. This one needed to remain truthful.

### What it did NOT change
Issue 12 was a UI/render resilience issue. It did **not**:
- change model logic
- change trade logic
- create synthetic confidence
- change the source of runtime decision authority

### Impact
The UI can remain up and usable even when portions of the backend state are incomplete or still loading.

### Current interpretation
Issue 12 is closed and remains foundational for stability.

---

## Issue 13 — Decision engine alignment

**Original issue title:** Decision engine alignment

**Historical status:** Open in baseline, fully resolved during this session.  
**Current status:** Closed.

### Original objective
- verify how ML outputs were actually being used
- confirm there were no stale assumptions
- align confidence / signal logic
- remove contradictions between runtime submodules

### Problem definition
Before Issue 13, the system had multiple competing notions of “prediction” and more than one implicit decision truth.

Examples of the misalignment included:
- fusion direction versus empirical 5c dominant direction
- mixed-horizon probability gating
- fragmented confidence semantics
- readiness logic not perfectly aligned with final gated state
- duplicate ML-access paths
- override behavior that could inject synthetic probability structures into decision flow

### Root cause
The system had evolved into a state where:
- empirical context
- model outputs
- fusion outputs
- signal generation
- conviction
- readiness
- gating

were not all driven by a single canonical object.  
That created structural contradiction, even when individual components looked internally reasonable.

### Full fix set

#### 13.1 Canonical decision object
A new `CanonicalForecast` was introduced and made the single forward directional belief for the decision stack.

It contains:
- direction
- probability_up
- probability_down
- probability_flat
- confidence
- provenance

This object became the required source for:
- stack vote
- prediction agreement logic
- probability gates
- readiness direction
- final decision alignment

#### 13.2 Empirical vs forward separation
The predictive layer was refactored so that:
- empirical 5c statistics are historical context
- forward direction is carried by canonical / fusion output
- these two concepts are no longer allowed to masquerade as the same object

**Why this mattered:**  
Historical context can be useful, but it must not pretend to be the active forward trade forecast.

#### 13.3 Stack vote alignment
Prediction-vote logic was moved onto canonical-only semantics.

**Why this mattered:**  
The final runtime stack must vote using one actual forward belief, not a hybrid of historical and forward objects.

#### 13.4 Mixed-horizon gate removal
Trade gates no longer mix:
- one horizon’s directional label
with
- another horizon’s probability values

**Why this mattered:**  
That was mathematically incoherent and violated the spirit of Issue 1 and Issue 3.

#### 13.5 Override safety
`pred_override` was constrained so synthetic probabilities cannot silently enter production trade flow.

**Why this mattered:**  
Debug controls are acceptable only when clearly contained and auditable.

#### 13.6 Single ML inference path
The live stack now uses one inference path:
- `run_base_models_once(...)`

This prevents semantically divergent access paths from competing in runtime logic.

#### 13.7 Readiness alignment
Readiness now uses:
- canonical direction
- post-gate final state
- actual gate result

This prevents readiness from describing a different truth than the final decision state.

#### 13.8 Confidence semantics separation
The system now separates:
- empirical confidence
- forward / fusion confidence
- call conviction

This avoids the prior misuse where a displayed “confidence” label could refer to a different underlying concept depending on context.

#### 13.9 API / logging visibility
Structured decision logging was added through `DECISION_BUNDLE`.

This allows runtime validation of:
- canonical probabilities
- fusion availability
- final signal
- conviction
- gate summary
- size decision
- override state

#### 13.10 Stale-path cleanup
Unused or misleading live-path logic was removed or isolated.

### Final closeout refinement

Issue 13 required a closeout pass because three alignment gaps still remained:
- conviction authority
- explicit fusion-unavailable policy
- API consistency around canonical truth

#### 13.10.1 Conviction authority
`call.conviction` is now seeded from:
- canonical confidence
- canonical dominant-probability margin

Environmental layers may only **downgrade** conviction.

They may not invent higher conviction than the canonical forecast supports.

#### 13.10.2 Fusion-unavailable policy
If canonical provenance is:
- `fusion_unavailable`
- `missing_canonical_fallback`

then directional trades are not allowed.

The system must force `WAIT`.

This is an explicit runtime behavior rule, not just a label.

#### 13.10.3 API truth consistency
Canonical-driven summary fields and provenance were carried outward into runtime state so that the external state matches the real runtime decision truth.

### Impact
Issue 13 fully completed runtime decision integrity.

After Issue 13:
- there is one canonical runtime decision object
- there is no horizon mixing in live decision logic
- there is no independent conviction authority
- synthetic probabilities cannot silently drive production decisions
- fusion-unavailable states are non-tradable
- the runtime stack is traceable and auditable

### Current interpretation
Issue 13 is closed and is one of the core pillars of the system’s present integrity.

---

## Issue 14 — Per-horizon training dataset independence

**Historical status:** Open.  
**Current status:** Closed.

### Problem definition
Training eligibility for one horizon was improperly tied to other horizons through shared completeness logic.

The training/data pipeline had cross-horizon dataset coupling.

The practical result was:
- rows valid for `outcome_1c` could be dropped because longer-horizon fields were still missing
- shorter-horizon eligibility was implicitly tied to the longest horizons
- the system could not support true horizon-independent ML

### Root cause
`outcome_filled` was being treated as if it were the correct gate for training row eligibility.

But:
- `outcome_filled = 1` meant all bar-spec horizons were complete
- that is a backfill completeness concept
- it is **not** a per-horizon ML eligibility concept

That meant logic equivalent to:
- `outcome_filled = 1 AND outcome_1c IS NOT NULL`

was dropping rows that were valid for 1c, 5c, or another specific horizon.

The sequence layer itself was already fundamentally single-target in its window/label usage, but the loader path was excluding valid rows before sequence generation.

### Full fix set

#### 14.1 Remove global all-horizon training eligibility
Training row inclusion was decoupled from `outcome_filled`.

#### 14.2 Introduce per-horizon eligibility clause
A dedicated `training_label_where_clause(label_column)` was introduced so that a row is eligible for horizon H if:
- `outcome_H IS NOT NULL`

and nothing else.

#### 14.3 Preserve strict label validation
The label clause validates against known horizon outcome columns.

That prevents silent bad horizon names and preserves contract clarity.

#### 14.4 Update dataset loaders
Shared training loaders, scheduler-related selection paths, and sequence input selection now use:
- horizon-specific label eligibility
instead of:
- all-horizon completeness

#### 14.5 Keep `outcome_filled` only where it belongs
`outcome_filled` remains in:
- backfill queue / completeness logic
- diagnostics
- optional historical checks

It no longer acts as the training gate.

### Sequence-layer confirmation
The LSTM and Transformer sequence paths were specifically verified.

Their behavior is now correctly understood as:
- row fetch predicate gated only by the target horizon label
- sliding windows built over valid rows
- target read from the current window’s target-horizon label only
- no hidden dependence on other horizon labels

### Impact
Issue 14 converted the system from:
- fake multi-horizon readiness
to:
- true per-horizon dataset independence

This was the foundation required for Issues 15–17.

### Current interpretation
Issue 14 is fully closed.

---

## Issue 15 — ML horizon expansion: 5c

**Historical status:** Open.  
**Current status:** Closed.

### Problem definition
The system had valid live ML only for 1c.  
5c existed as data capability and empirical context, but not as a true trained, evaluated, artifacted ML horizon.

### Root cause
The codebase was functionally 1c-only across key ML surfaces:
- target column defaults
- artifact names
- scheduler assumptions
- manifest / cache identity
- promotion paths
- evaluation assumptions

Even after initial implementation of 5c support, a cleanup pass showed that some shared infrastructure still contained hidden 1c assumptions and needed full closeout.

### Full fix set

#### 15.1 Horizon parameterization across ML stack
A single horizon module became the source of truth for:
- horizon slug normalization
- target label selection
- outcome-column routing
- artifact naming
- live-vs-training horizon defaults

#### 15.2 5c dataset construction
The system now builds 5c datasets using:
- `outcome_5c`
- horizon-specific label selection
- horizon-aware cache / fingerprint / manifest identity

#### 15.3 5c artifact separation
The system now supports true 5c artifacts:
- `xgb_{ticker}_5c.pkl`
- `lstm_{ticker}_5c.pt`
- `transformer_{ticker}_5c.pt`

with separate metadata and provenance.

#### 15.4 Scheduler / promotion separation
The system now supports separate:
- active roots
- arch state files
- manifest horizon suffixes

so 5c does not overwrite 1c.

#### 15.5 Horizon-aware evaluation path
Evaluation uses the horizon-aligned target column and horizon-aware inference context so the loaded artifacts match the label being scored.

#### 15.6 Cleanup pass
A second pass removed remaining non-deferred 1c assumptions from shared ML/training/eval infrastructure.

This included:
- default centralization
- bundle-key centralization
- cache-identity cleanup
- horizon-aware shared defaults in training, scheduler, manifests, cache, and utility paths

### Impact
Issue 15 transformed 5c from:
- unused / secondary horizon data
into:
- a real ML horizon with training, evaluation, artifacts, and scheduler support

### Current interpretation
Issue 15 is fully closed and architecturally clean.

---

## Issue 16 — ML horizon expansion: 15c

**Historical status:** Open.  
**Current status:** Closed.

### Clarification
Issue 16 had two required preconditions before true 15c ML could exist:
1. higher-horizon label generation / normalization had to be repaired
2. operational synchronization had to be enforced so normalized training data could not silently remain stale

Those were solved first, then 15c ML itself was completed.

### 16A. Higher-horizon label-generation / normalization repair

#### Problem definition
`outcome_15c` and `outcome_60c` appeared empty in the normalized training table even though higher-horizon data existed in raw snapshots.

#### Root cause
The primary failure was not horizon math.  
The primary failure was normalization-table breakage caused by schema drift.

The normalized materialization path attempted to insert columns from `snapshots` that did not exist in `snapshots_1m_normalized`, specifically:
- `horizon_outcome_schema_version`

This caused:
- SQLite insert failure
- transaction rollback
- stale normalized-table state

At the same time, shorter-horizon values could appear to exist because of older successful or partial materialization states, which created the false impression that only the long horizons were broken.

A secondary hardening issue also existed in the bar-prefetch window for `fill_outcomes`, which needed to extend far enough to support forward closes up to 60 minutes.

#### Full fix set
- added the missing normalized-table schema column
- made normalized inserts schema-safe by intersecting source/target column sets
- widened bar-prefetch upper bound so long-horizon outcome generation had the necessary forward lookahead
- rematerialized the normalized table against the repaired schema

#### Impact
After the repair:
- `outcome_15c` and `outcome_60c` were populated correctly in the training table
- the training-layer visibility issue was removed
- long-horizon labels were proven correct against the resampling contract

### 16B. Operational synchronization automation

#### Problem definition
Even after label generation was repaired, the pipeline still had an operational weakness:
- `fill_outcomes()` could update `snapshots`
- but `snapshots_1m_normalized` could remain stale unless materialization was run afterward

That manual dependency was not acceptable.

#### Root cause
There was no scheduler-managed synchronization guarantee between:
- source-of-truth snapshot outcome updates
and
- normalized training-table refresh

#### Full fix set
A scheduler-managed synchronization layer was added around normalized materialization.

Key properties:
- fingerprint-based change detection
- skip when unchanged
- rebuild when snapshots moved
- fingerprint advanced only after successful materialization
- serialized materialization lock
- orchestration wired into:
  - scheduler
  - training loader path
  - LSTM / transformer row extraction
  - live server debounce path
  - backfill and derived-data scripts

#### Impact
The normalized training table is now self-synchronizing from the system’s operational perspective.

The user is no longer expected to remember manual materialization for valid in-repo data paths.

### 16C. True 15c ML implementation

#### Problem definition
After the data pipeline was repaired, the remaining barrier to true 15c ML was not artifact routing.  
The remaining barrier was feature-contract asymmetry.

The system could already route 15c labels and artifacts structurally, but tabular rule features were not fully symmetric for product horizons.

#### Root cause
Feature engineering still omitted 15c / 60c from key horizon-based tabular rule feature generation.  
That meant training on `outcome_15c` could occur with an incomplete or asymmetric feature contract.

#### Full fix set
- horizon lists were expanded to include 15c and 60c where product horizons required parity
- rule spread/confidence feature generation was made symmetric across product horizons
- single-row feature engineering was aligned with training feature semantics
- readiness audits were extended to horizon-complete pred-column coverage
- transformer metadata horizon reporting was corrected
- compare tooling gained horizon support

#### Impact
Issue 16 converted 15c from:
- structurally routable but feature-incomplete
into:
- true first-class ML with:
  - dataset support
  - training support
  - artifact support
  - scheduler support
  - promotion separation
  - metadata honesty

### Current interpretation
Issue 16 is fully closed.

---

## Issue 17 — ML horizon expansion: 60c

**Historical status:** Open.  
**Current status:** Closed.

### Problem definition
60c was the final missing product horizon.  
By the time Issue 17 began, the architecture and data pipeline were already prepared, but the system still needed to prove true 60c ML end-to-end.

### Root cause
The remaining challenge was to carry the already-correct horizon-aware architecture fully through the final product horizon and confirm:
- no missing horizon lists
- no feature asymmetry
- no artifact collisions
- no scheduler/promotion contamination across horizons

The underlying cause was not a brand-new architecture defect.  
The issue was ensuring the final product horizon was treated as a true first-class ML citizen everywhere required.

### Full fix set
The same clean horizon-aware training/evaluation/promotion architecture now applies to 60c.

That means:
- `outcome_60c` dataset support
- 60c training paths for XGBoost / LSTM / Transformer
- 60c artifact naming
- 60c metadata / contract routing
- 60c scheduler support
- 60c promotion-root separation
- 60c compatibility with the feature-contract parity fixes introduced in Issue 16

### Impact
Issue 17 completed the multi-horizon ML foundation.

The system now supports true ML training across:
- 1c
- 5c
- 15c
- 60c

### Current interpretation
Issue 17 is fully closed.

---

## Issue 18 — Bring low-data tickers (PCG, SMCI) to promotable depth

**Historical status:** Open.  
**Current status:** Still open.

### What it means
Certain tickers still lack sufficient historical depth or qualifying data conditions to support promotion.

### Why it matters
A universal trading system cannot remain biased toward only data-rich symbols if the roadmap intends broad symbol coverage.

### What it is expected to solve
- data sufficiency for low-depth symbols
- promotion viability for currently blocked tickers
- a cleaner low-history path for universal symbol coverage

### Why it remains open
This issue was not superseded by the multi-horizon work.  
The multi-horizon work expanded what the system can do across horizons, but it did not guarantee deep promotable training history for every ticker.

### Current interpretation
Issue 18 remains the last numbered issue still open.

---

# 4. DRIFT / RESIDUAL TRACKER

D2. UTC vs session alignment  
D3. Backfill window limitation  
D4. Cold-start data gaps  
D5. Historical continuity gap  
D7. Anchor boundary edge-case  
D8. Feature vs anchor timing mismatch  
D10. Control-state ambiguity  

## Closed residual item

D12. Training row eligibility tied to all-horizon `outcome_filled`  
**Status:** Closed by Issue 14.

### Why it was removed from active residual risk
D12 was no longer merely a residual concern.  
It was promoted into Issue 14, solved directly, and is now a closed core item rather than an active drift item.

---

# 5. CURRENT ML SYSTEM STATE

## Current

The system now supports true ML artifacts for:
- 1c
- 5c
- 15c
- 60c

Artifacts are horizon-specific, for example:
- `xgb_{ticker}_1c.pkl`
- `xgb_{ticker}_5c.pkl`
- `xgb_{ticker}_15c.pkl`
- `xgb_{ticker}_60c.pkl`

Equivalent horizon-separated naming also exists for:
- LSTM
- Transformer
- metadata
- manifest identity
- active roots
- arch state files for non-default horizons

Contract enforcement remains active and validated.  
Loaders continue to require metadata compliance.

## What is now implemented

- Per-horizon dataset independence
- 5c ML
- 15c ML
- 60c ML
- horizon-aware training / evaluation routing
- horizon-aware artifact isolation
- scheduler-managed normalized training-table synchronization

## What is not yet implemented

- multi-horizon canonical forecasting
- user-selectable primary runtime horizon
- cross-horizon alignment / contradiction logic
- trade-plan synthesis from horizon-specific forecasts
- market-state-aware adaptive feature weighting
- pure canonical-probability-only position sizing
- final convergence from parallel-vs-cascade to one permanent winning architecture

---

# 6. CURRENT DATA PIPELINE

## High-level pipeline

`price_bars_1m → snapshots → outcome_* → snapshots_1m_normalized → features → ML → decision engine → UI`

## Persistence state

- All tracked tickers are written to the DB via the background logger
- Persistence no longer depends on whether a ticker is selected in the UI

## Outcome generation

`fill_outcomes()` remains the source of truth for outcome-label generation over the bar-horizon schema.

## Normalized training-table synchronization

The system now enforces operational synchronization through scheduler-managed normalization logic.

The effective guarantee is:

`snapshots fingerprint changes → ensure_normalized_training_table(...) → snapshots_1m_normalized refreshed if needed`

## Why this matters

A live research / decision system cannot rely on:
- user focus
- manual repair
- remembered operational steps

for valid training data.

This pipeline is now:
- horizon-aware
- synchronized
- materially safer against stale normalized training state

---

# 7. FULL ARCHITECTURE — CURRENT SYSTEM

## 7.1 Feature ingestion

### Entry point
`market_state.py`
- `build_market_state(...)`

### Purpose
This is where the live market slice is assembled and the runtime input object is constructed.

### Primary inputs
- prices
- walls / level context
- broader market context
- DB handle / stored state
- session/runtime context
- derived state written by the broader snapshot / feature pipeline

### Output
- `SignalInput`

### Why this matters
`SignalInput` is the common raw/context container for the downstream runtime stack.

---

## 7.2 Feature transformation

### Orchestration
`signals.py`
- `compute_signals(...)`
- `_compute_signals_impl(...)`

### Runtime sub-layers consuming `SignalInput`
- `rules_engine.compute_rules(...)`
- `volatility_regime.classify_volatility_regime(...)`
- `regime_engine.classify_regime(...)`
- `prediction_engine.build_ml_snapshot_for_fusion(...)`

### What this means
Features are **not** all consumed by one universal flat weighted formula at the point of ingestion.

Instead:
- raw/context features are assembled first
- different runtime layers consume the same input differently
- model-ready feature snapshots are then built for ML/fusion use

### Horizon-aware extension
For training and model preparation, feature transformation now also supports product-horizon parity across:
- 1c
- 5c
- 15c
- 60c

This includes symmetric rule spread and confidence features for product horizons.

### Why this matters
This architecture keeps:
- raw market state
- rule interpretation
- regime interpretation
- feature engineering
- model inference

as related but distinct layers.

---

## 7.3 Model layer

### Current model families
- XGBoost
- LSTM
- Transformer

### Current ML horizon set
- 1c
- 5c
- 15c
- 60c

### What happens here
The model stack is now multi-horizon in training and evaluation.

For each supported horizon, the system can:
- build a dataset
- train models
- save artifacts
- evaluate those artifacts
- archive / promote them without cross-horizon collision

### Runtime note
The live runtime is still currently 1c-centric by policy, but the model layer beneath it is now genuinely multi-horizon-capable.

---

## 7.4 Fusion layer

### Current fusion mechanism
`bayesian_fusion.fuse(...)`

### Current role
Fusion takes relevant model and contextual evidence and resolves it into a combined forward posterior for the active runtime horizon.

### Current limitation
Fusion is **not yet** multi-horizon canonical fusion.

It is still serving the current runtime decision horizon rather than fusing all four product horizons into one cross-horizon decision object.

### Why this matters
This is the exact architectural boundary between:
- current system state
and
- the next major phase

The next phase is not “more ML.”  
The next phase is:
- **Multi-Horizon Decision Engine**
which will require a multi-horizon fusion / alignment layer above today’s per-horizon outputs.

---

## 7.5 Decision layer

### Current decision object
`CanonicalForecast`

### Current runtime decision rule
All tradable live decisions must derive from:
- canonical direction
- canonical probabilities
- canonical confidence
- canonical provenance

### Current reality
That canonical object remains tied to the current runtime design, which is still effectively:
- one active horizon truth at a time

### Future extension
The system is headed toward:
- `canonical_1c`
- `canonical_5c`
- `canonical_15c`
- `canonical_60c`
followed by:
- multi-horizon alignment
- primary-horizon selection
- one unified final trade decision

---

## 7.6 Weighting (current + future)

### Current weighting state
The system does **not** use one explicit central table of raw feature weights.

Instead, weighting occurs in layers:

#### Rules layer
Thresholds / logic / pattern interpretation

#### Volatility / regime layers
Policy and contextual interpretation

#### ML models
Implicit learned importance

#### Fusion layer
Posterior combination

#### Decision layer
Canonical confidence / probability followed by policy downgrades

### What is true today
The system is:
- partially weighted
- partially learned
- partially policy-shaped

but not yet fully adaptive by identified market state.

### Future weighting direction
Confirmed future enhancement:
- **market-state-aware adaptive feature weighting**

Examples:
- in unstable volatility, continuation evidence should be trusted differently than in stable trend expansion
- structural liquidity or hedging context should alter how much influence certain evidence receives
- weighting should adapt by regime rather than remain fixed

### Position-sizing refinement
Confirmed future enhancement:
- move sizing to canonical-probability / canonical-forecast-based sizing only
- not confluence-count-based scaling

This was explicitly chosen and remains a required future refinement.

---

# 8. MODEL ARCHITECTURE CLARIFICATION

## 8.1 Training layer
Parallel and Cascade are currently:
- training / evaluation architectures
- not competing live runtime authorities

## 8.2 Runtime layer
The live app uses:
- one combined runtime decision stack
- one canonical decision truth
- one current active runtime authority

## 8.3 Meaning of the three terms

### Combined stack
The runtime decision pipeline that turns all relevant evidence into one live trade decision.

### Parallel stack
A training/model-family architecture in which models operate independently and are compared or fused later.

### Cascade stack
A training/model-family architecture in which later stages depend on prior stages in a sequential structure.

## 8.4 Promotion rule
Parallel and Cascade candidates may be evaluated and promoted into active.

The combined runtime stack is not itself promoted to parallel or cascade.

Instead:
- trained model families produce candidate artifacts
- promotion selects the winning artifact family
- the live combined runtime stack consumes the active artifacts for the relevant live horizon policy

## 8.5 Current and future distinction
Current:
- one live runtime decision truth
- multi-horizon training/evaluation foundation underneath

Future:
- multi-horizon combined decision engine above the horizon-specific ML artifacts

---

# 9. DECISION AUTHORITY RULES

## Current runtime decision authority
Only:
- `CanonicalForecast`

## CanonicalForecast governs
- direction
- probabilities
- confidence
- gates
- readiness
- conviction seed
- final signal alignment

## What must NOT act as independent decision authority
- historical empirical 5c context
- confluence counts
- raw rule outputs
- synthetic override probabilities
- duplicate inference-path outputs
- fusion-unavailable fallback posteriors
- non-primary horizon outputs acting independently without future multi-horizon decision-engine logic

### Why this matters
The system must know exactly which object owns the trade decision.  
If multiple submodules can each silently become the authority, the system loses integrity.

## Future decision-authority extension
Future multi-horizon design does **not** mean multiple independent decision authorities.

It means:
- multiple horizon-specific forecasts
- one explicit primary horizon
- one explicit supporting-horizon interpretation layer
- one final unified runtime decision truth

That rule is non-negotiable.

---

# 10. NON-TRADABLE STATES

If canonical provenance indicates there is no real usable posterior, including:
- `fusion_unavailable`
- `missing_canonical_fallback`

then:
- the system must force `WAIT`
- a directional trade is not tradable

### Why this matters
This prevents the system from turning uncertainty or missingness into false confidence.

---

# 11. CONVICTION MODEL

## Current rule
Conviction is seeded from:
- canonical confidence
- canonical dominant-probability margin

## Environmental modifiers
Conviction may then be downgraded by environment, structure, or policy.

## Hard rule
Environmental layers may not invent greater conviction than the canonical forecast supports.

### Why this matters
Conviction is subordinate to canonical truth, not an independent authority.

---

# 12. MULTI-HORIZON ML FRAMEWORK — DESIGN & USAGE

## 12.1 Overview

The system now supports independent ML training across multiple forward horizons:

- 1c
- 5c
- 15c
- 60c

This is **not** one model predicting many horizons inside one undifferentiated output.  
This is a set of independent models trained on the same underlying data but with different forward targets.

## 12.2 Horizon definitions

Each horizon corresponds to its own label column:

- 1c → `outcome_1c`
- 5c → `outcome_5c`
- 15c → `outcome_15c`
- 60c → `outcome_60c`

Each model is trained only on rows where that specific target exists.

## 12.3 Model separation

Each horizon produces its own:
- XGBoost model
- LSTM model
- Transformer model
- metadata
- manifests
- cache identity
- promotion path
- active-root separation for non-default promoted lanes

No horizon overwrites another.

## 12.4 Conceptual role of each horizon

### 1c — Execution horizon
- shortest-term prediction
- entry timing
- tight stop
- smallest target
- fastest trade-management cycle

### 5c — Immediate directional horizon
- short-term scalp direction
- moderate stop
- moderate target
- near-term move expectation

### 15c — Intraday structure horizon
- intermediate trend / intraday directional context
- wider stop
- larger target
- more room for trade development

### 60c — Session-bias horizon
- higher-level session structure
- widest stop
- largest target
- broader directional context

## 12.5 Trade plan generation by horizon

Each horizon can ultimately generate its own:
- entry zone
- stop
- target ladder
- hold-style expectation
- confidence

These are not contradictions.  
They are different trade plans derived from different forecast horizons.

## 12.6 Current status
Training/evaluation/data support exists across all four horizons.  
Runtime combination of those horizons into one trade plan does not yet exist.

## 12.7 Next use-case direction
The future system will treat horizons as:
- entry timing
- direction confirmation
- contradiction detection
- risk adjustment
- hold-style context

but still resolve them into one final trade recommendation.

---

# 13. OPERATIONAL SYNCHRONIZATION GUARANTEE

## Problem that existed
`fill_outcomes()` could update `snapshots` while `snapshots_1m_normalized` remained stale.

## What now exists
A scheduler-managed synchronization layer ensures:
- fingerprint of training-relevant snapshot state is checked
- normalized training table is rebuilt only when needed
- successful materialization is the gate for advancing stored synchronization fingerprint

## Why this matters
The system must never again silently operate in the state:
- source data updated
- training table stale

## Current guarantee
In-repo training / scheduler / LSTM / transformer / live-server paths now force or schedule synchronization appropriately.

Out-of-band manual SQL edits remain outside repo control, which is acceptable.

---

# 14. CURRENT TRAINING VS RUNTIME USAGE

## Training
Now fully multi-horizon:
- 1c
- 5c
- 15c
- 60c

## Runtime
Still 1c-centric by current product policy.

## Meaning
The system has completed the multi-horizon learning foundation before implementing multi-horizon live decision synthesis.

That is the correct order.

---

# 15. CONFIRMED ROADMAP DECISIONS

The following future decisions were explicitly made and must remain part of the authoritative roadmap.

## 15.1 Adaptive weighting
Implement market-state-aware adaptive feature weighting.

## 15.2 Position sizing refinement
Move position sizing to pure canonical-probability / canonical-forecast-based sizing rather than confluence-count scaling.

## 15.3 Multi-horizon canonical architecture
Future roadmap must explicitly include:
- `canonical_1c`
- `canonical_5c`
- `canonical_15c`
- `canonical_60c`
- horizon-specific trade calls / bias layers
- horizon alignment logic
- user-selectable primary trade horizon
- adaptive weighting by market regime

## 15.4 Primary trade recommendation
The future system should provide:
- one primary trade recommendation based on the selected trading horizon
- one multi-horizon alignment / contradiction layer around it

## 15.5 Eventual architecture convergence
Parallel vs cascade should not remain a permanent unresolved duality forever.  
Convergence to one winning architecture remains a future direction, after enough evidence.

---

# 16. NEXT MAJOR PHASE — MULTI-HORIZON DECISION ENGINE

This is the most important next step.

## Why it is next
The system now has:
- multi-horizon data
- multi-horizon training
- multi-horizon artifacts
- synchronized training infrastructure

What it does **not** yet have is:
- one logic layer that turns those horizon outputs into one coherent trade decision

That makes the Multi-Horizon Decision Engine the correct next phase.

## What this phase should do

### 16.1 Horizon alignment detection
Determine whether horizons are:
- aligned
- mixed
- contradictory
- weak / low-confidence

### 16.2 Primary-horizon selection
Support a selected primary horizon depending on trading intent, such as:
- scalping → 1c or 5c
- intraday → 15c
- session-bias / longer hold → 60c

### 16.3 Supporting-horizon interpretation
Use non-primary horizons as:
- confirmation
- contradiction
- timing filter
- risk modifier

### 16.4 Trade-plan synthesis
Convert horizon forecasts into:
- entry
- stop
- target(s)
- expected hold style
- confidence
- risk note

### 16.5 One final runtime truth
Despite multi-horizon analysis, the runtime must still end with:
- one unified final decision truth

## Why this matters
This is the phase that turns the system from:
- multi-horizon predictive modeling
into:
- institutional-grade multi-horizon trade intelligence

---

# 17. GUIDING PRINCIPLE FOR THE FUTURE SYSTEM

The system evolves from:
- single canonical forecast
→
- multi-horizon ML foundation
→
- multi-horizon canonical decision system
→
- adaptive, market-aware predictive engine

BUT ALWAYS:

> ONE unified runtime decision truth

Never:
- multiple competing runtime forecasts
- multiple independent runtime decision engines
- ambiguous decision ownership

---

# 18. STATUS SUMMARY

| Component | Status |
|----------|--------|
| Issue 11 (restore valid 1c ML stack) | Complete |
| Issue 12 (UI null-guard hardening) | Complete |
| Issue 13 (decision engine alignment) | Complete |
| Issue 14 (per-horizon dataset independence) | Complete |
| Issue 15 (5c ML) | Complete |
| Issue 16 pre-step (15c/60c labels + normalization) | Complete |
| Issue 16 operational synchronization | Complete |
| Issue 16 (15c ML) | Complete |
| Issue 17 (60c ML) | Complete |
| Issue 18 (low-data ticker promotion depth) | Open |
| Adaptive weighting | Planned |
| Pure canonical sizing refinement | Planned |
| Parallel vs cascade convergence | Future decision |
| Multi-horizon canonical framework | Planned |
| Multi-Horizon Decision Engine | **NEXT** |

---

# 19. OPERATIONAL HANDOFF SUMMARY

If a later conversation needs to resume from this file, the most important truths are:

1. Issue 13 is complete
2. `CanonicalForecast` is the current live runtime decision authority
3. The system now uses one combined runtime decision stack
4. Parallel and Cascade are still training/evaluation architectures
5. Issues 14–17 are complete
6. The system now supports true ML training for 1c / 5c / 15c / 60c
7. Normalized training data is now scheduler-managed and synchronized
8. Issue 18 is still open
9. The next major step is **Multi-Horizon Decision Engine**
10. After the scheduler completes the current run, the next design/construction conversation should focus on:
   - cross-horizon alignment
   - primary-horizon authority
   - trade-plan synthesis
   - one unified multi-horizon runtime decision truth

---

# 20. END OF MASTER DOCUMENT


====================================================================================================
# SOURCE DOCUMENT: Ed_Trading_System_MASTER_v12_additive_extension.md
**Date:** 2026-04-02 | **Role:** MASTER SPEC v12 — additive extension: full pipeline mapping, XGB/LSTM/Transformer stack interaction, similarity tiers | **Original size:** 49,181 bytes
====================================================================================================


# ED INSTITUTIONAL PREDICTIVE TRADING ENGINE
## MASTER SPEC + LIVE ISSUE TRACKERS (AUTHORITATIVE MASTER — V12 ADDITIVE EXTENSION TO V11)

---

# 5. NEW ISSUE TRACKER — POST MULTI-HORIZON FOUNDATION / LIVE-RUNTIME INTEGRITY

This section is an additive continuation of the V11 authoritative master. It does **not** replace any prior sections.  
It extends the issue history, architecture clarification, runtime/data interpretation, and future roadmap integration after the live QQQ vs SPY divergence investigation, the tier-selection audit, the logging architecture audit, and the SSE / polling / cache coherency audit.

The governing intent of this extension is:

- preserve the existing V11 architecture and issue history
- add the newly discovered runtime defects and design gaps without rewriting prior history
- explicitly separate:
  - data existence
  - data logging density
  - similar-set filtering
  - model availability
  - fusion availability
  - decision authority
  - transport/freshness architecture
- preserve one-runtime-truth policy while correcting live architectural incoherency

The key new realization is that the system’s current limitations are **not** reducible to “QQQ has less data than SPY.”  
The actual condition is more precise:

- QQQ has meaningful historical data
- the current similar-set selection path can reduce that historical data to an underpowered subset
- the current tier acceptance threshold is misaligned with downstream empirical viability requirements
- the live UI transport and backend recompute model can produce a mixed-freshness state in which price is newer than decision logic
- the current logging architecture is persistent for the core ticker universe but not yet true persistent all-tracked continuous logging
- the tier-driving features used in runtime similarity selection have not yet been fully audited, justified, or adaptively validated

---

## OPEN

19. Tier selection logic failure: similarity-vs-viability mismatch  
20. Real-time decision coherency failure: mixed-freshness SSE / polling / cache architecture  
21. Tier-driving feature integrity gap: auditability, justification, and adaptive validation  
22. Persistent logging coverage limitation for non-core tracked symbols  
23. Live transport / decision-bundle redesign for coherent SSE decision-state delivery  
24. Runtime decision authority rewrite for multi-horizon canonical integration  
25. Similarity framework evolution: from heuristic static tiers to validated adaptive similarity policy

---

# 6. ISSUE HISTORY — COMPLETE RECORD (NEW ISSUES)

## Issue 19 — Tier selection logic failure: similarity-vs-viability mismatch

**Historical status:** Newly discovered during live multi-horizon runtime validation.  
**Current status:** Open.  
**Severity:** High.  
**Category:** Runtime empirical decision integrity / data selection.  

### Problem definition

The runtime similar-set selection logic uses a tiered similarity ladder and stops when it finds the first tier containing at least a minimum number of rows. However, the threshold used to accept a tier is lower than the threshold required by downstream empirical horizon probability construction.

The system currently behaves conceptually like this:

- select the first similarity tier with at least 20 rows
- pass those rows to empirical horizon probability construction
- require at least 30 labeled samples to emit valid empirical probabilities

This creates a structural mismatch between:
- **tier acceptance**
and
- **statistical viability**

The effect is that the system can select a tier that is “acceptable” by selection policy but still unusable by empirical modeling policy.

### Why it mattered in the live QQQ event

For the investigated QQQ live failure state, the measured tier pools were:

- Tier 1 = 0
- Tier 2 = 3
- Tier 3 = 26
- Tier 4 = 105
- Tier 5 = 434

The system accepted Tier 3 because 26 is greater than or equal to the current “minimum rows to stop tier expansion” threshold.  
But the empirical horizon logic then withheld probabilities because 26 was still below the required minimum labeled sample threshold of 30.

That produced the following runtime chain:

- tier selected = Tier 3
- similar set size = 26
- empirical 1c/5c/15c/60c probabilities withheld
- multi-horizon bundle marked horizons unusable / non-tradeable
- no valid primary horizon
- final bias forced to `WAIT`

This was a genuine runtime failure even though broader ticker-level historical data existed.

### Root cause

The root cause is not a missing-data condition.  
The root cause is a **selection-policy defect**:

- the system prefers to stop at the most similar acceptable tier
- but “acceptable” is defined too loosely relative to downstream statistical requirements

The logic is optimizing for:
- **similarity precision**
before
- **statistical sufficiency**

That ordering is backwards for a decision system that requires valid empirical horizon estimates.

### Why it is a real design flaw, not just a threshold disagreement

This is not merely a matter of moving a number from 20 to 30.  
The deeper design flaw is that the current logic assumes the first tier with enough rows to look “usable” should be selected, even if a broader tier contains significantly more viable rows and would produce a far more stable empirical estimate.

The system therefore chooses:
- a narrower but statistically weaker set
instead of
- a broader but statistically viable set

This is especially dangerous for symbols with thinner density across high-specificity tiers.

### Full implications

Without correcting this issue, the system can:

- ignore broader, valid data pools
- fall into false `WAIT` states
- underutilize existing historical data
- create ticker asymmetry where broad symbols (SPY) remain robust while thinner symbols (QQQ or others) collapse at runtime
- confuse the operator into thinking data is missing when the real problem is selection logic

### Required correction directions

This issue must be resolved by changing selection policy so that the runtime similarity ladder does **not** stop before viability is achieved.

The candidate correction models are:

#### 19.1 Viability-first tier stopping
Continue tier expansion until:
- labeled counts reach empirical minimum viability

instead of:
- stopping at the first tier with at least the lower selection threshold

#### 19.2 Tier aggregation
Accumulate rows from progressively broader tiers until a target labeled sample floor is reached, subject to policy controls.

#### 19.3 Hybrid viability + similarity policy
Select the narrowest tier that reaches viability, or blend neighboring tiers with explicit weighting and auditability.

### What it does NOT mean

This issue does **not** imply:
- the models are broken
- the DB is empty
- the system failed to log QQQ completely
- the fusion layer is inherently wrong

It specifically identifies a runtime data-selection defect between:
- stored history
and
- empirical horizon construction

### Current interpretation

Issue 19 remains open and is now one of the most important blockers to live multi-horizon decision integrity.

---

## Issue 20 — Real-time decision coherency failure: mixed-freshness SSE / polling / cache architecture

**Historical status:** Newly discovered during live runtime freshness audit.  
**Current status:** Open.  
**Severity:** Critical.  
**Category:** Transport / runtime state coherency / live decision integrity.  

### Problem definition

The current UI/backend transport architecture does not maintain one fully coherent live decision state across price, tier inputs, and top-card decision logic.

The system currently has multiple update paths:

- full state refresh path via `_fetch_state(...)` and market-state recomputation
- SSE background refresh loop that pushes full state on a periodic cadence
- tick-patch path that updates only selected order-flow / spot-related keys on a faster cadence
- `/api/state` polling / fallback path
- `/api/state` cache branch when expiry/TTL conditions allow cached response reuse

The result is that some fields can become fresher than others.

This creates the mixed-freshness state:

- spot / price appears live
- decision logic is older
- top cards appear stale or inconsistent relative to price

### Why this matters

For a trading decision system, it is not enough that **some** fields are live.  
What matters is that the **decision-critical bundle** is coherent.

A live trading operator cannot safely rely on a UI where:

- price is current
- The Call is not
- MHAP row roles are not
- tier-driving inputs are not
- zone / vwap_side / nearest distances are not
- entry-state transitions are not

That violates live decision integrity.

### Audited finding

The code-path audit established that:

- SSE exists and can push full `MarketState` payloads
- tick-path SSE patching updates order-flow-related keys and spot, and may patch quote-derived spot fields
- tick-path patching does **not** recompute the broader decision stack
- top decision region fields remain tied to full recompute cadence rather than tick cadence
- `/api/state` may serve cached payloads under some expiry conditions
- therefore the architecture is mixed:
  - partial tick patch
  - periodic full refresh
  - polling fallback
  - cache reuse

### Root cause

The root cause is not SSE itself.  
The root cause is that the transport/recompute model was built as a hybrid:

- use partial fast patches for selected fields
- use slower full recompute for broader logic

This is acceptable for a general dashboard.  
It is not acceptable for a live top-decision trading system.

### Full implications

Without correcting this issue, the system can display:

- new price with old tiers
- new price with old MHAP
- new price with old The Call
- new order-flow with old structural state
- new spot while nearest-above / nearest-below distances remain stale until next full recompute
- stale entry-state relative to price movement

This is one of the most important architectural integrity issues discovered in the session.

### Required correction directions

The system must move to a coherent live decision-bundle architecture in which all decision-critical fields are updated together.

That does **not** necessarily mean full recompute on every tick.  
But it **does** mean that:
- partial patches must not create decision-state incoherency
- tier-driving inputs and decision outputs must be recomputed on meaningful triggers
- the top decision region must be treated as one synchronized live system

### Current interpretation

Issue 20 remains open and is a precondition for trusting live decision outputs.

---

## Issue 21 — Tier-driving feature integrity gap: auditability, justification, and adaptive validation

**Historical status:** Newly surfaced during tier audit.  
**Current status:** Open.  
**Severity:** High.  
**Category:** Feature engineering / runtime similarity framework / explainability.  

### Problem definition

The runtime similar-set framework currently uses manually selected, heuristic-driven features to define similarity tiers.

The currently verified tier-driving features include:
- zone
- vwap_side
- nearest_above_dist bucket
- nearest_below_dist bucket
- broad ticker/timeframe identity at lower-specificity levels

These features were chosen because they approximate structural market similarity.  
However, they have not yet been fully validated through:

- feature audit logs
- similarity inspection tooling
- ablation testing
- conditional probability validation
- adaptive weighting studies
- learned similarity comparison

### Why this matters

It is not enough for a feature to be intuitively reasonable.  
For a production-grade similarity framework, the system must know:

- why the feature is included
- how strongly it contributes
- whether it improves or harms outcome discrimination
- whether it should be mandatory, weighted, bucketed differently, or removed

Without this, the similar-set engine remains:
- heuristic
- static
- under-audited

### Root cause

This issue exists because the system has historically focused on:
- getting the data pipeline correct
- getting models trained
- getting runtime logic coherent

The similarity framework has therefore remained a mostly hand-authored approximation layer rather than a fully validated statistical subsystem.

### Required capabilities

This issue requires the following new tooling and methodology:

#### 21.1 Feature audit layer
For every live decision, log:
- features used to select the tier
- tier selected
- row counts at each tier
- which constraints were applied / dropped
- downstream empirical viability

#### 21.2 Similarity inspection tooling
Allow inspection of:
- the actual rows in the selected similar set
- feature distributions within those rows
- outcome distribution by selected tier
- ticker asymmetry and density patterns

#### 21.3 Feature validation methodology
Introduce:
- ablation analysis
- conditional probability checks
- SHAP / model importance cross-reference where appropriate
- feature redundancy analysis
- bucket-quality validation

#### 21.4 Adaptive framework evolution
Longer term, move from:
- static similarity tiers
toward:
- validated adaptive or weighted similarity selection

### Current interpretation

Issue 21 remains open and is essential for the eventual institutional-grade validation of the similarity framework.

---

## Issue 22 — Persistent logging coverage limitation for non-core tracked symbols

**Historical status:** Newly clarified by logging architecture audit.  
**Current status:** Open.  
**Severity:** High.  
**Category:** Data collection architecture / persistence density.  

### Problem definition

The current system does have background logging, but it is not yet equivalent to a true persistent all-tracked-ticker continuous logging architecture.

The audit confirmed:

- core tickers are always in the background logging universe
- QQQ is included in the core ticker set
- additional symbols can be enrolled when viewed / registered / persisted
- logging cadence is finite and throttled
- snapshot row insertion is capped (default at most one insert per minute per ticker)
- background loop is session-gated
- the system is not currently “all symbols, all sessions, all times”

### Why this matters

For the user’s actual intended workflow, a ticker that has been brought into the system should not later become history-thin merely because it was not actively selected for some period.

The required practical standard is:

- once a symbol is intentionally tracked, it should continue building history in the background
- symbol history should not depend on recent UI attention
- data density should improve over time, not reset to thin slices of incidental coverage

### Root cause

The current logger design optimizes for:
- core symbol persistence
- manageable runtime cost
- throttled snapshot writes
- a finite tracked universe

That is reasonable for a development-stage or bounded-universe console.  
It is not yet aligned with the user’s intended research/trading memory model.

### Required correction directions

The logging architecture must evolve toward:

#### 22.1 Persistent tracked-symbol universe
A symbol that has been explicitly added/used should remain tracked unless intentionally removed.

#### 22.2 True background density accumulation
Tracked symbols should continue accumulating historical data without depending on current selection.

#### 22.3 Explicit session policy
The system should formally decide whether to:
- remain RTH-only
- include premarket/postmarket
- or use configurable session modes

#### 22.4 Density-aware logging
The long-term architecture should consider the impact of throttle, cadence, and symbol-universe size on historical usefulness for similarity and ML support.

### Current interpretation

Issue 22 remains open and extends the spirit of Issue 10 from “persistence exists” to “persistence density and tracked-universe continuity are sufficient for real decision quality.”

---

## Issue 23 — Live transport / decision-bundle redesign for coherent SSE decision-state delivery

**Historical status:** Newly surfaced during SSE / polling audit.  
**Current status:** Open.  
**Severity:** Critical.  
**Category:** Runtime transport architecture.  

### Problem definition

The top decision region currently behaves as a composition of fields that are not guaranteed to share one update boundary.

The user’s top decision region includes:

- Right Now
- WTDS
- The Call
- MHAP
- hidden tier-driving inputs that determine similar-set selection and final decision behavior

These fields should behave as one coherent live decision system.

They currently do not.

### Required architectural rule

The correct rule is:

- if a field can materially affect a trade decision, it is decision-critical
- decision-critical fields must be grouped into one coherent live update bundle
- that bundle must be transmitted and rendered as one synchronized state

This issue is distinct from Issue 20 because it focuses specifically on the transport/payload architecture needed to implement coherency.

### Required correction directions

A new live-bundle architecture must be defined such that:

- all decision-critical top-region fields are recomputed together
- SSE transmits the coherent bundle
- tick-patch behavior is either:
  - constrained to non-decision fields
  - or integrated into a trigger-based full decision recompute model
- polling and cache paths must not be allowed to degrade decision-field freshness silently

### Current interpretation

Issue 23 remains open and should be resolved together with Issue 20.

---

## Issue 24 — Runtime decision authority rewrite for multi-horizon canonical integration

**Historical status:** Newly clarified during multi-horizon design + failure analysis.  
**Current status:** Open.  
**Severity:** High.  
**Category:** Decision layer / future architecture.  

### Problem definition

V11 established one-runtime-truth policy around canonical decision authority.  
The multi-horizon foundation expanded the horizon universe, but runtime still effectively behaves as a single-horizon authority system with partial multi-horizon overlays.

The new failures make clear that the future runtime authority model must explicitly incorporate:

- multi-horizon canonical selection
- primary/supporting horizon roles
- top-bundle coherency
- decision-critical trigger-based refresh
- empirical / fusion / risk / timing coordination
- consistent tradeability fallback when one horizon is statistically weak

### Why this matters

Without a formal rewrite of runtime decision authority for multi-horizon canonical architecture, future multi-horizon rollout risks:
- hidden secondary authorities
- inconsistent fallback behavior
- stale alignment logic
- mismatch between transport and authority

### Required directions

The future decision authority rewrite must explicitly define:

- what constitutes the primary horizon
- what may downgrade but not override
- how missing empirical horizon support is handled
- how canonical fusion interacts with withheld empirical tiers
- how a coherent top decision bundle is formed and streamed

### Current interpretation

Issue 24 remains open and belongs directly on the multi-horizon canonical roadmap.

---

## Issue 25 — Similarity framework evolution: from heuristic static tiers to validated adaptive similarity policy

**Historical status:** Newly articulated from combined tier/data-feature findings.  
**Current status:** Open.  
**Severity:** Medium-high.  
**Category:** Future architecture evolution.  

### Problem definition

The current similarity framework is:
- manually constructed
- heuristic-driven
- static
- only partially auditable

That is acceptable as an intermediate design, but not as an institutional-grade final framework.

### Required evolution path

The system must move through the following stages:

#### 25.1 Stage A — explicit auditability
Expose exactly how tiers are built and why rows are selected.

#### 25.2 Stage B — statistical validation
Prove that the selected features and buckets improve outcome discrimination.

#### 25.3 Stage C — weighted adaptive similarity
Allow the system to widen/narrow or weight dimensions according to evidence.

#### 25.4 Stage D — learned similarity (future)
Explore clustering / embedding / learned-distance approaches if and only if they outperform validated heuristic policies.

### Current interpretation

Issue 25 remains open and is a future architecture evolution item rather than an immediate blocker, but it must be preserved on the roadmap.

---

# 7. UPDATED SYSTEM STATE (POST V12 ADDITIVE FINDINGS)

The system now has:

- Correct bar-based horizons
- Canonical anchor
- Honest missingness in production decision flow
- Auto-expanding universe with background persistence for the current core tracked architecture
- Fully hardened UI against null / missing render crashes
- Valid restored 1c ML stack for compliant tickers
- Clean per-horizon dataset independence
- True ML training support for 1c, 5c, 15c, and 60c
- Populated and verified `outcome_15c` and `outcome_60c`
- Scheduler-managed synchronization between `snapshots` and `snapshots_1m_normalized`
- Horizon-aware manifests, cache keys, metadata, artifact names, promotion roots, and archive paths
- CanonicalForecast as the current runtime decision truth source in the pre-multi-horizon-runtime-authority system
- Single current live inference truth path for the active runtime stack
- Explicit decision trace logging through `DECISION_BUNDLE`
- Fusion-unavailable states explicitly forced to `WAIT`
- Conviction bounded by canonical forward probability / confidence rather than allowed to outrun canonical strength
- Verified background logging for core ticker universe, including QQQ
- Verified existence of meaningful stored QQQ history
- Verified tier-pool asymmetry between QQQ and SPY under live conditions
- Verified mixed-freshness transport architecture in the current SSE/polling/cache design

## Limitations (updated)

- Some tickers, especially lower-history or lower-depth cases such as PCG and SMCI, may still remain blocked by insufficient promotable depth
- Runtime decisioning is still intentionally 1c-centric by current product policy
- Multi-horizon canonical decision logic is not yet implemented
- Cross-horizon alignment, contradiction handling, and primary-horizon trade selection are not yet implemented
- Market-state-aware adaptive feature weighting is not yet implemented
- Position sizing is not yet fully driven by canonical probabilities alone
- Parallel vs cascade has not yet been converged to one permanent winning architecture
- Full scheduler completion and manifest refresh still must be run on the current workspace to finalize latest artifact evaluation state after the newest horizon additions
- Tier selection currently stops before empirical viability is guaranteed
- The current SSE/polling/cache architecture can expose newer spot than decision logic
- Decision-critical tier-driving inputs are not yet guaranteed to be refreshed coherently with top-card decision outputs
- Current logging architecture is persistent for core symbols but not yet true persistent continuous all-tracked-ticker logging
- Similarity framework features and buckets are not yet fully audited or adaptively validated

## Updated operating truth

The system is not allowed to run with multiple competing runtime decision truths.  
However, it is now additionally clear that the system is also not allowed to run with:
- one visible spot truth
- and a stale decision truth

The runtime must therefore evolve from:
- one canonical logical truth
to:
- one canonical logical truth delivered through one coherent live decision-state architecture

This is the core V12 additive insight.

---

# 8. DATA PIPELINE + FEATURE INGESTION → TRANSFORMATION MAPPING (FULL ADDITIVE CLARIFICATION)

This section is added because the newly discovered issues cannot be fully understood without a precise distinction between:

- raw data existence
- persistent logging
- derived snapshot state
- similar-set feature selection
- empirical horizon construction
- model-layer outputs
- fusion outputs
- final decision outputs

The system’s runtime data path is therefore restated here with explicit stage mapping.

---

## 8.1 Raw ingestion layer

The system ingests market and derived-state inputs through `_fetch_state(...)` and the broader server/runtime pipeline.  
At a high level, raw/near-raw runtime inputs include:

- quote / price / spot
- order-flow-derived state
- level relationships
- VWAP relationship
- broader contextual state needed to assemble `SignalInput`

These values are assembled into a full state object that is then used for:
- live UI
- snapshot persistence
- rule evaluation
- feature construction
- runtime ML inference
- empirical similar-set selection
- final decision construction

### Important current limitation
Raw spot may become fresher faster than the broader derived decision state because of the partial tick-patch path.

---

## 8.2 Snapshot persistence layer

Within `_fetch_state(...)`, after market state is built, snapshot persistence logic can run:

- build `SnapshotRow`
- insert into `snapshots` (subject to throttle)
- upsert 1m bars
- run `fill_outcomes(...)`
- schedule normalized refresh

This is the main persistence foundation for:
- historical empirical selection
- training
- diagnostics
- future replay/auditability

### Current implication for these issues
The persistence layer itself is not the root cause of the QQQ live failure.  
The QQQ live failure occurred despite meaningful stored history.

---

## 8.3 Derived runtime state layer

The runtime derives and carries fields such as:

- zone
- vwap_side
- nearest_above_dist
- nearest_below_dist
- structural/market-state labels
- other decision context fields

These fields matter because they are not only UI/state descriptors; they also become **selection features** for the similar-set engine.

This is the first major conceptual point that must be preserved:

> Some fields that look like ordinary UI state are actually decision-critical selection features.

That means they must be treated with the same freshness/integrity seriousness as price.

---

## 8.4 Similar-set feature selection layer

The empirical runtime path calls into `compute_prediction(...)`, which calls `db.get_similar_setups(...)`.  
This is where the current bar/state is matched to historical rows using the tier system.

The verified runtime tier-driving fields include:

- ticker
- timeframe
- zone
- vwap_side
- nearest_above_dist bucket
- nearest_below_dist bucket
- `outcome_1c IS NOT NULL` as the minimum row-eligibility gate for selection

This is the second major conceptual point:

> The runtime empirical path is not selecting from all history.  
> It is selecting from a heavily filtered, structure-constrained historical subset.

That is why “we have lots of QQQ data” and “the app only used 26 rows” are both true at the same time.

---

## 8.5 Similarity tiers as transformation stages

The tier framework is itself a transformation layer.

The current row set is progressively transformed from:
- broad ticker history
to
- tightly matched structural subsets

through the following approximate policy ladder:

- Tier 1: zone + vwap + both buckets
- Tier 2: zone + vwap + above bucket
- Tier 3: zone + vwap
- Tier 4: zone only
- Tier 5: ticker/timeframe/labeled baseline

This means the similar-set engine is effectively a **runtime feature-conditioned data transformation subsystem**.

It is not just a “query.”  
It is an active decision-shaping layer.

---

## 8.6 Empirical horizon transformation layer

After the similar rows are selected, `_literal_empirical_horizon(...)` computes horizon probabilities for:
- 1c
- 5c
- 15c
- 60c

This requires enough labeled samples for the requested horizon.  
If the threshold is not met, the triplet is withheld (returned as `None`).

This is the third major conceptual point:

> Similar-set selection and empirical horizon construction are separate gates.

That is why:
- a tier can be selected
- yet empirical horizon emission still fails

This separation is what exposed Issue 19.

---

## 8.7 Model-layer feature path vs empirical path

The system contains two distinct kinds of predictive machinery:

### A. Model-layer path
- XGBoost
- LSTM
- Transformer
- Monte Carlo
- Fusion
- Canonical forecast

### B. Empirical path
- similar-set selection
- empirical horizon probabilities

The live QQQ failure proved that:
- model stack can remain healthy
- fusion can remain available
- canonical stack can remain structurally present
while
- empirical multi-horizon runtime path collapses

That distinction is essential.

---

## 8.8 Final runtime state assembly

After these layers, the system assembles:
- predictive card state
- multi-horizon state
- The Call
- MHAP
- entry state
- final bias / tradeability / wait reason

This output is then transported via:
- SSE full payload refresh
- polling fallback
- cache branch
- tick-patched partial updates

That final stage is where mixed freshness becomes visible.

---

# 9. FULL MODEL LAYER INTERACTION (XGB / LSTM / TRANSFORMER) WITH THESE ISSUES

This section is added to clarify what the newly discovered defects do **and do not** imply about the model layer.

---

## 9.1 What was initially suspected

When QQQ degraded while SPY remained usable, a natural first suspicion was:

- model artifact missing
- model load failure
- feature/schema mismatch
- broken inference path

That suspicion was reasonable because those are common causes of ticker-specific failure.

---

## 9.2 What the live diagnostic proved

The live comparison showed:

- XGB available = yes
- LSTM available = yes
- Transformer available = yes
- fusion available = yes
- canonical provenance still present

for both SPY and QQQ in the compared runtime state.

That means the immediate QQQ failure was **not** caused by:
- missing active model artifacts
- broken model contracts
- absent model stack components
- total fusion collapse

---

## 9.3 Why that matters

This means the newly discovered live defect cannot be lazily attributed to “the models stopped working.”

Instead, the failure chain was:

- model stack still healthy
- fusion still available
- broader stack still alive
- empirical horizon path withheld
- multi-horizon runtime bundle found no valid primary
- final top-card decision degraded

This is actually an important system-strength signal:
- the stack did not hallucinate a false confident trade
- but it also exposes that empirical gating has become an over-powerful collapse point

---

## 9.4 XGBoost interaction

The XGB path matters in two ways:

### A. Direct runtime contribution
XGB contributes to the live model stack and therefore affects fusion/canonical behavior.

### B. Feature contract standard
Because XGB uses explicit feature lists and contract validation, it remains a reference point for:
- whether runtime model schema is coherent
- whether the system is correctly assembling model inputs

For the QQQ event, XGB being available helped rule out:
- immediate model load failure
- broad feature-vector construction failure

---

## 9.5 LSTM interaction

The LSTM path depends on:
- recent snapshot availability
- sequence readiness
- sufficient historical row continuity for inference windows

The QQQ event did **not** show LSTM collapse as the primary fault.  
But this issue still matters for future robustness because thinner logging density and ticker asymmetry can degrade sequence quality over time.

So while LSTM was not the direct root cause here, logging architecture limitations (Issue 22) are still relevant to LSTM quality.

---

## 9.6 Transformer interaction

Transformer availability also remained positive in the live comparison.  
That means the tier-selection defect did not come from transformer artifact or sequence collapse.

However, just like LSTM, transformer robustness still depends on:
- sequence depth
- logging density
- normalized data freshness

Therefore Issue 22 still indirectly matters to transformer quality over the long term.

---

## 9.7 Shared model-layer lesson

The important lesson is:

> The model layer and the empirical tier layer are not failing for the same reasons.

The model layer can be healthy while the empirical horizon path is not.  
That is precisely what happened.

This means the system must never conflate:
- model availability
with
- empirical horizon viability

They are separate diagnostics and separate failure domains.

---

## 9.8 What these findings require from the model layer architecture

The runtime architecture must expose separate health states for:

- model stack health
- empirical horizon health
- fusion availability
- canonical availability
- decision-bundle coherency

Without this separation, the operator can misread a tier-selection failure as a model collapse, or vice versa.

---

# 10. FULL FUSION LAYER IMPACT (BAYESIAN LAYER BEHAVIOR UNDER FAILURE)

This section clarifies how the Bayesian fusion layer behaves relative to the newly discovered runtime defects.

---

## 10.1 Existing fusion architecture context

Per V11, the fusion layer sits after:
- model stack outputs
and before:
- decision policy / canonical direction

Fusion remains the consensus engine and must remain late in the stack.

---

## 10.2 What the QQQ event showed

The QQQ event demonstrated that:
- fusion can remain available
- canonical provenance can remain present
- yet final top-decision outputs can still degrade

This is because the new failure occurred in the empirical multi-horizon similarity path, not in fusion itself.

---

## 10.3 Why this matters conceptually

Without careful interpretation, one might think:

> if fusion is alive, the UI should never collapse

That is false.

Fusion being alive means:
- the model consensus engine is still functioning

It does **not** guarantee:
- the empirical multi-horizon path is viable
- the current primary-horizon selection has valid empirical support
- the transport architecture is coherent

---

## 10.4 Fusion vs empirical path under failure

The live failure shows a three-layer distinction:

### Layer A — model/fusion truth
Still functioning

### Layer B — empirical horizon truth
Withheld due to insufficient selected-similar labeled samples

### Layer C — final runtime decision bundle
Forced into `WAIT` because primary horizon could not be validated

This distinction is crucial for future decision policy design.

---

## 10.5 What the Bayesian layer should and should not do

The fusion layer should:
- continue to aggregate model evidence
- provide canonical directional context
- remain the forward probabilistic consensus source

The fusion layer should **not**:
- silently replace all empirical horizon controls without explicit policy
- hide empirical horizon failure
- produce an unqualified trade simply because it is still available

That said, the current architecture may still be too brittle if empirical withholding can fully collapse the decision layer when fusion remains strong.

That is not a statement that fusion should override.  
It is a statement that decision policy must become more explicit about:
- when empirical horizon absence means “degrade confidence”
- when it means “block trade”
- when canonical fusion can remain directional context without granting execution authority

---

## 10.6 Required fusion-related evolution

The decision layer must explicitly define the relationship between:

- fusion/canonical forward truth
- empirical horizon validity
- primary horizon authority
- fallback / degrade policy

This belongs directly in the future multi-horizon decision authority rewrite.

---

## 10.7 Bayesian layer implication for transport architecture

Because fusion/canonical values are part of the decision-critical top bundle, they must be transported coherently with:
- tier-driving inputs
- MHAP
- The Call
- final bias

Otherwise the system risks:
- fresh price
- old fusion
- old MH state
- old tradeability

That is unacceptable.

---

# 11. FULL DECISION LAYER AUTHORITY LOGIC REWRITE (REQUIRED)

This section is intentionally detailed because the new failures reveal that future multi-horizon deployment cannot rely on incremental ad hoc adjustments. It needs an explicit runtime authority model.

---

## 11.1 Existing authority context

V11 established:
- one runtime truth
- CanonicalForecast as the current central runtime decision object
- no mixed-horizon probability abuse
- no synthetic directional confidence
- explicit `WAIT` when fusion unavailable

That remains valid and must not be weakened.

---

## 11.2 New authority problem surfaced by V12 findings

The current system now contains at least four meaningful authority domains:

1. live spot / quote truth  
2. model/fusion/canonical truth  
3. empirical multi-horizon similarity truth  
4. final UI / The Call / MHAP truth  

The newly discovered problem is that these truths can become temporally misaligned.

This creates a deeper requirement:

> one logical runtime truth is necessary, but not sufficient;  
> the system also needs one coherent **decision-time boundary**

---

## 11.3 Required decision authority rewrite

The future runtime authority model must answer all of the following explicitly:

### A. What owns direction?
- current canonical / selected primary horizon / final policy synthesis

### B. What owns execution timing?
- lower-horizon tactical layer (e.g. 1c) under defined authority constraints

### C. What owns tradeability?
- final policy synthesis after:
  - empirical viability
  - contradiction handling
  - gating
  - risk controls

### D. What may downgrade but not override?
- support/contradiction horizons
- environmental constraints
- empirical weakness
- risk layers

### E. What may force `WAIT`?
- no valid primary horizon
- fusion unavailable
- structural contradiction
- no coherent decision state
- stale decision bundle
- no viable empirical support under policy

### F. What may not silently replace authority?
- stale top-card state
- spot-only patching
- support horizon disagreement
- UI convenience logic
- partial transport patch

---

## 11.4 Canonical multi-horizon integration requirement

The authority rewrite must eventually move toward:

- canonical_1c
- canonical_5c
- canonical_15c
- canonical_60c

with:
- user-selected or policy-selected primary horizon
- supporting horizon assessments
- contradiction handling
- one final trade decision truth

But this must only happen once:
- real-time coherency is fixed
- tier viability logic is fixed
- empirical-vs-fusion fallback policy is explicitly defined

---

## 11.5 Entry-state authority

The new entry-state work uncovered an important sub-authority distinction:

- thesis authority is not identical to execution-entry authority

For example:
- 15c may govern trade thesis
- 1c may govern timing
- 60c may govern structural carry / hold style

This means the decision authority rewrite must preserve:
- one final decision truth
while allowing:
- multiple sub-authority roles within that truth

This is not contradiction.  
It is hierarchy.

---

## 11.6 Required output contract for the rewritten decision layer

The future final decision layer must emit one coherent object containing at least:

- final_bias
- final_confidence
- final_quality
- final_tradeable
- primary_horizon
- support_horizon_summary
- alignment_state
- contradiction_state
- entry_state
- entry_display_text
- stop_display_text
- target_ladder
- hold_style
- size_modifier
- risk_note
- wait_reason
- decision_provenance
- freshness / coherence metadata

That object must become the one transport-authoritative live decision bundle.

---

# 12. FULL PARALLEL VS CASCADE IMPLICATIONS

This section is included because the user explicitly requested that V12 not omit architecture-layer implications, including parallel vs cascade.

---

## 12.1 Current state from V11

V11 preserved:
- parallel and cascade training/evaluation architectures
- no final permanent convergence yet
- winner selection/promotion still part of future architecture evolution

The new V12 issues do **not** invalidate that setup.  
However, they do change how parallel/cascade results should be interpreted at runtime.

---

## 12.2 Why parallel vs cascade is not the root cause here

The live QQQ failure occurred even though:
- model availability remained positive
- fusion remained available

Therefore this failure did not emerge because:
- parallel won when cascade should have won
- cascade artifact failed
- promotion chose the wrong family

That means V12 does **not** identify a direct parallel-vs-cascade defect.

---

## 12.3 Why parallel vs cascade still matters

Even though it was not the direct root cause, the current issues still affect evaluation of parallel vs cascade in two important ways:

### A. Runtime interpretability
If runtime decision bundles can collapse because of empirical tier failure or transport incoherency, then apparent strategy quality may be confounded by:
- empirical layer brittleness
- transport staleness
- selection-policy defects

This can make model-family comparison noisier than it should be.

### B. Data density dependence
Sequence-heavy architectures (especially LSTM/Transformer) are more sensitive to:
- logging density
- continuity
- normalized freshness
than purely tabular systems

So Issue 22 still matters to long-term fair comparison between architectures.

---

## 12.4 Required implication for future promotion evaluation

Future parallel-vs-cascade evaluation must distinguish:

- model-family quality
from
- runtime empirical gating quality
from
- transport coherency quality

Otherwise:
- a good model family may look bad because runtime transport is stale
- a good empirical architecture may look brittle because tier selection stops too early
- the wrong root cause may be blamed during architecture comparison

---

## 12.5 Preserved roadmap position

The V11 decision remains valid:

- do not prematurely converge to one architecture
- evaluate later after stronger system integrity is established

But V12 adds an important precondition:

> parallel-vs-cascade comparison should not be considered final until live decision-bundle coherency and empirical tier viability policy are fixed.

---

# 13. FULL MULTI-HORIZON CANONICAL ARCHITECTURE INTEGRATION (FUTURE 10.X ITEMS)

This section exists because the user explicitly required that V12 include how these issues intersect with the future 10.x multi-horizon canonical roadmap.

---

## 13.1 Preserved V11 future roadmap items

The following V11 roadmap decisions remain in force:

- move from a single canonical forecast to a multi-horizon canonical framework
- use:
  - Execution bias
  - Scalp bias
  - Intraday bias
  - Session bias
- converge toward one primary trade recommendation based on chosen trade horizon
- include multi-horizon alignment panel
- eventually compare and converge architecture choices after evaluation
- support adaptive weighting by market regime

None of those are reversed by V12.

---

## 13.2 New V12 integration constraint

However, V12 introduces a new prerequisite:

> multi-horizon canonical architecture must not be layered on top of a mixed-freshness transport model and brittle tier-selection logic

If that happens, the future multi-horizon canonical system will inherit:
- stale top-bundle state
- unstable horizon viability
- false `WAIT` collapses
- poor operator trust

---

## 13.3 Required order of operations

Before full future 10.x rollout, the system must first fix:

1. Issue 20 — real-time decision coherency  
2. Issue 19 — tier viability mismatch  
3. Issue 22 — logging density/persistence expansion  
4. Issue 21 — feature audit and validation  

Then the system can safely extend into:

5. Issue 24 — decision authority rewrite  
6. Multi-horizon canonical runtime integration  
7. Adaptive feature weighting and learned similarity evolution  

---

## 13.4 How V12 findings refine future multi-horizon design

The multi-horizon canonical framework must now explicitly incorporate:

### A. Freshness/coherency metadata
So the top bundle knows whether its fields belong to the same decision-time boundary.

### B. Horizon viability metadata
Not just:
- direction/confidence
but also:
- why available
- why withheld
- whether empirical support is present
- whether fusion-only degradation is in effect

### C. Structured degrade/block policy
The future system must distinguish:
- “direction valid, empirical weak”
from
- “no valid trade”
from
- “trade thesis valid, execution timing weak”

### D. Transport-aware runtime authority
The canonical architecture must not assume transport coherence.  
It must explicitly require it.

---

## 13.5 Final future-architecture interpretation

V12 does not change the destination:
- a multi-horizon canonical architecture remains the intended future state

But V12 changes the necessary foundation:
- transport coherence
- empirical viability policy
- logging density
- feature validation
must be elevated from “supporting details” to “first-class prerequisites”

---

# 14. UPDATED DRIFT / RESIDUAL TRACKER

The following new residual/drift items are added.

D13. Tier acceptance threshold misaligned with empirical viability threshold  
**Status:** Open  
**Category:** Runtime selection drift  
The tier-selection path stops at a count that can still be unusable for empirical horizon construction.

D14. Mixed-freshness transport state  
**Status:** Open  
**Category:** Runtime coherency  
Spot/order-flow can become fresher than top-card decision logic.

D15. Tier-driving features not yet fully audited  
**Status:** Open  
**Category:** Feature integrity  
Similarity features and bucket construction remain heuristic and under-validated.

D16. Continuous tracked-symbol density not guaranteed outside current core/tracked model  
**Status:** Open  
**Category:** Data architecture  
Tracked symbol history density can remain uneven over time.

D17. Multi-horizon runtime authority not yet formally rewritten for coherent canonical integration  
**Status:** Open  
**Category:** Decision architecture  
Future multi-horizon runtime authority requires explicit redesign.

---

# 15. UPDATED NEXT STEPS (STRICT ORDER, REVISED AFTER V12 FINDINGS)

The strict execution order is now:

## Phase 1 — Issue 20 / Issue 23
Real-time decision coherency + coherent SSE live-bundle architecture
- define top decision-critical bundle
- eliminate mixed-freshness decision display
- define trigger-based recompute policy
- isolate or remove decision-incoherent tick patching

## Phase 2 — Issue 19
Tier viability correction
- replace first-tier-≥20 stopping policy
- enforce viability-first tier acceptance
- define tier expansion / aggregation policy

## Phase 3 — Issue 22
Persistent logging expansion
- formalize tracked-symbol persistence rules
- expand beyond the current effective core-dependent model
- define session policy and density targets

## Phase 4 — Issue 21
Tier-driving feature audit and validation
- build feature audit layer
- inspect similar-set composition
- validate bucket policy and feature usefulness

## Phase 5 — Issue 24
Decision authority rewrite
- formalize primary/support/supportive roles
- define empirical-vs-fusion degrade/block policy
- define canonical multi-horizon runtime authority object

## Phase 6 — Issue 25 + future 10.x roadmap
Similarity framework evolution and multi-horizon canonical rollout
- adaptive weighting
- validated similarity evolution
- future learned similarity only after proof

---

# 16. FINAL POSITION (POST V12 ADDITIVE EXTENSION)

The system is now understood to be in the following state:

## What is solid
- the broad model stack
- fusion availability
- canonical one-truth policy
- multi-horizon ML foundation
- core persistence/logging infrastructure
- scheduler/normalization foundations

## What is not yet solid
- empirical tier viability selection
- transport coherency for the top decision region
- full all-tracked-ticker persistence density
- auditability of tier-driving features
- runtime decision authority for future multi-horizon canonical deployment

## Final truth after V12 findings

The system does **not** primarily fail because:
- the models are absent
- QQQ has no data
- fusion is broken

The system fails because:
- selected empirical subsets can become underpowered before viability is checked
- transport architecture can expose a newer price than decision state
- persistence density and feature validation are not yet at the required institutional-grade standard
- future multi-horizon runtime authority has not yet been rewritten around these realities

This must now be treated as the correct interpretation going forward.

---

# END OF V12 ADDITIVE EXTENSION


====================================================================================================
# SOURCE DOCUMENT: edwebconsole_future_state_architecture_spec_v1.md
**Date:** 2026-04-09 | **Role:** APP ARCHITECTURE — multi-plane future-state spec (planes, tiers, materiality engine, L1 contract) — the architecture actually built | **Original size:** 21,111 bytes
====================================================================================================

# EdWebConsole — Future-State Multi-Plane Architecture Spec (v1)

## Purpose

This document formalizes the next architectural direction for EdWebConsole so that all future work builds toward a world-class, real-time trading platform rather than adding isolated fixes.

This is a platform document, not a patch memo.

---

## 1. Core Architectural Decision

The system is now defined as a **four-plane architecture** with explicit ownership, latency budgets, update triggers, and freshness/version contracts.

The planes are:

- **L0 — Live Market Plane**
- **L1 — Near-Real-Time Context Plane**
- **L2 — Heavy Analytical Plane**
- **L3 — Persistence / Research Plane**

These planes are not conceptual only. They must become the operating design standard for:
- server-side modules
- caches/state domains
- SSE/event routing
- API contracts
- UI update behavior
- future feature placement decisions

No feature should be added until its plane ownership is explicitly identified.

---

## 2. Why This Architecture Exists

The old failure mode of systems like this is predictable:

- too much logic is tied to one endpoint
- live quote path gets contaminated by heavy work
- “fast” and “accurate” state are mixed without traceability
- UI implicitly waits for everything
- ticker switching causes stale or cross-owned work
- future features force rewrites because there were no boundaries

This architecture exists to prevent that.

The goal is not just speed. The goal is:

- deterministic state
- plane independence
- controlled freshness
- traceable merges
- scalability for future analytics and model expansion
- reduced rewrite risk

---

## 3. Plane Definitions

### 3.1 L0 — Live Market Plane

**Purpose:**  
Provide authoritative, immediate, tradeable reality.

**Contains:**
- last price
- bid
- ask
- spread
- session label
- active ticker identity
- stream ownership state
- live quote freshness
- generation / sequencing metadata
- stream health / connected state
- optional raw tape/book inputs if available on live path

**Must Not Contain:**
- chain analytics
- decision bundle
- ML outputs
- DB reads
- news
- full market-state calculations
- anything requiring slow recompute

**Cadence:**
- sub-second
- event-driven
- stream-first
- REST bootstrap allowed for recovery or initialization

**Consumers:**
- Tier A quote strip
- fast live UI elements
- streaming diagnostics
- any component requiring “true now” price

**Rules:**
- must always stay hot
- must never block on L1, L2, or L3
- must never trigger chain fetch on hot path
- must never rely on DB for current output
- must remain authoritative for the current price domain

**Latency Budget:**
- target first visible quote: sub-250 ms
- ideal much lower when stream already connected

---

### 3.2 L1 — Near-Real-Time Context Plane (Tier B)

**Purpose:**  
Provide cheap, trader-relevant, frequently updating context that makes the system feel continuously alive while L2 catches up.

**Contains:**
- order-flow summaries
- tape/book-derived microstructure summaries
- spot vs cached structural anchors
- distance to cached levels/walls/VWAP
- cached regime strip or compact structural context derived from last L2 snapshot
- liquidity summary vs current spot
- compact readiness / trader-context summary
- fast contextual metrics derived from:
  - current L0 state
  - last acknowledged L2 snapshot
  - stream health / short rolling windows

**May Read:**
- L0 always
- L2 cache snapshot only
- optional short-lived stream statistics cache

**Must Not Contain:**
- full chain traversal
- full exposure recompute
- ML inference
- full decision bundle
- DB/news reads
- anything that blocks on a fresh L2 run

**Cadence:**
- quote-driven
- event-driven
- typically 250 ms to 2 s responsiveness
- throttled as needed for UI stability

**Consumers:**
- Tier B cards
- near-real-time context summaries
- “readiness” style UI
- fast structural context displays

**Rules:**
- L1 is a merge plane, not a compute-everything plane
- L1 never implies L2 freshness
- L1 only merges L0 with the last known L2 snapshot
- L1 must explicitly disclose which L2 version it merged with
- L1 must never trigger or wait for full L2 recompute on user-critical path

**Latency Budget:**
- useful context visible under 1 second target
- no blocking on L2 refresh completion

---

### 3.3 L2 — Heavy Analytical Plane (Tier C)

**Purpose:**  
Run full intelligence and expensive calculations that provide deeper analytical value but must remain off the critical visual path.

**Contains:**
- full chain analytics
- strike-level exposures
- walls/totals/flip/voids/charm full calculations
- build_market_state
- decision bundle
- fusion / multi-model outputs
- ML horizon outputs
- Monte Carlo or similar heavy forecast logic
- model-health or rich analytics fields
- richer structured context that cannot be derived cheaply

**May Include:**
- news-enriched analytics
- cross-expiry context
- model summary overlays
- higher-order structural interpretations

**Must Not Be:**
- part of quote hot path
- synchronous requirement for ticker switch responsiveness
- directly tied to L0 rendering success

**Cadence:**
- async
- stale-while-refresh
- cache-first
- deduped keyed jobs
- on-demand + TTL + materiality driven

**Consumers:**
- full state panels
- deeper analytical cards
- decision intelligence
- research-grade UI views
- persistence triggers

**Rules:**
- background only
- versioned
- keyed by at least (ticker, expiry) where applicable
- deduped job model
- refresh must be explicitly observable (refresh_in_progress, stale, version)
- no direct silent replacement without version bump

**Latency Budget:**
- cache hit: immediate projection
- background refresh may lag but must not block L0/L1 usability

---

### 3.4 L3 — Persistence / Research Plane

**Purpose:**  
Provide durable storage, replayability, research support, model training support, audits, and operational traceability.

**Contains:**
- snapshots
- historical outcomes
- training sync / exports
- model-health records
- logs and audits
- backfills
- compliance-style artifact checks
- replay / research-oriented persistence
- offline metrics history

**Must Not Affect:**
- L0 responsiveness
- L1 responsiveness
- request-thread success for live features
- quote/ticker-switch critical path

**Cadence:**
- batched
- throttled
- completion-triggered from L2 milestones or timer-based jobs

**Consumers:**
- research tools
- training pipelines
- similar-setup logic
- replay systems
- audit/ops processes

**Rules:**
- append-only where possible
- never blocks L0–L2 user experience
- may lag without harming usability
- own worker discipline and queueing

---

## 4. Domain Model: Stop Thinking in One Giant Payload

The system should no longer be mentally modeled as one giant response blob.

It should be modeled as independent state domains.

### Required domains

- `live_market_state[ticker]`
- `context_light_state[ticker]`
- `analytics_state[(ticker, expiry)]`
- `persistence_state[...]`

Each domain should have explicit metadata.

### Required per-domain metadata

- `plane_id`
- `schema_version`
- `as_of_ts`
- `generated_at`
- `age_sec`
- `stale`
- `refresh_in_progress`
- `source_owner`
- `generation_id` or equivalent sequencing/version field
- `depends_on` metadata where applicable

### Critical dependency rule

L1 outputs that include structural fields must include the L2 snapshot version used.

Example concept:
- `l1_version`
- `l2_snapshot_version_used`

This is how the system avoids silent mixing of:
- fresh L0 price
- stale L2 structure
- ambiguous UI displays

---

## 5. Update Model

### 5.1 Architectural stance

The future model is **hybrid**:

- **Event-driven** for L0 and L1
- **Job-oriented / async** for L2
- **Batch / append-oriented** for L3

This is the correct model.

A fully event-sourced global architecture would be overkill and disruptive now.  
A purely request-driven design is too weak for where this system is going.

### 5.2 Required internal events

At minimum, define and standardize these internal events:

- `quote_tick`
- `ticker_changed`
- `l2_refresh_requested`
- `l2_snapshot_ready`
- `l2_refresh_failed`
- `stream_health_changed`
- `cache_invalidated`
- `l1_recompute_requested`

These can start as in-process pub/sub or callback dispatch.  
Do not over-engineer an external bus first.

### 5.3 Event consumers

At minimum:

- L0 updates from quote/stream events
- L1 recomputes on:
  - quote tick
  - ticker change
  - L2 snapshot ready
  - stream-health material changes if relevant
- L2 jobs trigger on:
  - TTL expiry
  - materiality threshold breach
  - ticker/expiry change
  - user forced refresh
- L3 writes trigger on:
  - L2 completion milestones
  - scheduled intervals
  - operational checkpoints

---

## 6. Tier Classification Standard

| Tier / Plane | Contents | What it must not do |
|---|---|---|
| Tier A / L0 | Quote, bid/ask, spread, session, live freshness, stream ownership | Must not wait on chain, DB, ML, or L2 recompute |
| Tier B / L1 | Order-flow summaries, spot vs cached VWAP/levels, cached regime strip, liquidity summary, readiness summary | Must not fetch chain, query DB, run ML, or imply L2 freshness |
| Tier C / L2 | Full chain analytics, exposures, build_market_state, fusion, decision bundle, ML horizons, richer analytics | Must not sit on request hot path or block live rendering |
| Persistence / L3 | Snapshots, history, training/research data, audits, backfills, ops records | Must not affect UI responsiveness |

### Hard classification rules

If a feature:
- requires chain → it is not Tier B
- requires DB → it is not Tier B
- requires ML → it is not Tier B
- must be immediate/current-tradeable-truth → it is Tier A
- is heavy but analytically valuable → it is Tier C
- is historical/research/training/audit → it is L3

No exceptions without explicit architecture review.

---

## 7. Materiality Engine (Must Be Built)

This is a required future-safe component, not a nice-to-have.

### Purpose

Prevent unnecessary L2 recompute while ensuring material market changes trigger analytics refresh when it matters.

### Why it matters

Without a materiality engine:
- the system recomputes too often and wastes performance
- or recomputes too slowly and analytics become misleading

Either failure mode is unacceptable.

### Materiality inputs should eventually include

- spot move magnitude vs last L2 snapshot
- time decay since last L2 compute
- expiry context
- volatility regime changes
- structural threshold crossings
- user force refresh
- stream reconnect / data invalidation events
- possibly spread/market-quality changes if analytically relevant

### Minimum architectural rule

L2 refresh should not be driven only by generic TTL forever.  
The system must evolve to **TTL + materiality + explicit triggers**.

---

## 8. Worker / Job Model

L2 and L3 must use explicit background job discipline.

### L2 job requirements

- deduped by key
- key includes at least ticker and expiry where applicable
- observable refresh state
- cancellation / discard behavior on stale ownership transitions
- versioned completion output
- failure state emitted explicitly

### Suggested job classes

- live quote / bootstrap recovery work
- L1 light recompute work (if not inline-throttled)
- L2 heavy analytics work
- L3 persistence work

### Hard rule

Do not let request handlers quietly become worker engines.

Endpoints should project current state and optionally trigger work through explicit paths.

---

## 9. UI Contract

The UI must evolve to subscribe by plane, not assume one monolithic payload.

### UI expectations

The UI should support:
- immediate partial rendering
- independent card freshness
- per-plane diagnostics
- background updates landing without resetting other cards
- structural version visibility where relevant
- tolerance for partial availability

### UI mental model

#### Immediate (L0)
- quote
- bid/ask
- spread
- streaming status
- active ticker confirmation

#### Fast follow (L1)
- distances to cached anchors
- order-flow summary
- liquidity one-liner
- readiness summary

#### Background (L2)
- deep analytics
- decision bundle
- model-driven outputs
- full chain-based cards

#### Offline / historical (L3)
- research/replay/history pages
- training state
- audit panels

### Hard UI rule

No card should silently imply it is fresh if it is showing merged or stale structural data.  
Freshness and versioning must be displayable or at least internally traceable.

---

## 10. Ticker Switching Contract

Ticker switch must be treated as a state transition, not as a full monolithic app refresh.

### Required sequence

1. Commit active ticker immediately
2. Bind L0 live plane to new ticker immediately
3. Render L0 immediately
4. Hydrate L1 from cache or cheap recompute
5. Request / subscribe to L2 in background
6. Discard stale prior-ticker work cleanly
7. Preserve ownership/version rules so old events cannot overwrite new ticker state

### Why this matters

Without this contract:
- stale work leaks across ticker transitions
- UI appears inconsistent
- “connected but wrong” state emerges
- the app feels unreliable even when technically running

---

## 11. Future-Safe Decisions to Lock Now

These decisions should be treated as current architectural standards.

### 11.1 Per-plane metadata everywhere
Every payload or SSE envelope should carry enough metadata to identify:
- plane
- freshness
- version
- source
- dependency version if merged

### 11.2 Single L2 worker abstraction
Do not create multiple ad hoc refresh patterns for heavy analytics.

### 11.3 Internal event hooks now
Even if implemented minimally today, standardize event hooks so logic stops sprawling across unrelated request handlers.

### 11.4 No chain calls outside L2 without review
This should be a hard architecture gate.

### 11.5 Endpoints are projections, not logic centers
Feature logic belongs in plane/domain modules, not in endpoint orchestration sprawl.

### 11.6 Incremental recompute as future target
Design L2 in stages now so later you can cache:
- chain fetch
- exposure stage
- downstream structural interpretation
- decision/fusion stages

Even if not fully implemented now, the interfaces should allow it later.

---

## 12. The Most Important Constraint in the Whole Design

**L1 never implies L2 freshness. It only merges L0 with the last acknowledged L2 snapshot.**

This is the sentence that protects the entire system from coherence failure.

If violated, the app will:
- feel inconsistent
- display mixed-time truths as one state
- become difficult to debug
- force architecture rewrites later

---

## 13. Exact Next Implementation Recommended

The next build should not be framed loosely as “add Tier B.”

It should be framed precisely as:

## Build L1 as a first-class domain module with a hard contract

### Recommended implementation target

Create a dedicated module such as:

- `planes/context_light.py`

### L1 inputs must be explicitly defined

- current L0 live state
- latest acknowledged L2 cache entry
- optional stream stats / short rolling microstructure window

### L1 outputs must be explicitly defined

- light context payload
- trader-readable summaries
- structural anchor distances
- readiness summary
- order-flow summary
- liquidity summary
- metadata including:
  - `l1_version`
  - `as_of_ts`
  - `stale`
  - `l2_snapshot_version_used`

### L1 trigger sources

- quote tick
- ticker changed
- L2 snapshot ready
- optional throttled timer for UI stability

### L1 must not do

- call chain fetch
- hit DB
- run model inference
- wait for fresh L2 completion

### Why this is the highest-value next step

Because it creates the missing middle plane that separates:
- “fast quote app”
from
- “continuous professional terminal”

Without L1, the system will always feel like:
- fast live price
- then slow jump to deeper intelligence

With L1, it becomes coherent and continuously useful.

---

## 14. Exact Cursor Prompt for Next Build

```text
We are not in patch/fix mode.

From this point on, every implementation must build toward a future-state multi-plane architecture for a professional real-time trading platform. Do not optimize locally or add ad hoc logic that increases coupling.

You must treat the current system as the foundation for a platform, not as a one-endpoint app.

# GOAL

Implement the next architectural step:
build L1 / Tier B as a first-class near-real-time context plane with explicit contracts, versioning, merge semantics, and event-driven updates.

We already have:
- L0 / Tier A live quote path
- L2 / Tier C heavy analytics path
- stale-while-refresh L2 behavior
- streaming ownership/generation work
- non-blocking ticker switching improvements

Now we need the middle plane done correctly.

# ARCHITECTURAL RULES (LOCKED)

You must follow these rules exactly:

1. L0 = Live Market Plane
- authoritative current price domain
- quote, bid/ask, spread, session, stream health, ownership/generation
- must never block on chain, DB, ML, or heavy analytics

2. L1 = Near-Real-Time Context Plane
- cheap, trader-relevant, frequently updating context
- derived from L0 + last acknowledged L2 snapshot + optional stream stats
- may include order-flow summaries, spot vs cached levels/VWAP, liquidity summary, readiness summary
- must NOT fetch chain
- must NOT query DB
- must NOT run ML
- must NOT wait on L2 recompute

3. L2 = Heavy Analytical Plane
- full chain analytics, build_market_state, exposures, fusion, decision bundle, ML horizons, etc.
- background only
- cache-first
- stale-while-refresh
- versioned
- never on critical live rendering path

4. L3 = Persistence / Research Plane
- snapshots, audits, training/research persistence
- completely off hot path

# CRITICAL MERGE RULE

L1 never implies L2 freshness.

L1 only merges:
- current L0 state
with
- the last acknowledged L2 snapshot

That means every L1 structural output must explicitly indicate which L2 version it used.

This must be enforced in code and payload contracts.

# WHAT TO BUILD

Implement a formal L1 domain module.

Preferred location:
- planes/context_light.py
or equivalent if a better exact path fits the codebase

The L1 domain must have a stable contract.

## REQUIRED INPUTS
- current live market state (L0)
- latest acknowledged analytical cache entry (L2)
- optional stream/tape/book rolling stats if already available cheaply

## REQUIRED OUTPUTS
A versioned light-context object containing at minimum:
- plane identifier
- schema version
- as_of timestamp
- stale flag
- refresh_in_progress if applicable
- L1 version or generation
- L2 snapshot version used
- spot vs cached anchor distances
- compact liquidity summary
- compact order-flow summary
- compact readiness summary

## REQUIRED TRIGGERS
L1 must update from:
- quote/stream events
- ticker change
- L2 snapshot ready event

It may also have a throttle/debounce for UI stability, but do not turn it into polling-only logic.

# IMPLEMENTATION REQUIREMENTS

1. Do not bury L1 logic inside endpoints.
Endpoints should project L1 state, not own L1 logic.

2. Introduce or formalize minimal internal event hooks if needed.
At minimum, define clear trigger points for:
- quote updated
- ticker changed
- L2 snapshot ready

3. Preserve existing working architecture where possible.
Do not throw away:
- FastAPI
- current cache concepts
- existing Tier A/Tier C split
- stale-while-refresh L2
- streaming ownership work

4. Add explicit metadata/versioning.
Every L1 response should identify:
- its plane
- its own freshness/version
- the L2 version it merged

5. Do not allow any new chain fetch or DB read to sneak into L1.

6. If some current “light” fields actually depend on heavy analytics or DB, identify them explicitly and either:
- keep them in L2
or
- convert them into cached/merged fields only

Do not silently misclassify them.

# WHAT I WANT BACK

Before giving code, provide:

## A. Exact implementation plan
- files to create/change
- new state objects/domains
- event hooks to add
- payload/schema changes
- how L1 will be computed and published

## B. Boundary audit
List anything that currently sits in the wrong plane or risks violating the new plane rules.

## C. Then provide exact code changes
No summaries.
No vague pseudo-code.
Show the precise code changes needed.

# HARD CONSTRAINTS

- Do not regress L0 responsiveness
- Do not make L1 wait on L2 refresh
- Do not add new monolithic endpoint coupling
- Do not treat “light” as permission to do hidden heavy work
- Think like a platform architect, not a patcher
```

---

## 15. Final Verdict

This architecture is the correct direction.

It:
- aligns with world-class real-time platform design
- builds on the current system rather than replacing it
- reduces rewrite risk
- creates the missing middle layer your app needs

The most important next step is not another patch.  
It is formalizing L1 as a first-class plane with hard boundaries and explicit merge/version semantics.


====================================================================================================
# SOURCE DOCUMENT: ED INSTITUTIONAL DECISION ENGINE.docx
**Date:** 2026-05-03 | **Role:** Decision Engine research/build framework (became repo v1.1/V3) | **Original size:** 33,518 bytes
====================================================================================================

ED INSTITUTIONAL DECISION ENGINE — RESEARCH / BUILD FRAMEWORK
Working Draft — Not Fully Locked Yet
PURPOSE
Build a replacement institutional-grade trading decision engine.
The system is not being designed to predict “price up / price down.”
The system is being designed to answer:
“Given a defined trade setup, under defined rules, is this trade likely to make money?”
Final intended output:
- TRADE LONG
- TRADE SHORT
- WAIT
- AVOID
With:
- probability of success
- expected value
- stop / target / timeout
- confidence
- reason codes
- supporting multi-horizon context
============================================================
STEP 1 — CORE PROBLEM RESET
============================================================
Original system problem:
- The existing stack was primarily directional.
- It used fixed forward-return style labels such as outcome_*c.
- It attempted to infer whether price would move up/down over fixed horizons.
- This does not answer whether an actual trade makes money.
- Directional accuracy alone is insufficient because a trade can be directionally correct and still lose due to stop placement, timing, volatility, spread, poor entry, or timeout.
Research conclusion:
The target system must predict trade outcome, not price direction.
New framing:
- Old question: “Will price go up?”
- New question: “Will this defined trade win, lose, or time out?”
Rejected:
- pure directional prediction as the final authority
- confidence scores without calibrated probabilities
- bar-by-bar prediction as the main signal engine
- using the old fusion / call_engine as authoritative
- treating old outcome_*c labels as valid trade success labels
Accepted:
- trade-outcome-based system
- event-based sampling
- triple-barrier labels
- meta-labeling later
- calibrated decision policy later
============================================================
STEP 1.5 — DEFINE WHAT A TRADE IS
============================================================
Before any model can be trained, the system must define the trade being evaluated.
Required trade definition components:
1. Entry rule
2. Direction
3. Stop rule
4. Target rule
5. Timeout / vertical barrier
6. Cost treatment
7. Same-bar ambiguity handling
8. Force-flat/session-close behavior
Working decisions:
- Entry = next bar open after signal bar T.
- Direction = LONG or SHORT.
- Stop = ATR multiple.
- Target = ATR multiple.
- Timeout = fixed number of minutes.
- Labels = WIN / LOSS / TIMEOUT.
- Costs are applied post-label, not used to change WIN/LOSS/TIMEOUT classification.
- Same-bar ambiguity requires conservative handling plus reject diagnostic.
- Force-flat near session close becomes TIMEOUT with audit flag.
Critical separation:
- Trade horizon = how long the trade is allowed to work.
- Structure horizon = market context/features used to decide quality.
- These are not the same thing.
============================================================
STEP 2 — REPLACE BAR-BY-BAR SAMPLING WITH EVENT SAMPLING
============================================================
Old idea:
- Every bar can be a prediction point.
Problem:
- This creates too many noisy samples.
- It overweights uneventful periods.
- It encourages models to learn noise.
- It does not follow institutional event-based research practice.
Research decision:
Use event-based sampling.
Chosen method:
- CUSUM event detection.
Purpose:
- Identify meaningful market movement events.
- Reduce noise.
- Avoid labeling every bar.
- Create a cleaner research dataset.
Initial event framework:
- Use 1m RTH bars.
- Compute returns.
- Scale returns by volatility sigma.
- Feed scaled z-score into CUSUM.
- Fire event when CUSUM threshold is reached.
============================================================
STEP 2.5 — DEFINE CUSUM VOLATILITY SCALE / SIGMA CONTRACT
============================================================
CUSUM requires a volatility denominator:
z_i = return_i / sigma_i
Initial implementation:
- Daily-reset EWM sigma.
- Hard variance floor leading to sigma ≈ 1e-8.
- CUSUM threshold used z-scores from this sigma.
What went wrong:
- At 09:30 ET, daily reset caused sigma to collapse.
- The first RTH bar’s return included overnight/open movement.
- That return divided by near-zero sigma created huge z-score spikes.
- CUSUM fired artificially at session open.
- First-30-minute suppression then deleted most of those events.
- Final event count collapsed.
Evidence discovered:
- All extreme |z| events occurred at 09:30.
- Sigma floor hit 1e-8 at session open.
- |z| values became enormous.
- This was a statistical construction problem, not a strategy failure.
Corrected sigma contract:
- Use continuous, causal EWM sigma across the full ordered RTH bar tape.
- Do not reset sigma daily for CUSUM event detection.
- Add optional causal relative sigma floor based on prior sigma median.
- Do not allow a fixed hard 1e-8 floor to dominate the scale.
- Sigma must be computed causally with no future bars.
Accepted:
- continuous EWM sigma
- causal relative floor
- no daily reset for CUSUM sigma
- no future leakage
Rejected:
- daily reset as CUSUM denominator
- hard 1e-8 floor as meaningful scale
- using first-30 filter as a patch for bad sigma
- changing k/h before fixing sigma
Result after sigma fix:
- Extreme z artifacts: eliminated.
- Raw fires increased from 51 to 126.
- Final events increased from 10 to 69.
- Event generator became statistically usable for pipeline validation.
============================================================
STEP 2.7 — EVENT FILTERS / EARLY SAFEGUARDS
============================================================
Initial event filters:
1. Exclude first 30 minutes of RTH event emission.
2. Minimum bar gap between events.
3. SMA(8,21) side rule.
4. Drop NONE / near-equal SMA side.
5. Do not emit event on last bar if next-bar entry is impossible.
Purpose:
- Avoid opening chaos.
- Avoid event clustering.
- Ensure each event has directional side.
- Ensure label path exists.
Important refinement:
The first-30-minute rule should not be used to hide sigma pathology.
It may remain as an event emission policy, but sigma itself must be valid.
Diagnostics showed:
- SMA side filter was not the issue.
- min_bar_gap was secondary.
- first-30 suppression was large, but mostly because bad sigma created artificial open events.
- after sigma fix, event generation became reasonable.
Current status:
- k unchanged.
- h unchanged.
- min_bar_gap unchanged.
- first-30 emission rule unchanged.
- SMA side rule unchanged.
- Only sigma contract changed.
============================================================
STEP 3 — DEFINE LABELING METHOD
============================================================
Research decision:
Use triple-barrier labeling.
Each event becomes a simulated trade.
Labels:
- WIN = target hit first
- LOSS = stop hit first
- TIMEOUT = neither hit before vertical barrier / force-flat
Why triple barrier:
- It directly measures trade success.
- It accounts for entry, stop, target, and time.
- It replaces fixed forward-return labels.
- It aligns with López de Prado style event-based labeling.
Rejected:
- outcome_1c / outcome_5c / outcome_15c / outcome_60c as final labels
- simple forward return > 0 labels
- “direction was right” as a win
- model confidence as a substitute for trade outcome
============================================================
STEP 3.5 — DEFINE TRADE OUTCOME GRID
============================================================
Instead of one trade rule, test a grid of trade definitions.
Current pilot grid:
- stop ATR: 0.75, 1.0, 1.25, 1.5, 2.0
- target ATR: 1.0, 1.5, 2.0, 2.5, 3.0
- vertical minutes: 15, 20, 25, 30, 35, 45, 60
Total cells:
- 5 stop levels × 5 target levels × 7 timeouts = 175 cells
Purpose:
- Discover which stop/target/time combinations behave well.
- Do not assume one arbitrary trade structure.
- Compare trade definitions systematically.
Important:
This is not final optimization.
This is the first trade-outcome labeling grid.
============================================================
STEP 4 — DATA CONTRACT
============================================================
Canonical data:
- 1-minute bars are the truth.
Primary production table:
- price_bars_1m
Staging table:
- price_bars_1m_staging
Data source:
- Schwab 1-minute OHLCV through existing repo client.
Rules:
- No direct production ingestion during reconstruction.
- Data must go to staging first.
- Validate staging.
- Merge later only with explicit approval.
- No silent repair.
- No overwrite without policy.
- No production table mutation during research runs.
Critical discovery:
The expected historical SPY data was missing.
Current canonical DB had far less SPY history than expected.
Forensics showed prior manual deletion of old bars and no recoverable backup in Git, D:\, WAL, or scanned local paths.
Conclusion:
Historical bar depth must be reconstructed through controlled ingestion/backfill.
============================================================
STEP 4.5 — STAGING INGESTION LAYER
============================================================
Why staging was required:
- Direct upsert into price_bars_1m can overwrite data.
- Existing upsert path can trigger outcome refresh.
- We needed reversibility and auditability.
- We needed to test Schwab data quality before touching production.
Staging table:
price_bars_1m_staging
Required staging fields:
- batch_id
- ticker
- bar_start_ts_utc
- bar_end_ts_utc
- open
- high
- low
- close
- volume
- source
- ingested_at
Primary key:
- batch_id, ticker, bar_start_ts_utc
Validation rules:
- duplicate key rows = 0
- off-grid rows = 0
- bad 60s span rows = 0
- bad OHLC rows = 0
- same-day RTH gaps = 0 for pilot-quality RTH data
- min/max timestamps documented
- gap drill-down reviewed
Validated results:
- 2-day SPY staging test passed.
- 30-day SPY staging batch loaded.
- RTH same-day gaps = 0.
- Extended-hours gaps exist but are not blocking RTH-only pilot.
============================================================
STEP 5 — BUILD PILOT SCAFFOLD
============================================================
Pilot purpose:
Validate the replacement-core mechanics.
Pilot is not:
- final model
- final strategy
- proof of edge
- production decision engine
Pilot components:
- prereg_v1.json
- pilot_config.py
- data_loader.py
- event_generation.py
- atr.py
- labeling.py
- metrics.py
- pilot_runner.py
- reports
- manifests
- logs
- diagnostics
Pilot responsibilities:
- Load 1m bars.
- Generate CUSUM events.
- Define trade entry.
- Compute ATR.
- Simulate triple-barrier outcomes.
- Produce 175-cell metrics.
- Report PASS/FAIL.
- Maintain audit trail.
Important:
The pilot scaffold can pass even when cells fail statistically.
Scaffold PASS means mechanics work.
Cell PASS means statistical/event thresholds are met.
============================================================
STEP 5.5 — SCIENTIFIC / GOVERNANCE GUARDRAILS
============================================================
Required guardrails:
- No leakage.
- No future data in sigma.
- ATR anchored at T-1.
- Signal bar T excluded from ATR.
- Entry is next-bar open.
- Costs do not change WIN/LOSS/TIMEOUT label.
- No old outcome_*c labels.
- No legacy signal authority.
- No production wiring.
- No merge into price_bars_1m.
- Prereg hash must validate.
- Explicit PASS/FAIL criteria.
- No silent fallback.
Current known limitation:
- purge/embargo not implemented in pilot v1.
- It is explicitly marked as NOT_IMPLEMENTED_IN_PILOT_V1.
- We are not pretending statistical validation is complete.
============================================================
STEP 6 — FIRST PILOT RUN / FAILURE
============================================================
Initial pilot result:
- 30-day staging data loaded.
- RTH bars ≈ 7,800.
- Events = 10.
- All cells failed.
Initial fail flags:
- valid_events_below_min
- TIMEOUT_pct_below_min
- mean post-cost return non-positive
- data_gaps_affect_labels
Initial concern:
Maybe strategy/system was bad.
Deeper investigation showed:
The system was not ready for strategy interpretation because event generation was malformed by sigma construction.
============================================================
STEP 6.5 — FAILURE INVESTIGATION
============================================================
Questions asked:
- Is this data size?
- Is this threshold issue?
- Is this event logic bug?
- Is SMA filtering killing events?
- Is min_bar_gap suppressing too much?
- Is first-30 filter suppressing too much?
- Is sigma scaling broken?
Diagnostics requested:
- total RTH bars
- eligible bars
- raw CUSUM fires
- first-30 drops
- min_gap drops
- SMA drops
- final events
- sensitivity across k values
- with/without min_gap
- with/without SMA
- with/without first-30 suppression
Finding:
- Raw fires = 51.
- Events emitted = 10.
- First-30 suppression removed most.
- SMA removed essentially none.
- min_bar_gap removed a few.
- Sigma pathology at open was the deeper issue.
============================================================
STEP 7 — EVENT ATTRITION ANALYSIS
============================================================
Attrition chain:
RTH bars → sigma-valid bars → CUSUM fires → post-fire filters → final events
Baseline before sigma fix:
- RTH bars = 7,800
- CUSUM fires = 51
- first-30 dropped = 36
- min_bar_gap dropped = 5
- SMA near-equal dropped = 0
- final events = 10
Interpretation:
The event engine was firing heavily at the wrong place/time, then filters were deleting the events.
This was not a valid event distribution.
============================================================
STEP 7.5 — SENSITIVITY DIAGNOSTICS
============================================================
Sensitivity tested:
- k = 0.3, 0.5, 0.7, 0.9, 1.2
- min_bar_gap on/off
- first-30 suppression on/off
- SMA gate on/off
Findings:
- Lowering k helped modestly, not enough.
- SMA gate was not the problem.
- first-30 suppression was the largest immediate lever.
- But removing first-30 would not solve the root issue because sigma was causing fake open fires.
Conclusion:
Do not tune k/h yet.
Fix sigma first.
============================================================
STEP 8 — SIGMA PATHOLOGY DISCOVERY
============================================================
Diagnostic rule:
Log bars where:
- sigma < 1e-6
- or |z| > 100
Result:
- 19 extreme rows.
- 100% occurred at 09:30 ET.
- sigma = 1e-8.
- z-score exploded because open/overnight return was divided by tiny sigma.
- All extreme z events occurred in first 30 minutes.
Root cause:
Daily-reset EWM sigma creates a cold-start variance collapse at the first bar of each session.
Interpretation:
This is a numerical/statistical artifact, not market information.
============================================================
STEP 8.5 — SIGMA CONTRACT DESIGN REVIEW
============================================================
Options considered:
A. Do not reset EWM sigma daily; use continuous causal EWM across full RTH stream.
B. Reset daily, but exclude first session return.
C. Reset daily, but seed/warm up from prior session trailing volatility.
D. Freeze CUSUM updates during first 30 minutes.
E. Use relative median sigma floor.
F. More advanced volatility models later.
Decision:
Use A + optional E.
Chosen contract:
- continuous causal EWM sigma
- no daily reset
- optional causal relative sigma floor
- no hard absolute floor as dominant scale
Rejected:
- daily reset as primary event sigma
- first-30 filter as patch
- D-only solution
- advanced volatility models for pilot v1
Reason:
Continuous sigma is simpler, causal, defensible, and removes session-boundary artifacts.
============================================================
STEP 9 — IMPLEMENT SIGMA FIX
============================================================
Implementation changes:
- Added build_sigma_for_cusum.
- Added continuous EWM across RTH sequence.
- Added relative floor from strictly past sigma median.
- Kept legacy daily-reset sigma only for diagnostics.
- generate_events now uses corrected sigma.
- k unchanged.
- h unchanged.
- first-30 filter unchanged.
- SMA rule unchanged.
- min_bar_gap unchanged.
Prereg updated:
- sigma_contract added.
- continuous EWM relative floor v1.
- daily reset marked deprecated.
Tests added:
- prereg hash validation
- causality test
- open sigma bounded test
- no fixed 09:30 extreme-z concentration
- data loader staging tests
- event generation tests
Test result:
- 23 passed.
============================================================
STEP 10 — RE-RUN PILOT AFTER SIGMA FIX
============================================================
Result:
- Same RTH bars: 7,800.
- Events: 10 → 69.
- Raw fires: 51 → 126.
- Extreme |z| > 100: 19 → 0.
- Scaffold PASS remained true.
- No production writes.
- No merge.
- No old signal stack involvement.
Interpretation:
Event generator is now valid for pipeline diagnostics.
Current event density:
- 69 events over ~20 RTH sessions.
- Approx 3–4 events/session.
- This is reasonable.
============================================================
STEP 10.5 — WHAT THIS DOES AND DOES NOT PROVE
============================================================
This proves:
- staging pipeline works
- Schwab ingestion works
- data normalization works
- CUSUM sigma now behaves sanely
- event generation is functional
- labeling pipeline runs
- pilot scaffold is structurally sound
This does not prove:
- strategy edge
- final model quality
- final trade profitability
- calibrated probabilities
- production readiness
- statistical sufficiency
- meta-label performance
============================================================
STEP 11 — NEW CONSTRAINT: DATA SCALE
============================================================
After sigma fix, the bottleneck shifted.
Old bottleneck:
- broken event generation
New bottleneck:
- insufficient data volume
Current:
- ~69 events over 30 calendar days / ~20 RTH sessions.
Prereg statistical gate:
- ~1000 valid events per cell.
Current result:
- cells still fail valid_events_below_min.
- this is expected.
- it is not evidence the system is bad.
Conclusion:
Need more staged historical data before evaluating cells seriously.
============================================================
STEP 11.5 — DEFINE TWO PASS LEVELS
============================================================
Decision:
Separate exploratory diagnostics from statistical claims.
Exploratory gate:
- roughly 50–100 events
- useful for debugging, sanity checks, distributions
- cannot claim edge
Statistical gate:
- roughly 1000+ valid events
- required for real conclusions
- required before model training / confidence claims
Important:
Do not remove the 1000-event statistical gate.
Instead, add exploratory reporting as a lower tier.
As more data is ingested, cells should naturally graduate:
EXPLORATORY → STATISTICAL
No intervention should be needed except data expansion and validation.
============================================================
STEP 12 — DATA EXPANSION PHASE
============================================================
Current validated staging:
- 30-day SPY staging batch.
- 26,846 staging rows.
- 7,800 RTH bars.
- same-day RTH gaps = 0.
- event count = 69 after sigma fix.
Next data objective:
- expand staged SPY history.
Possible targets:
- 120 days
- 180 days
- 252 days
Purpose:
- reach 500+ events
- eventually reach 1000+ valid events
- keep all data in staging until merge policy is approved
Do not:
- merge into price_bars_1m yet
- train models yet
- tune parameters yet
- claim edge yet
============================================================
STEP 13 — FUTURE MERGE POLICY
============================================================
Before any staging-to-production merge:
Required:
- DB backup
- explicit merge script
- insert-missing-only default
- no silent overwrite
- conflict policy documented
- provenance/batch_id preserved
- rollback plan
- validation before/after
- no outcome recompute without sign-off
Default merge rule should likely be:
- insert rows missing from price_bars_1m
- do not overwrite existing rows unless explicitly approved
Still not done:
- merge job
- production table update
- staging provenance transfer
============================================================
STEP 14 — FUTURE FEATURE SYSTEM
============================================================
Once labels/events/data are sufficient, build features.
Feature groups:
1m execution:
- spread
- micro movement
- candle behavior
- immediate momentum
- volatility
- execution quality
5m entry control:
- pullback/continuation
- VWAP interaction
- short-term momentum
- entry confirmation
15m structure:
- HH/HL/LH/LL
- BOS/CHOCH
- supply/demand
- FVG
- support/resistance
- opening range
60m regime:
- trend
- volatility regime
- macro/market state
- market breadth/proxy context
- higher timeframe bias
Rules:
- every feature must be causal
- every feature must exist at decision time
- no UI-only feature unless converted into training/inference feature
- no model output features unless formally governed
- training and inference schemas must match
============================================================
STEP 15 — FUTURE MODELING LAYER
============================================================
Model target:
- probability trade succeeds
Not:
- probability price goes up
Possible base models:
- XGBoost
- LSTM
- Transformer
- Monte Carlo/path simulation
- Bayesian fusion later
But all must train on:
- trade outcome labels
- not old outcome_*c labels
Critical:
Old model stack may not be reused as authoritative unless retrained under new labels and contracts.
============================================================
STEP 16 — FUTURE META-LABELING
============================================================
Meta-labeling purpose:
- decide whether to take a candidate trade.
Base event says:
- trade opportunity exists.
Meta-model says:
- take it or avoid it.
Meta-label target:
- 1 = take trade
- 0 = do not take trade
Required:
- OOF predictions
- purged validation
- embargo
- walk-forward structure
- no leakage
- no in-sample meta training
============================================================
STEP 17 — FUTURE CALIBRATION
============================================================
Raw model scores are not enough.
Need calibrated probabilities:
- P(WIN)
- P(LOSS)
- P(TIMEOUT)
- expected value
- uncertainty
- reliability
Possible methods:
- isotonic calibration
- Platt scaling
- reliability curves
- Brier score
- ECE
Decision engine must use calibrated probabilities, not raw scores.
============================================================
STEP 18 — FUTURE DECISION POLICY
============================================================
Final policy output:
- TRADE LONG
- TRADE SHORT
- WAIT
- AVOID
Decision should require:
- positive expected value
- sufficient probability
- acceptable risk/reward
- acceptable liquidity/spread
- no veto from higher timeframe structure/regime
- valid confidence/calibration
- no data-quality issue
Example future output:
LONG probability: 64%
SHORT probability: 38%
Expected value: positive
60m trend supports long
15m structure supports continuation
5m confirms entry
1m execution favorable
Decision: TRADE LONG
============================================================
STEP 19 — FUTURE VALIDATION FRAMEWORK
============================================================
Required institutional validation:
- purged cross-validation
- embargo
- sample uniqueness
- walk-forward validation
- out-of-sample testing
- leakage audits
- regime-aware performance
- calibration checks
- decision-level EV validation
Current status:
- not implemented in pilot v1
- explicitly acknowledged
- no fake claims
============================================================
STEP 20 — CURRENT STATUS SUMMARY
============================================================
Completed:
- problem reframed from direction to trade outcome
- trade definition created
- triple-barrier labeling scaffold built
- ATR T-1 fixed
- staging ingestion created
- Schwab ingestion validated
- 30-day SPY staging loaded
- pilot can run against staging
- sigma pathology identified
- sigma contract corrected
- event count improved 10 → 69
- scaffold passes
- no production table merge yet
Still open:
- scale staged data
- define exploratory/statistical reporting explicitly in code
- merge policy
- longer SPY history
- QQQ and equity anchor expansion
- feature contracts
- model training
- meta-labeling
- calibration
- decision policy
- UI integration
- purged/embargo validation
============================================================
CURRENT POSITION
============================================================
We are here:
VALID EVENT PIPELINE + INSUFFICIENT DATA SCALE
We are not yet here:
VALIDATED STRATEGY
TRAINED DECISION MODEL
PRODUCTION TRADE ENGINE
============================================================
ONE-LINE SYSTEM FLOW
============================================================
1m market data
→ staging ingestion
→ validated canonical bar tape
→ CUSUM event detection
→ defined trade entry/stop/target/timeout
→ triple-barrier WIN/LOSS/TIMEOUT labels
→ causal multi-horizon features
→ base models
→ OOF meta-labeling
→ calibration
→ EV decision policy
→ TRADE / WAIT / AVOID
============================================================
CORE RULE GOING FORWARD
============================================================
Do not tune strategy before validating data, events, and labels.
Correct order:
1. Reconstruct data
2. Validate data
3. Generate stable events
4. Label trades correctly
5. Reach sufficient sample size
6. Build features
7. Train models
8. Meta-label
9. Calibrate
10. Decide trades
11. Integrate UI/production


====================================================================================================
# SOURCE DOCUMENT: IDEAL TRADING DECISION ENGINE.docx
**Date:** 2026-05-04 | **Role:** Ideal decision engine design | **Original size:** 20,745 bytes
====================================================================================================

=================================================================================
                    IDEAL TRADING DECISION ENGINE — PIPELINE
                    Based on empirical research evidence
=================================================================================
[STAGE 1: DATA LAYER]
─────────────────────
                                                          
Schwab API ──┐                                            
             │                                            
InsiderFinance ┐                                          
             │ ├──► price_bars_1m_staging ──► validation ──► price_bars_1m
Other feeds ─┘ │     (Schwab 1m OHLCV +                     (canonical)
             │ │      options data + flow)                                                   
External  ───┘ │                                                              
data feeds                                                                    
[STAGE 2: EVENT GENERATION (López/Thames discipline)]
──────────────────────────────────────────────────────
price_bars_1m
     │
     ▼
CUSUM filter (volatility-adaptive threshold)
     │
     ▼
Side rule (SMA crossover or your prediction-driven rule)
     │
     ▼
Events: (timestamp T, side LONG/SHORT, ATR at T-1)
[STAGE 3: FEATURE LAYER (per horizon, per model type)]
───────────────────────────────────────────────────────
Each event triggers feature extraction across 4 horizon-specific feature spaces:
┌──────────────┬──────────────┬──────────────┬──────────────┐
│  1m FEATURES │  5m FEATURES │ 15m FEATURES │ 60m FEATURES │
│              │              │              │              │
│  execution   │  entry       │  structure   │  regime      │
│  timing      │  confirmation│  bias        │  trend       │
│              │              │              │              │
│  - tick      │  - VWAP      │  - BOS/CHOCH │  - VIX       │
│    micro     │    interact  │  - S/R       │  - sector    │
│  - spread    │  - pullback  │  - FVG       │    rotation  │
│  - momentum  │  - momentum  │  - supply/   │  - macro     │
│  - tape      │    short-term│    demand    │  - regime    │
│              │              │  - opening   │    state     │
│              │              │    range     │              │
└──────────────┴──────────────┴──────────────┴──────────────┘
       Each feature space gets routed to model-type-specific
       feature subsets (tabular/sequential/distributional)
[STAGE 4: PER-HORIZON MODEL STACKS (3 architectures per horizon)]
──────────────────────────────────────────────────────────────────
   ┌─────────────────── 1m HORIZON STACK ───────────────────┐
   │                                                          │
   │  XGBoost     ModernTCN     Logistic baseline            │
   │  (tabular)   (sequential)  (sanity check)               │
   │      │            │              │                       │
   │      └──► Horizon 1m Fusion (XGBoost meta) ◄───┘        │
   │                       │                                  │
   └───────────────────────┼──────────────────────────────────┘
                           │
                           ▼
                  P(1m success | event)
   ┌─────────────────── 5m HORIZON STACK ───────────────────┐
   │                                                          │
   │  XGBoost     LSTM/GRU      TimesNet                     │
   │  (tabular)   (sequential)  (intraday seasonality)       │
   │      │            │              │                       │
   │      └──► Horizon 5m Fusion (XGBoost meta) ◄───┘        │
   │                       │                                  │
   └───────────────────────┼──────────────────────────────────┘
                           │
                           ▼
                  P(5m success | event)
   ┌─────────────────── 15m HORIZON STACK ──────────────────┐
   │                                                          │
   │  XGBoost     PatchTST      N-HiTS                       │
   │  (tabular)   (Transformer  (hierarchical)               │
   │              variant)                                    │
   │      │            │              │                       │
   │      └──► Horizon 15m Fusion (XGBoost meta) ◄───┘       │
   │                       │                                  │
   └───────────────────────┼──────────────────────────────────┘
                           │
                           ▼
                  P(15m success | event)
   ┌─────────────────── 60m HORIZON STACK ──────────────────┐
   │                                                          │
   │  CatBoost    iTransformer  HMM                          │
   │  (regime     (long-range   (regime                      │
   │  features)   dependencies) detection)                   │
   │      │            │              │                       │
   │      └──► Horizon 60m Fusion (XGBoost meta) ◄───┘       │
   │                       │                                  │
   └───────────────────────┼──────────────────────────────────┘
                           │
                           ▼
                  P(60m success | event)
[STAGE 5: TRIPLE-BARRIER LABELING (López)]
───────────────────────────────────────────
For each event, run forward path simulation:
                                                          
  Entry: next bar open                                    
  Stop: ATR multiple                                      
  Target: ATR multiple                                    
  Vertical: max holding time                              
                                                          
       │                                                  
       ▼                                                  
  Auxiliary labels (per horizon role):
  - 1m_label  (vertical = 5min)
  - 5m_label  (vertical = 15min)
  - 15m_label (vertical = 30min)
  - 60m_label (vertical = 60min)
  - Policy label (one authoritative for meta)
[STAGE 6: CROSS-HORIZON META LAYER (López/Thames)]
───────────────────────────────────────────────────
Meta-model consumes (OOF predictions only):
   ┌─────────────────────────────────────────────────────┐
   │  Inputs to meta:                                    │
   │                                                     │
   │  • P(1m success)  ──┐                              │
   │  • P(5m success)  ──┤                              │
   │  • P(15m success) ──┤── Role-model OOF outputs     │
   │  • P(60m success) ──┘                              │
   │                                                     │
   │  • Volatility features (ATR, vol regime)            │
   │  • Regime features (VIX, time-of-day, session)     │
   │  • Trade-specific (R:R ratio, side, vertical)      │
   │  • Cross-horizon agreement signals                  │
   │                                                     │
   │  Target:                                            │
   │  meta_label = 1 if policy_label == WIN else 0       │
   │                                                     │
   │  Architecture: XGBoost (canonical for meta)         │
   │                                                     │
   └─────────────────────┬───────────────────────────────┘
                         │
                         ▼
              Raw meta probability p_trade
[STAGE 7: CALIBRATION LAYER]
─────────────────────────────
   Raw p_trade
        │
        ▼
   Isotonic calibration (per walk-forward window)
        │
        ▼
   Calibrated P(WIN | this defined trade)
   
   ECE monitoring for production drift
[STAGE 8: DECISION POLICY (EV-based)]
──────────────────────────────────────
   Calibrated probability + Cost model + R:R geometry
                       │
                       ▼
   EV = P(WIN) × R_target − (1−P(WIN)) × R_stop − cost
                       │
                       ▼
        ┌──────────────┴──────────────┐
        │                             │
   EV ≥ TRADE_threshold?         EV ≤ AVOID_threshold?
        │                             │
        ▼                             ▼
   TRADE LONG / SHORT          AVOID
                       │
                       ▼ (between thresholds)
                    WAIT
[STAGE 9: OUTPUT TO TRADER]
────────────────────────────
   ┌────────────────────────────────────────────────┐
   │  Decision:        TRADE LONG                    │
   │  P(success):      0.64                          │
   │  Expected value:  +0.42 R                       │
   │  Stop:            $462.18                       │
   │  Target:          $464.85                       │
   │  Timeout:         15:30 ET                      │
   │  Confidence:      High                          │
   │                                                 │
   │  Reason codes:                                  │
   │  - 60m trend: supportive (P=0.71)              │
   │  - 15m structure: continuation (P=0.68)         │
   │  - 5m entry: confirmed (P=0.62)                 │
   │  - 1m execution: favorable (P=0.59)             │
   │  - Regime: low VIX, mid-session                 │
   └────────────────────────────────────────────────┘
[STAGE 10: GOVERNANCE / VALIDATION (continuous, all stages)]
─────────────────────────────────────────────────────────────
   v1.1 Framework discipline applied throughout:
   
   • Purged CV with embargo at every model layer
   • OOF predictions only for downstream consumption
   • Walk-forward validation with locked windows
   • Sample uniqueness weighting per López
   • DSR-adjusted Sharpe for any "best cell" claims
   • Pre-registered prereg with content_hash binding
   • Feature contracts per role and per model type
   • No silent fallback logic
   • Calibration ECE monitoring
   • Drift detection per production hard-fail gates
=================================================================================
                              EVIDENCE BACKING
=================================================================================
Stage 4 model picks: 918-experiment controlled comparison + S&P 500 quantum-
                     classical study (architecture diversity r=0.38 vs r=0.6)
Stage 5 labeling:    López de Prado triple-barrier method (canonical)
Stage 6 meta:        Hudson & Thames meta-labeling (37-100% Sharpe improvement
                     over primary alone in published studies)
Stage 7 calibration: Per-window refit, ECE-monitored (clinical ML standard)
Stage 8 decision:    EV-thresholded policy (López/Thames canonical)
Cross-stage:         v1.1 framework discipline (your locked artifact)
=================================================================================
                              CRITICAL NOTES
=================================================================================
- 12 base models + 4 horizon fusions + 1 meta = 17 trainable artifacts
- All consume role/model-specific feature subsets per Step 1.5 D.2
- Total feature-to-cell assignments: ~70 features × 12 base cells = 840 pairs
  to evaluate via SHAP + MI ablation
- Sample size requirement: ~1000 events per cell minimum (currently 69)
- Computational cost: high; suitable for research, may require optimization
  for real-time deployment
=================================================================================
This is the empirically-supported ideal stack. Each stage has published evidence behind the architectural choice. The flow is left-to-right: data → events → features → model stacks per horizon → triple-barrier → meta → calibration → decision → output, with governance running orthogonally throughout.
Want me to redraw any section more detailed, or focus on a specific stage?


====================================================================================================
# SOURCE DOCUMENT: IDEAL TRADING DECISION ENGINE_V1.docx
**Date:** 2026-05-04 | **Role:** Maximum-edge unconstrained design variant | **Original size:** 18,452 bytes
====================================================================================================

================================================================================= MAXIMUM-EDGE TRADING DECISION ENGINE Unconstrained design — research-backed ================================================================================= [STAGE 1: DATA INGESTION — multi-source] ───────────────────────────────────────── Schwab API ──────────────┐ InsiderFinance ──────────┤ Options flow data ───────┤ Dark pool prints ────────┤ ETF creation/redemption ─┤──► Staging tables ──► Validated canonical store Sector ETFs / cross-asset ┤ (per-source) (1m OHLCV + Congressional trades ────┤ options + flow + News sentiment ──────────┤ alt data) Macro / VIX / yields ────┤ Earnings / events ───────┘ [STAGE 2: EVENT GENERATION — multi-source detection] ───────────────────────────────────────────────────── ┌────────────────────────────────────────────────┐ │ Event sources (parallel detection): │ │ │ │ • CUSUM (price structural breaks) │ │ • Volatility regime change detection │ │ • News-driven events (sentiment spikes) │ │ • Options flow events (unusual activity) │ │ • Dealer positioning shifts (gamma flip etc.) │ │ • Dark pool large prints │ │ • Cross-asset divergence events │ └─────────────────┬───────────────────────────────┘ │ ▼ Unified event stream (timestamp T, event type, side LONG/SHORT, ATR at T-1, regime context at T) [STAGE 3: REGIME DETECTION LAYER] ────────────────────────────────── Event ──► Regime classifier │ ├── HMM (Hidden Markov Model) → regime state ├── Volatility regime (low/med/high VIX percentile) ├── Trend regime (trending/ranging) ├── Sector dispersion regime └── Macro regime (Fed cycle, earnings season) │ ▼ Regime vector attached to event [STAGE 4: PARALLEL LABELING LAYER] ─────────────────────────────────── Each event gets BOTH label families (López): ┌─────────────────────────┬─────────────────────────┐ │ Triple-barrier labels │ Trend-scanning labels │ │ │ │ │ - Stop ATR multiple │ - Statistical │ │ - Target ATR multiple │ significance of │ │ - Vertical (timeout) │ trend over window │ │ │ - t-statistic based │ │ Output: WIN/LOSS/ │ - Signed magnitude │ │ TIMEOUT per cell │ │ │ │ Output: trend strength │ │ + auxiliary labels │ + direction per role │ │ per role horizon │ │ │ (5/15/30/60 min) │ │ └─────────────────────────┴─────────────────────────┘ │ │ └────────┬───────────────────┘ │ ▼ Both label streams stored in parallel (production label is from one; diagnostic label from the other) [STAGE 5: FEATURE LAYER — per horizon × per model type] ──────────────────────────────────────────────────────── Each event triggers 4 horizon-specific feature spaces. Within each horizon, features are routed to model-type- specific subsets: ┌──────────┬──────────┬──────────┬──────────┐ │ 1m │ 5m │ 15m │ 60m │ │ features │ features │ features │ features │ └──────────┴──────────┴──────────┴──────────┘ │ │ │ │ ▼ ▼ ▼ ▼ Each routes to 3 model types per horizon [STAGE 6: PER-HORIZON MODEL STACKS] ──────────────────────────────────── ┌────────────── 1m HORIZON STACK ──────────────┐ │ │ │ XGBoost ModernTCN Logistic baseline │ │ (tabular) (sequential) (sanity check) │ │ │ │ │ │ │ └────► 1m Fusion (XGBoost meta) ◄───┘ │ │ │ │ └───────────────────────┼────────────────────────┘ ▼ P(1m success | event, regime) ┌────────────── 5m HORIZON STACK ──────────────┐ │ │ │ XGBoost LSTM/GRU TimesNet │ │ │ │ │ │ │ └────► 5m Fusion (XGBoost meta) ◄───┘ │ │ │ │ └───────────────────────┼────────────────────────┘ ▼ P(5m success | event, regime) ┌────────────── 15m HORIZON STACK ─────────────┐ │ │ │ XGBoost PatchTST N-HiTS │ │ │ │ │ │ │ └────► 15m Fusion (XGBoost meta) ◄──┘ │ │ │ │ └───────────────────────┼────────────────────────┘ ▼ P(15m success | event, regime) ┌────────────── 60m HORIZON STACK ─────────────┐ │ │ │ CatBoost iTransformer HMM (regime) │ │ │ │ │ │ │ └────► 60m Fusion (XGBoost meta) ◄──┘ │ │ │ │ └───────────────────────┼────────────────────────┘ ▼ P(60m success | event, regime) [STAGE 7: REGIME-AWARE DYNAMIC WEIGHTING] ────────────────────────────────────────── Per-horizon outputs flow into regime-aware weighting layer: ┌────────────────────────────────────────────────┐ │ Current regime → weights for each horizon │ │ │ │ Bull regime: weight 60m heavier │ │ Bear regime: weight 1m + 5m heavier │ │ High-vol: weight 1m heavier │ │ Low-vol: weight 60m heavier │ │ Trending: weight 60m + 15m heavier │ │ Ranging: weight 5m + 15m heavier │ │ │ │ Dynamic weights learned from historical │ │ regime-conditional performance │ └─────────────────────┬───────────────────────────┘ │ ▼ Weighted multi-horizon prediction [STAGE 8: CROSS-LABEL META LAYER (López/Thames)] ───────────────────────────────────────────────── Two parallel meta models, one per label family: ┌──────────────────────────┬──────────────────────────┐ │ Triple-barrier meta │ Trend-scanning meta │ │ │ │ │ Inputs: │ Inputs: │ │ • Regime-weighted │ • Regime-weighted │ │ horizon predictions │ horizon predictions │ │ • Regime features │ • Regime features │ │ • Volatility features │ • Volatility features │ │ • Trade geometry │ • Trend statistics │ │ • OOF only │ • OOF only │ │ │ │ │ Target: │ Target: │ │ meta_label_TB = │ meta_label_TS = │ │ 1 if TB_label == WIN │ 1 if TS magnitude │ │ │ significant + correct │ │ │ direction │ │ │ │ │ Architecture: XGBoost │ Architecture: XGBoost │ └─────────────┬────────────┴─────────────┬────────────┘ │ │ ▼ ▼ p_trade_TB p_trade_TS │ │ └────────┬─────────────────┘ │ ▼ Synthesis layer (regime-aware combination) │ ▼ p_trade_combined [STAGE 9: BAYESIAN UNCERTAINTY ESTIMATION] ─────────────────────────────────────────── Raw p_trade_combined enters Bayesian layer: ┌────────────────────────────────────────────────┐ │ Bayesian neural network OR Gaussian process │ │ produces: │ │ │ │ • Point estimate: p_trade │ │ • Uncertainty: σ(p_trade) │ │ • Confidence band: [p_low, p_high] │ └─────────────────────┬───────────────────────────┘ │ ▼ Probability + uncertainty [STAGE 10: CALIBRATION LAYER] ────────────────────────────── Point estimate → Isotonic calibration (per walk-forward window, per regime) │ ▼ Calibrated P(WIN) ECE monitoring with regime-conditional thresholds Drift detection per production hard-fail gates [STAGE 11: REINFORCEMENT LEARNING POSITION SIZING] ─────────────────────────────────────────────────── Inputs to RL agent (PPO or SAC): ┌────────────────────────────────────────────────┐ │ • Calibrated P(WIN) │ │ • Uncertainty σ(P) │ │ • EV calculation │ │ • Current portfolio state │ │ • Recent realized P&L │ │ • Risk budget remaining │ │ • Correlation with existing positions │ │ • Regime state │ │ │ │ Output: position size as fraction of capital │ │ │ │ Reward: realized P&L (after costs) │ │ Trained with conservative risk constraints │ └─────────────────────┬───────────────────────────┘ │ ▼ Optimal position size [STAGE 12: DECISION POLICY (EV + uncertainty + size)] ────────────────────────────────────────────────────── ┌────────────────────────────────────────────────┐ │ EV = P(WIN) × R_target − (1−P(WIN)) × R_stop │ │ − cost │ │ │ │ Confidence-adjusted EV: │ │ EV_lower = EV using p_low │ │ EV_upper = EV using p_high │ │ │ │ Decision: │ │ EV_lower ≥ TRADE_threshold → TRADE (sized) │ │ EV_upper ≤ AVOID_threshold → AVOID │ │ Otherwise → WAIT │ └─────────────────────┬───────────────────────────┘ │ ▼ [STAGE 13: OUTPUT TO TRADER] ───────────────────────────── ┌────────────────────────────────────────────────┐ │ Decision: TRADE LONG │ │ P(success): 0.64 (CI: 0.58 – 0.70) │ │ Expected value: +0.42 R │ │ Position size: 2.3% of capital │ │ Stop: $462.18 │ │ Target: $464.85 │ │ Timeout: 15:30 ET │ │ Confidence: High │ │ Regime: Low VIX, mid-session, trending│ │ │ │ Reason codes: │ │ - 60m trend: supportive (P=0.71, weight 0.35) │ │ - 15m structure: continuation (P=0.68, w 0.30) │ │ - 5m entry: confirmed (P=0.62, w 0.20) │ │ - 1m execution: favorable (P=0.59, w 0.15) │ │ - Triple-barrier meta: 0.66 │ │ - Trend-scanning meta: 0.62 │ │ - Regime-conditional historical: WIN rate 58% │ │ - Position size from RL agent: 2.3% of capital │ └────────────────────────────────────────────────┘ [STAGE 14: GOVERNANCE / VALIDATION (continuous)] ───────────────────────────────────────────────── v1.1 Framework discipline applied throughout: • Purged CV with embargo at every model layer • OOF predictions only for downstream consumption • Walk-forward validation with locked windows • Sample uniqueness weighting per López • DSR-adjusted Sharpe for any "best cell" claims • Pre-registered prereg with content_hash binding • Feature contracts per role and per model type • No silent fallback logic • Calibration ECE monitoring per regime • Drift detection per production hard-fail gates • Bayesian uncertainty validation • RL agent reward function audit ================================================================================= ARTIFACT COUNT ================================================================================= • 12 base models (3 per horizon × 4 horizons) • 4 horizon fusion models • 1 regime detection model (HMM) • 1 regime-aware weighting model • 2 meta-models (TB + TS) • 1 synthesis layer • 1 Bayesian uncertainty model • 1 calibration model • 1 RL position-sizing agent Total: ~24 trainable artifacts ================================================================================= EVIDENCE BACKING ================================================================================= Stage 2 multi-source events: Multi-event-source ensemble research Stage 3 regime detection: HMM regime literature, regime-aware ensembles Stage 4 parallel labels: López trend-scanning vs triple-barrier comparison (TS showed 37%+ Sharpe improvement) Stage 6 model picks: 918-experiment controlled comparison Stage 6 architecture diversity: r=0.38 vs r=0.60 correlation finding Stage 7 regime weighting: Regime-aware ensemble research Stage 8 dual meta: López meta-labeling canonical Stage 9 Bayesian uncertainty: Bayesian deep learning literature Stage 10 calibration: Clinical ML calibration standards Stage 11 RL position sizing: PPO/SAC trading research, FinRL contests Stage 12 decision policy: López/Thames EV-thresholded canonical Cross-stage discipline: v1.1 framework (your locked artifact) =================================================================================


====================================================================================================
# SOURCE DOCUMENT: Trading Plan by Cursor Final.docx
**Date:** 2026-05-04 | **Role:** Trading plan (Cursor final) | **Original size:** 27,025 bytes
====================================================================================================

Below is the tightened version I’d run by the group. It preserves the unified architecture but fixes the weak spots: overfit-prone regime weighting, overclaimed conformal guarantees, context-dependent neutralization, heuristic ranking, and unclear separation between signal/execution/portfolio edge.
=================================================================================
                ED INSTITUTIONAL TRADING DECISION ENGINE
                Evidence-gated maximum-edge architecture
=================================================================================
CORE DESIGN PRINCIPLE
─────────────────────
The engine is split into three auditable edge domains:
  1. SIGNAL EDGE
     Does the event predict a profitable directional opportunity
     before implementation costs?
  2. IMPLEMENTATION EDGE
     Can the opportunity be monetized now, given spread, liquidity,
     fill probability, adverse selection, and market impact?
  3. PORTFOLIO EDGE
     Is this the best use of risk budget versus all other candidates
     and existing exposures?
No layer is included because it is sophisticated.
Every optional layer must earn inclusion through purged OOF,
walk-forward, after-cost, capacity-aware expected utility lift.
=================================================================================
STAGE 1: DATA INGESTION — MULTI-SOURCE CANONICAL STORE
=================================================================================
Sources:
  • Schwab API / broker market data
  • 1m OHLCV
  • Order book / quotes / NBBO where available
  • Options flow
  • Dark pool prints
  • ETF creation/redemption
  • Sector ETFs / cross-asset data
  • Insider transactions
  • Congressional trades
  • News sentiment
  • Macro / VIX / yields
  • Earnings and event calendars
  • Capacity / crowding:
      short interest, borrow cost, institutional ownership,
      factor crowding, dealer positioning
Pipeline:
  Source feeds
      → per-source staging tables
      → timestamp normalization
      → availability-lag enforcement
      → survivorship-safe symbol mapping
      → validated canonical store
Canonical store contains:
  • 1m OHLCV
  • options/flow data
  • quote/order-book features
  • microstructure data
  • alt-data features
  • macro/regime context
  • event calendar context
Hard rule:
  Every feature must have an as-of timestamp and availability timestamp.
  No feature may enter training or inference unless it would have been
  known at decision time.
=================================================================================
STAGE 2: EVENT GENERATION — MULTI-SOURCE DETECTION
=================================================================================
Parallel event detectors:
  • CUSUM price structural breaks
  • volatility regime-change events
  • news/sentiment shocks
  • unusual options activity
  • dealer positioning shifts / gamma flip events
  • dark pool large-print events
  • ETF flow / creation-redemption anomalies
  • cross-asset divergence events
  • liquidity shock events
  • earnings/event-calendar events
Output:
  Unified event stream:
    event_id
    symbol
    timestamp T
    event_type
    proposed side LONG/SHORT
    triggering source
    source confidence
    ATR at T-1
    liquidity state at T
    regime context at T
Important distinction:
  Event generation proposes candidate opportunities.
  It does not decide trades.
=================================================================================
STAGE 3: REGIME CONTEXT — FEATURES FIRST, HMM ONLY IF EARNED
=================================================================================
Regime vector attached to every event:
  • volatility regime:
      VIX percentile, realized volatility percentile, intraday vol state
  • trend regime:
      trending/ranging via statistical tests and multi-horizon structure
  • liquidity regime:
      spread, depth, volume profile, turnover, quote stability
  • sector dispersion regime:
      sector breadth, correlation, dispersion, beta concentration
  • macro/event regime:
      Fed cycle, CPI/FOMC proximity, earnings season, yield regime
  • time-of-day/session regime:
      open, mid-session, close, lunch lull, post-event window
Optional:
  • HMM regime state
HMM inclusion rule:
  HMM is not mandatory.
  It is included only if it improves locked walk-forward,
  purged OOF, after-cost expected utility versus explicit
  volatility/trend/liquidity/macro regime features.
Regime-weighting guardrail:
  Regime context may condition models and thresholds.
  It may not freely curve-fit horizon weights unless the weighting model
  proves incremental OOF utility lift after shrinkage and embargoed validation.
=================================================================================
STAGE 4: PARALLEL LABELING — TRIPLE-BARRIER + TREND-SCANNING
=================================================================================
Every event receives both label families.
Triple-barrier labels:
  • stop distance, usually ATR-scaled
  • target distance, usually ATR-scaled
  • vertical timeout
  • output:
      WIN / LOSS / TIMEOUT
  • auxiliary outputs:
      time-to-hit
      max adverse excursion
      max favorable excursion
      realized R
      path quality
Trend-scanning labels:
  • statistical trend significance over candidate windows
  • t-statistic
  • signed magnitude
  • direction
  • horizon-specific trend strength
Label use:
  • one production target is selected per strategy role
  • the other label family remains available as diagnostic features
  • both label families are stored for model comparison
  • label choice itself is evaluated by walk-forward OOF performance
Hard rule:
  Label horizons, stops, targets, and vertical barriers are defined
  before validation. No post-hoc best-cell selection without DSR/PBO/CSCV
  correction.
=================================================================================
STAGE 5: FEATURE LAYER — SIGNAL FEATURES VS EXECUTION FEATURES
=================================================================================
Features are explicitly separated into two groups.
A. SIGNAL FEATURES
Used to predict whether the event has directional edge.
Examples:
  • event type and source features
  • price/volume structure
  • volatility state
  • cross-asset confirmation/divergence
  • options flow imbalance
  • dealer positioning
  • dark-pool context
  • news/sentiment shock
  • sector/market context
  • macro/event-calendar context
  • trend-scanning diagnostics
  • triple-barrier diagnostics from prior analogous events
  • regime vector
B. EXECUTION FEATURES
Used to predict whether the signal can be monetized.
Examples:
  • bid-ask spread
  • depth / quote imbalance
  • quote stability
  • trade sign autocorrelation
  • order-flow toxicity / VPIN-style features
  • quote/trade intensity
  • realized sub-minute volatility
  • expected slippage
  • fill probability
  • adverse selection probability
  • time-of-day liquidity
  • market impact estimate
Feature neutralization:
  Neutralization is role-specific, not universal.
  Apply neutralization when the target is idiosyncratic alpha:
    • remove market beta exposure
    • remove sector exposure
    • remove volatility exposure
    • remove liquidity exposure
  Do not neutralize away exposures when the strategy role is explicitly
  to harvest or time those premia.
  Neutralization policy is pre-registered per strategy role.
=================================================================================
STAGE 6: PER-HORIZON SIGNAL MODELS
=================================================================================
Horizons:
  • 1m
  • 5m
  • 15m
  • 60m
Baseline rule:
  XGBoost or CatBoost is the mandatory foundation model at every horizon.
Optional model additions:
  • ModernTCN
  • LSTM/GRU
  • TimesNet
  • PatchTST
  • N-HiTS
  • iTransformer
  • other specialized architecture
Inclusion rule:
  Additional models are not included by default.
  Each must beat the horizon baseline on:
    • purged OOF predictions
    • embargoed walk-forward windows
    • after-cost expected utility
    • capacity-aware performance
    • stability across regimes
    • no unacceptable calibration degradation
Output per horizon:
  P_signal_1m
  P_signal_5m
  P_signal_15m
  P_signal_60m
Each output must be OOF for downstream training.
=================================================================================
STAGE 7: HORIZON FUSION — SHRUNK REGIME-CONDITIONAL WEIGHTING
=================================================================================
Goal:
  Combine horizon-specific signal probabilities into one signal probability.
Inputs:
  • P_signal_1m
  • P_signal_5m
  • P_signal_15m
  • P_signal_60m
  • regime vector
  • cross-horizon agreement
  • horizon-specific calibration quality
  • recent regime-conditional performance
Output:
  P_signal_combined
Weak-spot fix:
  Regime-aware horizon weighting is constrained.
  The weighting model must use:
    • OOF-only horizon predictions
    • shrinkage toward global average weights
    • minimum sample requirements per regime
    • monotonic/regularized constraints where applicable
    • locked walk-forward evaluation
    • degradation fallback to global weights if regime coverage is weak
No free-form regime weighting is allowed unless it proves incremental
after-cost utility lift.
=================================================================================
STAGE 8: META-LABELING — SINGLE META MODEL USING BOTH LABEL FAMILIES
=================================================================================
Meta-model:
  XGBoost/CatBoost meta-labeler.
Inputs:
  • OOF horizon predictions
  • fused signal probability
  • triple-barrier diagnostics
  • trend-scanning diagnostics
  • regime vector
  • volatility features
  • trade geometry:
      side, stop, target, timeout, R:R
  • cross-horizon agreement
  • signal/execution separation flags
Target:
  meta_label = 1 if the pre-defined trade setup wins under the selected
  production label definition, else 0.
Output:
  raw P_trade
Design choice:
  Use one meta-model consuming both label families, not separate TB and
  TS meta-models plus synthesis, unless dual-meta proves incremental
  OOF utility lift.
=================================================================================
STAGE 9: CALIBRATION AND UNCERTAINTY
=================================================================================
Calibration:
  • isotonic or Platt calibration
  • trained only on proper walk-forward calibration windows
  • evaluated per regime
  • monitored with ECE / Brier score / reliability curves
Output:
  calibrated P_trade
Uncertainty:
  Conformal or quantile-based interval methods may be used to produce:
    p_low
    p_high
    interval width
    coverage diagnostics
Important limitation:
  Conformal methods do not magically guarantee coverage under arbitrary
  market distribution shift.
Operational interpretation:
  • validate empirical coverage per regime
  • widen intervals when regime coverage degrades
  • lower confidence when conformal coverage breaks
  • block or reduce size when interval uncertainty is too wide
Output:
  calibrated P_trade
  p_low
  p_high
  uncertainty_score
  coverage_health
=================================================================================
STAGE 10: EXECUTION AND MICROSTRUCTURE MODEL
=================================================================================
Purpose:
  Convert theoretical signal edge into executable edge.
Inputs:
  • calibrated P_trade
  • p_low / p_high
  • spread
  • depth
  • quote imbalance
  • liquidity regime
  • expected volatility during holding period
  • order size
  • time of day
  • order type candidates
  • recent fills/slippage
  • adverse selection features
Models estimate:
  • expected fill price
  • fill probability
  • expected slippage
  • market impact
  • adverse selection risk
  • execution shortfall distribution
  • optimal order type:
      market, limit, passive, aggressive, staged
Output:
  execution_adjusted_cost
  expected_fill
  fill_probability
  adverse_selection_score
  executable_EV_components
Hard rule:
  Flat transaction-cost assumptions are not enough for short-horizon trades.
  The final decision must use execution-adjusted EV.
=================================================================================
STAGE 11: CANDIDATE UTILITY AND CROSS-SECTIONAL RANKING
=================================================================================
When multiple candidates fire, they are ranked by expected utility,
not a heuristic product.
For each candidate:
  EV_net =
      P_trade × R_target
      - (1 - P_trade) × R_stop
      - execution_cost
      - expected_market_impact
Confidence-adjusted EV:
  EV_lower uses p_low.
  EV_base uses calibrated P_trade.
  EV_upper uses p_high.
Utility score may include:
  • EV_lower
  • expected net return
  • variance / downside risk
  • correlation with current book
  • liquidity/capacity
  • drawdown state
  • regime confidence
  • execution quality
  • opportunity cost of capital
Output:
  ranked candidate list
  marginal utility per unit of capital/risk
  allocation priority
Portfolio rule:
  The system does not ask only, “Is this trade good?”
  It asks, “Is this trade the best use of risk budget right now?”
=================================================================================
STAGE 12: POSITION SIZING — FRACTIONAL KELLY WITH CONSTRAINTS
=================================================================================
Sizing inputs:
  • calibrated P_trade
  • p_low / p_high
  • EV_net after execution
  • stop/target geometry
  • current portfolio exposure
  • correlation with open positions
  • realized drawdown
  • volatility regime
  • liquidity regime
  • risk budget remaining
  • opportunity rank
Sizing rule:
  • fractional Kelly using conservative probability input, usually p_low
  • drawdown-constrained reduction
  • correlation-adjusted scaling
  • liquidity/capacity cap
  • max position cap
  • max sector/theme/regime exposure cap
  • no trade if lower-bound EV is insufficient
Why no RL by default:
  RL sizing is allowed only as a research candidate.
  It must beat fractional Kelly / expected utility sizing on locked
  walk-forward, after-cost, risk-adjusted utility without reward hacking.
=================================================================================
STAGE 13: FINAL DECISION POLICY
=================================================================================
Decision inputs:
  • calibrated P_trade
  • p_low / p_high
  • EV_net
  • EV_lower
  • EV_upper
  • execution quality
  • candidate rank
  • proposed size
  • regime confidence
  • calibration health
  • conformal coverage health
  • drift status
Decision rules:
  TRADE:
    EV_lower >= trade_threshold
    AND execution quality passes
    AND calibration health passes
    AND coverage health passes
    AND drift gates pass
    AND portfolio risk budget is available
  AVOID:
    EV_upper <= avoid_threshold
    OR execution quality fails
    OR drift/calibration gates hard-fail
    OR trade is dominated by better-ranked candidates
  WAIT:
    Otherwise.
Output:
  TRADE / WAIT / AVOID
  side
  size
  stop
  target
  timeout
  preferred order type
  expected fill
  execution-adjusted EV
  confidence interval
  reason codes
=================================================================================
STAGE 14: TRADER OUTPUT
=================================================================================
Example output:
  Decision:        TRADE LONG
  Symbol:          SPY
  P(success):      0.64
  Interval:        0.58 - 0.70
  EV_net:          +0.42 R after execution costs
  EV_lower:        +0.18 R
  Position size:   2.3% of capital
  Stop:            $462.18
  Target:          $464.85
  Timeout:         15:30 ET
  Order type:      limit, allow aggressive crossing if fill risk rises
  Expected fill:   $462.42
  Slippage est.:   0.5 bp
  Fill prob.:      96%
  Regime:          low VIX, trending, mid-session, liquid
Reason codes:
  • 60m signal supportive
  • 15m structure confirms continuation
  • 5m entry confirmed
  • 1m execution favorable
  • triple-barrier diagnostics bullish
  • trend-scanning diagnostics bullish
  • execution quality high
  • cross-sectional rank: 2 of 5
  • allocation priority: high
  • calibration health: pass
  • conformal coverage health: pass
=================================================================================
STAGE 15: GOVERNANCE, VALIDATION, AND EVIDENCE GATES
=================================================================================
Validation discipline:
  • purged CV with embargo at every model layer
  • OOF predictions only for downstream models
  • walk-forward validation with locked windows
  • sample uniqueness weighting
  • no silent fallback logic
  • all feature availability timestamps enforced
  • all thresholds pre-registered before validation
Overfit controls:
  • Deflated Sharpe Ratio
  • Probability of Backtest Overfitting
  • Combinatorially Symmetric Cross-Validation
  • reality-check / multiple-hypothesis correction
  • best-cell claims require DSR/PBO-adjusted evidence
Monitoring:
  • ECE by regime
  • Brier score by regime
  • conformal coverage by regime
  • drift detection
  • execution slippage drift
  • fill probability drift
  • feature distribution drift
  • label distribution drift
  • realized EV versus predicted EV
Component inclusion gate:
  A component is included only if it improves:
    • purged OOF performance
    • locked walk-forward performance
    • after-cost expected utility
    • calibration or uncertainty quality
    • execution-adjusted realized edge
    • robustness across relevant regimes
Components that fail the gate are removed, not retained for complexity.
=================================================================================
REVISED ARTIFACT COUNT
=================================================================================
Baseline trainable artifacts:
  • 4 horizon signal models
  • 4 horizon fusion/calibration components, if needed
  • 1 regime context model/layer
  • 1 constrained horizon-weighting layer
  • 1 meta-labeling model
  • 1 calibration model
  • 1 uncertainty/conformal wrapper
  • 1 execution/microstructure model
  • 1 cross-sectional utility/ranking model
Rule-based / constrained modules:
  • fractional Kelly sizing
  • risk caps
  • final EV decision policy
  • hard-fail governance gates
Optional earned artifacts:
  • additional sequence/deep models per horizon
  • HMM regime model
  • dual-meta architecture
  • RL sizing agent
Optional artifacts are included only after proving incremental
walk-forward, after-cost, capacity-aware expected utility lift.
=================================================================================
SUMMARY OF FIXES VERSUS PRIOR VERSION
=================================================================================
  1. Signal edge, execution edge, and portfolio edge are explicitly separated.
  2. Regime-aware weighting is constrained with shrinkage, minimum sample
     requirements, and fallback to global weights.
  3. Conformal uncertainty is no longer overclaimed as guaranteed under all
     distribution shift; it is monitored and trusted only while coverage holds.
  4. Feature neutralization is strategy-role-specific, so it does not remove
     intended beta, volatility, liquidity, or sector-timing edge.
  5. Cross-sectional ranking is based on expected utility and risk-budget
     allocation, not a heuristic probability × EV score.
  6. Execution modeling is mandatory for realized edge, especially at 1m/5m.
  7. Optional sophisticated layers are allowed, but only if they beat the
     simpler baseline under strict OOF, walk-forward, after-cost evaluation.
=================================================================================
EMPIRICALLY HONEST POSITION
=================================================================================
This is the maximum-edge target architecture.
The architecture does not assume edge comes from model complexity alone.
It assumes edge comes from the combination of:
  • better event definition
  • leakage-safe labels
  • multi-horizon signal estimation
  • regime-aware but constrained adaptation
  • calibrated probabilities
  • uncertainty-aware decisions
  • microstructure-aware execution
  • cross-sectional capital allocation
  • conservative sizing
  • aggressive overfit control
The system remains ambitious, but its ambition is now aimed at the parts of
published research most consistently tied to realized trading edge.
=================================================================================


====================================================================================================
# SOURCE DOCUMENT: ED_CONSOLE_MASTER_OPERATING_CONTRACT_AND_HANDOFF.md
**Date:** 2026-07-11 | **Role:** Master operating contract + handoff | **Original size:** 18,090 bytes
====================================================================================================

# ED CONSOLE — MASTER OPERATING CONTRACT AND HANDOFF

## 1. Governing standard

All Ed Console work must meet an institutional, MIT-grade, Bloomberg/Reuters-terminal, real-money-capable standard.

Allowed governing labels:

- PROVEN / NOT_PROVEN
- APPROVED / NOT_APPROVED
- CLOSED_WITH_EVIDENCE / NOT_CLOSED
- PASS / FAIL

There is no acceptable “mostly,” “substantially,” “good enough,” or “closed with limitations” category.

## 2. Binary closure rule

If any material requirement remains unproven, the parent lane remains NOT_CLOSED.

A narrow proof may remain valid, but it cannot close a broader lane.

Example:

- ECON_01_DENOMINATOR_FIX = CLOSED_WITH_EVIDENCE
- ECON_01_PARENT = NOT_CLOSED

## 3. Universality

Universality is a hard rule.

No fix, proof, or audit may be limited to one ticker, horizon, route, model, card, environment, or representative example unless ticker-/horizon-/route-agnostic construction is proven.

Where applicable, proof must cover:

- SPY, QQQ, IWM
- guest tickers
- 1c, 5c, 15c, 60c
- live, replay, training, evaluation, calibration, promotion, persistence, and UI
- stale, missing, fallback, and degraded states
- RTH and non-RTH behavior

Sampled tests may support evidence, but universality must come from construction.

## 4. End-to-end scope

End-to-end is a hard rule.

Every material mission must examine the entire connected path:

raw data → normalization → features → model input → artifact selection → inference → calibration → fusion/meta → policy/sizing → persistence → replay/reconstruction → UI/operator output → realized outcome evaluation

Known tasks are minimum requirements, not scope boundaries.

All materially connected defects are in scope.

## 5. Root-cause-only fixes

All fixes must address the root cause universally.

Forbidden:

- one-ticker or one-route exceptions
- token or regex evasion
- file-specific exemptions
- silent defaults
- assertion weakening
- test deletion or weakening
- threshold lowering to manufacture green
- suppressing errors or logs
- documentation-only closure
- treating green CI as semantic proof

Required:

- prove root cause
- search equivalent paths repo-wide
- implement universal architecture
- add adversarial tests
- add mechanical recurrence prevention
- validate at the exact final SHA

## 6. Money-path scrutiny

Every trade-determinative path receives maximum scrutiny.

This includes:

- primitives and timestamps
- ticker/horizon identity
- feature construction
- model calculations
- artifact and calibration loading
- fusion/meta/regime/Monte Carlo/options context
- policy, sizing, risk, and tradeability
- persistence and replay
- UI display and explanations
- realized outcome evaluation

Treat all money-path logic as P0/P1 until disproven.

No assumptions without code proof.

## 7. Seven-layer stack

The current executable seven-layer stack must be derived from the repository, not memory.

The repo must mechanically identify:

- exactly seven governed layers
- canonical names
- implementation files/functions
- production/training/evaluation entry points
- inputs and outputs
- upstream/downstream dependencies
- ticker/horizon scope
- artifacts and calibrators
- fallback modes and runtime classes

Every layer and every cross-layer boundary must be audited.

One unproven layer means:

- FULL_SEVEN_LAYER_STACK = NOT_CLOSED
- MONEY_PATH_CORRECTNESS = NOT_PROVEN

## 8. Model-by-model questions

For every model/layer/horizon/ticker, answer:

1. CODE CORRECTNESS — Is the mathematics and implementation correct?
2. WIRING CORRECTNESS — Are the correct inputs and downstream consumers used?
3. EVALUATION CORRECTNESS — Are training, replay, calibration, and promotion free of leakage/drift?
4. PREDICTIVE VALIDITY — Does it beat appropriate baselines out of sample with economic value?

A model can pass one and fail another.

Required proof dimensions:

- implementation identified
- mathematical specification
- independent reference calculation
- input/output correctness
- feature schema parity
- ticker/horizon isolation
- point-in-time correctness
- no current/future leakage
- model/calibration version pinning
- training/evaluation correctness
- live wiring correctness
- downstream consumer fidelity
- stale/missing/fallback correctness
- golden-file parity
- invariants
- ablation/incremental value
- baseline superiority
- per-ticker/per-horizon validity
- mechanical enforcement
- exact-final-SHA CI

Final status: CORRECT / WRONG / NOT_PROVEN.

## 9. Predictive validity

Plumbing correctness does not prove predictive validity.

Required:

- shuffled-label and negative controls
- purged temporal validation
- embargo
- fold isolation
- no meta leakage
- calibration correctness
- beat-the-baseline tests
- per-ticker, per-horizon, and per-regime results
- execution-aware economics
- sufficient sample size and confidence intervals
- cost-adjusted out-of-sample evidence

Accuracy alone is insufficient.

Until proven:

- PREDICTIVE_VALIDITY = NOT_PROVEN
- REAL_MONEY_APPROVAL = NOT_APPROVED

## 10. Lookahead and leakage

All paths must prove:

- strict as-of semantics
- no post-event features
- no centered rolling windows
- no full-series normalization
- no fitting on validation/test data
- no latest-row lookup in historical paths
- no current singleton state in replay
- no future artifact use
- no ticker/horizon/cache contamination
- no in-sample meta predictions presented as OOF
- no calibration leakage
- no fold-state reuse

Required adversarial proofs include future-row append/mutation invariance, other-ticker/horizon mutation invariance, artifact/calibration mutation invariance, duplicate/out-of-order handling, and timezone/session/DST boundaries.

## 11. Meta learners

All meta/stacking paths must prove:

- base predictions are OOF
- deployed/full-data artifacts are not scored when governed folds exist
- in-sample fallback is labeled
- fallback cannot masquerade as governed OOF evidence
- fallback-trained metas cannot support automatic promotion
- missing base outputs are governed
- feature ordering is locked
- calibration inputs are fold-correct
- overfit-base inheritance trap passes
- corrupt/legacy manifests never upgrade to governed

Silent in-sample substitution is a P1 defect.

## 12. Versioning and artifacts

Historical evaluation/replay must never silently use current artifacts.

Required identities:

- ticker
- horizon
- model family/version
- feature schema hash
- training cutoff
- calibration version/cutoff
- artifact/bundle hash
- fold identity

Fail closed on missing, corrupt, mismatched, current-pointer, or stale-cache artifacts.

## 13. Feature parity

Training and inference must use identical:

- feature names/order
- dtypes
- missingness
- scaling/clipping/encoding/normalization
- ticker/horizon identity

Required golden chain:

raw input → engineered features → tensor/matrix → raw output → calibrated output → fused/meta output → policy output

Intentional golden changes require reviewed regeneration.

## 14. Fallback/degraded modes

Fallback behavior must be explicit, governed, provenance-visible, and mechanically classified.

Forbidden:

- silent neutral or zero fill
- silent current-artifact fallback
- silent reduced stack
- silent guest anchor
- silent stale state
- silent missing context

Approved neutral fill must be explicit and machine-readable.

## 15. Live/replay/training parity

Live, replay, training, and evaluation must have governed equivalent semantics.

Prove identical definitions for features, missingness, ticker/horizon identity, model/calibration versions, timestamp semantics, fallback classification, output contracts, and reconstructable decisions.

Calling the same function is not enough; actual inputs and meanings must match.

## 16. RTH

Any behavior dependent on real market conditions must be proven during applicable RTH.

Forbidden:

- simulated RTH proof
- after-hours substitution
- stale-data proof presented as live
- old-SHA runtime evidence used for new closure

RTH-gated lanes remain NOT_CLOSED until actual RTH evidence exists.

U.S. equities open is governed around 8:30 AM Central.

## 17. Exact SHA

Every closure must capture:

- base SHA
- final SHA
- remote SHA
- local/remote equality
- committed file list
- hook result
- push result
- exact CI runs at exact final SHA

Green CI at an old SHA does not close a newer tip.

Local pass is not closure.

## 18. Four required remote checks

- Objective Audit
- Pytest Full Suite
- Hardening Gates
- Schwab CSV First Guard

All four must pass at the exact final SHA.

Green CI proves gate execution, not semantic correctness.

## 19. Mechanical enforcement

Memory and prose are insufficient.

Important rules must be enforced through schemas, registries, scanners, AST/source locks, invariants, mutation tests, negative fixtures, CI, manifests, board reconciliation, and contradiction detection.

A defect is not fully fixed until recurrence is mechanically prevented where feasible.

## 20. Closure gate

Before accepting CLOSED_WITH_EVIDENCE, verify:

- no material NOT_PROVEN
- no correctness/leakage/universality/runtime/observability/reproducibility limitation
- no missing mechanical lock
- no parent/sub-lane contradiction
- no old-SHA evidence
- no real-money inference

Any contradiction means NOT_CLOSED.

Agents may recommend closure; the gatekeeper independently decides it.

## 21. Parent/sub-lane rule

Sub-lanes can close independently.

They never automatically close their parent.

Every record must show:

- parent lane
- sub-lane
- sub-lane status
- parent status
- preserved proven facts
- remaining requirements

## 22. Agent autonomy

Claude and Cursor must receive:

- mission objective
- institutional standard
- known evidence
- minimum proof requirements
- binary acceptance criteria
- stop conditions
- broad authority to investigate and fix materially connected defects

Do not micromanage exact files/functions unless drift is proven.

Specific proof obligations are minimums, not boundaries.

## 23. No over-prescription

Avoid prompts that unnecessarily say:

- touch only these files
- fix only this function
- run only these tests
- stop when this narrow component passes

Preferred prompt structure:

MISSION OBJECTIVE → STANDARD → CURRENT EVIDENCE → OPEN QUESTIONS → MINIMUM PROOF → BROAD AUTHORITY → BINARY ACCEPTANCE → STOP CONDITIONS → FINAL PACKET

## 24. Multi-agent cross-talk

When Claude and Cursor are active:

- do not issue overlapping work
- wait for complete findings
- do not pre-judge one agent with the other’s partial result
- reconcile outputs before dispatching more work
- identify overlap, contradiction, and cross-layer effects
- maintain one master board

Agent outputs are evidence, not truth.

## 25. Independent packet review

For every Claude/Cursor packet, independently evaluate:

- claim/evidence match
- universality
- root-cause completeness
- adjacent defects
- honest labels
- exact-final-SHA proof
- internal contradictions
- real-money implications

Do not merely summarize packets.

Act as gatekeeper.

## 26. Prompt continuity

After assessing a completed packet, provide the exact next prompt when new work is appropriate.

Exception: do not issue another prompt while an agent is still working or when it would create cross-talk.

## 27. Material progress

Work must materially advance:

- architecture correctness
- data truth
- money-path correctness
- reliability
- observability
- governance
- operator trust
- real-money readiness

Avoid cosmetic work, low-impact busywork, repeated narrow loops, and documentation without enforcement.

Use pre-RTH time for substantial repo-local work.

## 28. Board preservation

Maintain a master board with:

- parent/sub-lane relationships
- active lanes
- proven/unproven dimensions
- blockers
- external gates
- next actions
- final SHAs
- CI status

No lane disappears because another mission becomes active.

## 29. Drift recovery

If a prior status was inflated:

1. state the error
2. downgrade the parent
3. preserve valid narrow proofs
4. add a drift-recovery entry
5. list remaining requirements
6. add recurrence prevention
7. never silently carry forward the inflated label

## 30. No assumptions

Do not infer correctness from file names, function names, docstrings, green tests, agent claims, historical architecture descriptions, intended design, or representative examples.

Get code proof.

If proof is absent: NOT_PROVEN.

## 31. Test quality

Tests must prove semantics, not just execution.

Use:

- golden files
- independent references
- adversarial fixtures
- mutation tests
- negative controls
- deliberate defect injection
- invariants
- cross-ticker/horizon cases
- stale/missing/fallback cases
- artifact mismatch cases
- leakage traps

A test using the same defective implementation is not independent proof.

## 32. Governance performance

Gate performance may improve only with no loss of protection.

Allowed:

- phase batching
- scratchpad pipelining
- staged-file ownership
- safe deterministic caching
- removing proven redundancy after authorization

Required:

- unknown scope → full bundle
- selector/map/hook changes → full bundle
- failures never cached
- stale results never reused
- remote full suite preserved
- self-protection and invalidation tests

Speed alone is not closure.

## 33. Enforcement removal

Do not remove apparently duplicate enforcement until exact overlap, ordering, worktree state, timing gap, failure semantics, and defense-in-depth value are proven.

Removal requires authorization.

## 34. Real-money approval

No component closure implies real-money approval.

Approval is a separate operator decision requiring all institutional lanes, all seven layers, money-path contracts, predictive validity, risk/sizing, execution assumptions, RTH proof, no material NOT_PROVEN, independent final audit, and explicit operator approval.

Until then:

REAL_MONEY_APPROVAL = NOT_APPROVED

## 35. Governing status template

AUTHORITATIVE_SEVEN_LAYER_INVENTORY = PROVEN / NOT_PROVEN
ALL_SEVEN_LAYERS_ACCOUNTED_FOR = PROVEN / NOT_PROVEN
ALL_SEVEN_LAYERS_CODE_CORRECT = PROVEN / NOT_PROVEN
ALL_SEVEN_LAYERS_WIRED_CORRECTLY = PROVEN / NOT_PROVEN
ALL_CROSS_LAYER_CONTRACTS = PROVEN / NOT_PROVEN
POINT_IN_TIME_CORRECTNESS = PROVEN / NOT_PROVEN
NO_LOOKAHEAD_BIAS = PROVEN / NOT_PROVEN
NO_META_LEARNER_LEAKAGE = PROVEN / NOT_PROVEN
MODEL_VERSION_PINNING = PROVEN / NOT_PROVEN
CALIBRATION_VERSION_PINNING = PROVEN / NOT_PROVEN
FEATURE_SCHEMA_PARITY = PROVEN / NOT_PROVEN
PURGED_TEMPORAL_VALIDATION = PROVEN / NOT_PROVEN
EMBARGO_ENFORCEMENT = PROVEN / NOT_PROVEN
SHUFFLED_LABEL_CONTROL = PASS / FAIL / NOT_PROVEN
BEATS_BASELINE = PROVEN / NOT_PROVEN
PREDICTIVE_VALIDITY = PROVEN / NOT_PROVEN
END_TO_END_MONEY_PATH = PROVEN / NOT_PROVEN
FULL_SEVEN_LAYER_STACK = CLOSED_WITH_EVIDENCE / NOT_CLOSED
REAL_MONEY_APPROVAL = NOT_APPROVED / APPROVED

## 36. Gatekeeper review form

LANE =
PARENT_LANE =
FINAL_SHA =
REMOTE_SHA =
LOCAL_REMOTE_EQUALITY =

WHAT EXACTLY WAS PROVEN?
WHAT REMAINS NOT_PROVEN?

DO LIMITATIONS TOUCH:
- correctness?
- universality?
- leakage?
- versioning?
- calibration?
- runtime/RTH?
- observability?
- reproducibility?
- enforcement?

IS THE CLAIM BROADER THAN THE EVIDENCE?
IS ANY EVIDENCE FROM AN OLD SHA?
IS REQUIRED LIVE/RTH PROOF MISSING?
IS A RECURRENCE LOCK MISSING?
DOES GREEN CI ONLY PROVE EXECUTION?
DOES A SUB-LANE IMPROPERLY CLOSE A PARENT?
WOULD AN INDEPENDENT INSTITUTIONAL REVIEWER CALL THIS COMPLETE?

DECISION = CLOSED_WITH_EVIDENCE / NOT_CLOSED
REASON =
REOPENED_ITEMS =
NEXT MATERIAL MISSION =

## 37. Required final-packet fields

MISSION
RESULT
BASE_HEAD
FINAL_HEAD
REMOTE_HEAD
HEAD_REMOTE_EQUALITY
ROOT_CAUSE
SCOPE
UNIVERSALITY_PROOF
FILES_CHANGED
FILES_ADDED
FILES_DELETED
WORKTREE_STATUS
TESTS_RUN
TEST_RESULTS
HOOK_RESULT
PUSH_RESULT
REMOTE_CHECK_1
REMOTE_CHECK_2
REMOTE_CHECK_3
REMOTE_CHECK_4
PROVEN_DIMENSIONS
NOT_PROVEN_DIMENSIONS
LIMITATIONS
MECHANICAL_LOCKS
BOARD_UPDATES
RESIDUAL_OPEN_ITEMS
NEXT_BLOCKER
PARENT_STATUS
SUB_LANE_STATUS
REAL_MONEY_APPROVAL

## 38. New-window handoff

At a new window:

1. Upload/paste this contract.
2. Provide latest final packet.
3. Provide current local and remote SHA.
4. State active agent and mission.
5. Do not issue overlapping work until active findings are complete.
6. Reconstruct the board from evidence.
7. Apply binary labels.
8. Continue with the highest-value executable money-path work.
9. Preserve valid sub-proofs without inflating parent closure.

Suggested opening:

Use the attached Ed Console Master Operating Contract as controlling.
Current HEAD:
Remote HEAD:
Active agent:
Active mission:
Latest final packet:
Open parent lanes:

Do not assume closure. Reconcile evidence, preserve universality and end-to-end scope, avoid cross-talk, and act as independent gatekeeper.

## 39. Non-negotiable summary

UNIVERSALITY = HARD RULE
END_TO_END = HARD RULE
ROOT_CAUSE = REQUIRED
BINARY STATUS = REQUIRED
MONEY_PATH SCRUTINY = MAXIMUM
ALL SEVEN LAYERS = ALWAYS IN SCOPE
NO SCOPED PARENT CLOSURE
NO GREEN-CI SEMANTIC INFERENCE
NO REPRESENTATIVE-ONLY PROOF
NO TOKEN/REGEX EVASION
NO SILENT FALLBACK
NO OLD-SHA CLOSURE
NO BLIND AGENT-PACKET ACCEPTANCE
NO MULTI-AGENT CROSS-TALK
CLAUDE/CURSOR AUTONOMY = REQUIRED
MECHANICAL ENFORCEMENT = REQUIRED
REAL-MONEY APPROVAL = SEPARATE
ANY MATERIAL NOT_PROVEN = PARENT NOT_CLOSED

## 40. Core operating statement

The objective is to prove, universally and end to end, whether every layer of the seven-layer stack is correctly specified, coded, trained, evaluated, calibrated, wired, consumed, leakage-free, version-pinned, universal, mechanically protected, and predictively/economically valid.

Until all are proven:

MODEL_STACK_CODE_CORRECTNESS = NOT_PROVEN
MODEL_STACK_WIRING_CORRECTNESS = NOT_PROVEN
MODEL_STACK_EVALUATION_CORRECTNESS = NOT_PROVEN
MODEL_STACK_PREDICTIVE_VALIDITY = NOT_PROVEN
END_TO_END_MONEY_PATH = NOT_PROVEN
FULL_SEVEN_LAYER_STACK = NOT_CLOSED
REAL_MONEY_APPROVAL = NOT_APPROVED


====================================================================================================
# SOURCE DOCUMENT: daily_operations.md
**Date:** 2026-04-03 | **Role:** APPENDIX: daily operations checklist (operational, preserved for completeness) | **Original size:** 2,776 bytes
====================================================================================================

# 📅 Daily System Operations Checklist (Trading Engine)
## Phase: Controlled Data Accumulation & Observation

---

# 🎯 OBJECTIVE
Maintain a **clean, validated 1-minute canonical system** while collecting enough data to perform a **measured accumulation review**.

This phase is **NOT for development or tuning**.  
This is **observation, validation, and logging only**.

---

# ⏰ DAILY SCHEDULE

## 🟢 During Market Hours (Passive Monitoring Only)
**Time:** 9:30 AM – 4:00 PM ET

### ✅ What to do:
- Ensure system is **running continuously**
- Confirm:
  - App/server is live
  - Data is updating (no freezes)
- OPTIONAL (quick glance only):
  - Spot-check 1–2 tickers for live updates

### ❌ What NOT to do:
- Do NOT analyze data deeply
- Do NOT make changes
- Do NOT draw conclusions intraday

---

## 🔵 End of Day (PRIMARY TASK)
**Time:** ~4:10–4:20 PM ET (after market close)

### 🔁 Run EOD Review Script
```bash
python tools/eod_pin_neutral_review.py
```

---

## 📊 EOD REVIEW OUTPUT (What gets logged automatically)

### 1. Population Metrics
- Total 1m snapshots
- `pin_neutral` count
- % of total

### 2. Labeling Metrics
- `pin_neutral` rows with `outcome_filled = 1`
- Unfilled rows

### 3. Issue 19 Metrics
- Tier1 count
- Tier2 count
- Rejection reason (if any)

### 4. Diagnostics (if enabled)
- `bias_signal` distribution
- `pin_strength` stats
- `net_delta` / `net_gamma`

### 5. Output File
Stored at:
data/eod_reviews/YYYY-MM-DD_pin_neutral_review.json

---

# 🟡 DAILY VALIDATION CHECK (1–2 MINUTES)

### ✅ System Health
- Script executed successfully
- JSON file created
- No errors

### ✅ Data Presence
- New 1m data exists
- Zones are populated

### ⚠️ Observation Only (NO ACTION)
- `pin_neutral` count (may be 0 — OK)
- Issue 19 pools (may be 0 — expected early)

---

# 🚨 ANOMALY WATCH
- Large timestamp gaps
- Missing data blocks
- Sudden drop to zero activity

---

# 📆 WEEKLY / ACCUMULATION CHECKPOINT

## ⏳ When to Review
- Minimum: 3–5 trading days  
- Ideal: 10+ trading days  

---

## 📊 What to Evaluate

### 1. `pin_neutral` Emergence
- Count
- % of total

### 2. Labeling Integrity
- Are rows being filled correctly?

### 3. Issue 19 Behavior
- Are pools forming?

### 4. Outcome Quality
- Up / Down / Flat distribution

### 5. Near-Miss Analysis
- Are thresholds too strict?

---

# 🧠 DECISION FRAMEWORK

### Case A — Healthy
Keep system unchanged

### Case B — Rare
Consider adjustments

### Case C — Nonexistent
Re-evaluate logic

### Case D — Pipeline issue
Investigate

---

# ❌ STRICT DO NOTS

- Do NOT modify core logic
- Do NOT mix 5m into 1m
- Do NOT force signals
- Do NOT overanalyze intraday

---

# 🔥 FINAL RULE
Observe. Log. Accumulate. Do NOT interfere.


====================================================================================================
# SOURCE DOCUMENT: three_account_plan.jsx
**Date:** 2026-03-04 | **Role:** APPENDIX: three-account capital plan (verbatim JSX artifact) | **Original size:** 47,755 bytes
====================================================================================================

import { useState } from "react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell, PieChart, Pie, ReferenceLine } from "recharts";

// ── SCORES from full universe ML run ─────────────────────────────────
const SC = {
  NET:{score:192.5,xgb:46.9,mc:53.2,sharpe:0.77,vol:50.3,prob:72.6,p10:-29.9,p90:160.9},
  UUUU:{score:173.4,xgb:30.8,mc:148.0,sharpe:1.13,vol:77.9,prob:78.8,p10:-33.1,p90:391.4},
  CEG:{score:159.6,xgb:36.8,mc:62.0,sharpe:0.75,vol:57.7,prob:69.6,p10:-37.4,p90:196.3},
  SOFI:{score:130.8,xgb:27.3,mc:74.6,sharpe:0.89,vol:58.4,prob:76.0,p10:-29.4,p90:207.9},
  CIFR:{score:113.8,xgb:-9.7,mc:361.9,sharpe:1.28,vol:114.0,prob:78.2,p10:-43.7,p90:952.5},
  KGC:{score:105.8,xgb:7.2,mc:182.9,sharpe:2.21,vol:45.1,prob:98.7,p10:43.7,p90:358.9},
  PLTR:{score:104.6,xgb:4.6,mc:207.2,sharpe:1.72,vol:62.8,prob:93.3,p10:12.4,p90:465.3},
  UEC:{score:102.6,xgb:18.1,mc:86.7,sharpe:0.86,vol:69.6,prob:69.4,p10:-42.1,p90:261.3},
  ALB:{score:88.0,xgb:19.9,mc:37.4,sharpe:0.46,vol:60.7,prob:58.5,p10:-47.6,p90:148.7},
  FSLR:{score:83.6,xgb:19.0,mc:35.1,sharpe:0.42,vol:59.5,prob:57.7,p10:-47.1,p90:147.9},
  ORCL:{score:80.2,xgb:18.3,mc:32.1,sharpe:0.46,vol:51.3,prob:61.5,p10:-39.7,p90:124.5},
  KLAC:{score:78.4,xgb:14.4,mc:59.4,sharpe:0.94,vol:45.7,prob:78.7,p10:-20.3,p90:159.7},
  CRWD:{score:78.0,xgb:18.4,mc:26.9,sharpe:0.41,vol:47.2,prob:60.4,p10:-38.9,p90:107.0},
  GOOGL:{score:65.6,xgb:10.7,mc:56.9,sharpe:1.40,vol:29.8,prob:91.6,p10:2.6,p90:118.4},
  GDX:{score:63.7,xgb:3.9,mc:110.6,sharpe:1.85,vol:37.8,prob:96.0,p10:21.1,p90:221.6},
  AEM:{score:62.8,xgb:1.0,mc:131.3,sharpe:2.18,vol:36.4,prob:98.3,p10:35.3,p90:245.6},
  GE:{score:62.3,xgb:8.0,mc:71.9,sharpe:1.58,vol:31.7,prob:94.3,p10:8.2,p90:147.1},
  CCJ:{score:58.6,xgb:4.9,mc:93.0,sharpe:1.23,vol:50.6,prob:85.2,p10:-10.6,p90:226.7},
  AVGO:{score:55.6,xgb:6.0,mc:78.0,sharpe:0.97,vol:53.6,prob:78.8,p10:-21.5,p90:208.4},
  TSLA:{score:55.5,xgb:6.4,mc:75.0,sharpe:0.85,vol:62.8,prob:72.1,p10:-33.9,p90:225.5},
  CAT:{score:55.4,xgb:8.2,mc:55.2,sharpe:1.32,vol:30.5,prob:90.7,p10:1.7,p90:116.6},
  NEM:{score:52.8,xgb:0.8,mc:111.6,sharpe:1.72,vol:40.5,prob:95.6,p10:17.8,p90:225.8},
  WPM:{score:52.4,xgb:1.2,mc:105.9,sharpe:1.86,vol:36.2,prob:96.7,p10:22.4,p90:203.3},
  LRCX:{score:50.9,xgb:5.4,mc:71.4,sharpe:1.02,vol:48.4,prob:80.4,p10:-18.8,p90:187.4},
  MU:{score:49.8,xgb:-3.8,mc:148.2,sharpe:1.43,vol:60.4,prob:88.3,p10:-6.4,p90:356.2},
  NVDA:{score:38.8,xgb:2.6,mc:66.3,sharpe:0.93,vol:49.8,prob:77.5,p10:-22.2,p90:178.9},
  RTX:{score:31.3,xgb:0.6,mc:59.2,sharpe:1.80,vol:23.8,prob:96.7,p10:14.5,p90:109.2},
  MSFT:{score:25.0,xgb:6.7,mc:2.5,sharpe:-0.07,vol:24.1,prob:49.0,p10:-26.5,p90:35.6},
  IEMG:{score:24.9,xgb:3.2,mc:25.4,sharpe:1.07,vol:16.8,prob:90.0,p10:0.0,p90:54.9},
  SPDW:{score:1.8,xgb:-2.9,mc:22.2,sharpe:1.07,vol:14.9,prob:89.3,p10:-0.5,p90:46.1},
  SOFI:{score:130.8,xgb:27.3,mc:74.6,sharpe:0.89,vol:58.4,prob:76.0,p10:-29.4,p90:207.9},
  SOXL:{score:41.3,xgb:-1.0,mc:107.8,sharpe:0.58,vol:111.5,prob:53.2,p10:-74.1,p90:368.7},
  SPXL:{score:-6.4,xgb:-7.9,mc:49.1,sharpe:0.74,vol:47.3,prob:73.2,p10:-28.0,p90:141.9},
  BND:{score:6.1,xgb:0.9,mc:5.7,sharpe:0.22,vol:4.7,prob:87.5,p10:-0.7,p90:12.2},
  VZ:{score:8.4,xgb:-0.9,mc:23.7,sharpe:0.74,vol:22.3,prob:80.5,p10:-9.9,p90:59.6},
  SCHD:{score:2.6,xgb:-1.6,mc:15.8,sharpe:0.70,vol:14.0,prob:82.9,p10:-4.7,p90:37.5},
  VOO:{score:1.8,xgb:-2.3,mc:18.8,sharpe:0.81,vol:15.8,prob:84.7,p10:-3.8,p90:43.2},
  SPYM:{score:1.4,xgb:-2.3,mc:18.0,sharpe:0.80,vol:15.9,prob:83.5,p10:-5.1,p90:43.0},
  KO:{score:7.4,xgb:-0.8,mc:19.2,sharpe:0.84,vol:15.8,prob:84.9,p10:-3.5,p90:44.0},
  PLTR:{score:104.6,xgb:4.6,mc:207.2,sharpe:1.72,vol:62.8,prob:93.3,p10:12.4,p90:465.3},
  COP:{score:-26.3,xgb:-8.6,mc:10.2,sharpe:0.17,vol:29.7,prob:57.2,p10:-27.8,p90:55.5},
  TQQQ:{score:-27.9,xgb:-14.1,mc:52.2,sharpe:0.64,vol:62.3,prob:63.9,p10:-44.1,p90:181.4},
  VNOM:{score:-9.7,xgb:-5.4,mc:21.3,sharpe:0.46,vol:33.6,prob:66.2,p10:-24.4,p90:75.2},
  AVUV:{score:4.2,xgb:-1.2,mc:17.7,sharpe:0.53,vol:22.1,prob:72.9,p10:-13.1,p90:53.3},
  MMATQ:{score:-999,xgb:0,mc:0,sharpe:0,vol:0,prob:0,p10:0,p90:0},
};

const rating = s => s>=150?"Strong Buy":s>=80?"Strong Buy":s>=50?"Buy":s>=15?"Hold":s>=0?"Neutral":"Reduce";
const ratingColor = r => ({
  "Strong Buy":"#22c55e","Buy":"#84cc16","Hold":"#f59e0b","Neutral":"#64748b","Reduce":"#ef4444","Worthless":"#a855f7"
})[r]||"#64748b";

// ── ELEVANCE RO IRA ───────────────────────────────────────────────────
const ELEV_SELLS = [
  {sym:"COP",  action:"SELL ALL", shares:100, price:115.86, proceeds:11559, score:-26.3, reason:"Score −26. XGB −8.6%/21d. Worst held position. No tax hit in IRA."},
  {sym:"TQQQ", action:"SELL ALL", shares:100, price:50.40,  proceeds:5040,  score:-27.9, reason:"Score −28. XGB −14.1%/21d. Worst ETF in universe. Sell and redeploy."},
  {sym:"MMATQ",action:"REMOVE",   shares:2,   price:0,      proceeds:0,     score:-999,  reason:"Worthless — $0 value. Call Schwab to remove. Captures $2,424 loss record."},
];
const ELEV_KEEPS = [
  {sym:"BND",  shares:586, price:74.55,  mv:43686, note:"25.8% bonds — appropriate anchor. Keep as is."},
  {sym:"SPXL", shares:100, price:220.18, mv:22018, note:"Leveraged S&P. Keep — negative score but provides core beta."},
  {sym:"ALB",  shares:100, price:168.96, mv:16896, note:"Score 88. Lithium. Buy signal. Keep."},
  {sym:"SCHD", shares:200, price:31.57,  mv:6314,  note:"Dividend anchor. Keep."},
  {sym:"SOXL", shares:100, price:56.69,  mv:5669,  note:"Score 41. 3x semi. Keep in IRA."},
  {sym:"VZ",   shares:100, price:51.17,  mv:5117,  note:"Income. Keep."},
  {sym:"RTX",  shares:20,  price:209.10, mv:4182,  note:"Score 31. Sharpe 1.80. Defense. Keep."},
  {sym:"CIFR", shares:100, price:16.18,  mv:1618,  note:"Score 114. High risk/reward crypto miner. Keep."},
];
const ELEV_ADDS = [
  {sym:"PLTR", curr:50,  add:50,  target:100, price:153.67, cost:7684,  score:104.6, reason:"Score 105. MC +207%. Sharpe 1.72. Double to 100 shares."},
  {sym:"GE",   curr:15,  add:10,  target:25,  price:339.69, cost:3397,  score:62.3,  reason:"Score 62. Sharpe 1.58. MC +72%. Add 10 more → 25 total."},
  {sym:"KGC",  curr:50,  add:100, target:150, price:33.96,  cost:3396,  score:105.8, reason:"Score 106. Sharpe 2.21. Best risk-adjusted. Triple to 150."},
];
const ELEV_NEWS = [
  {sym:"UUUU", shares:300, price:22.01,  cost:6603,  score:173.4, reason:"#2 in universe. XGB +30.8%/21d. MC +148%. Uranium bull cycle."},
  {sym:"NET",  shares:25,  price:185.60, cost:4640,  score:192.5, reason:"#1 in universe. XGB +46.9%/21d. Cloudflare AI infrastructure play."},
  {sym:"SOFI", shares:200, price:18.78,  cost:3756,  score:130.8, reason:"Score 131. XGB +27.3%/21d. MC +75%. Fintech recovery."},
  {sym:"CEG",  shares:10,  price:323.15, cost:3232,  score:159.6, reason:"Score 160. XGB +36.8%/21d. Nuclear energy. Constellation Energy."},
  {sym:"GDX",  shares:25,  price:106.26, cost:2657,  score:63.7,  reason:"Score 64. Sharpe 1.85. Gold miners ETF. 96% prob positive 1Y."},
  {sym:"GOOGL",shares:8,   price:302.95, cost:2424,  score:65.6,  reason:"Score 66. Sharpe 1.40. 91.6% prob positive. 56.9% MC expected."},
  {sym:"CCJ",  shares:20,  price:120.65, cost:2413,  score:58.6,  reason:"Score 59. Uranium. MC +93%. Companion to UUUU and UEC."},
  {sym:"TSLA", shares:4,   price:406.96, cost:1628,  score:55.5,  reason:"Score 56. MC +75%. XGB +6.4%. Starter position in IRA."},
];
const ELEV_FINAL = [
  {sym:"BND",  sh:586, price:74.55,  mv:43686, isNew:false, isAdd:false},
  {sym:"SPXL", sh:100, price:220.18, mv:22018, isNew:false, isAdd:false},
  {sym:"ALB",  sh:100, price:168.96, mv:16896, isNew:false, isAdd:false},
  {sym:"PLTR", sh:100, price:153.67, mv:15367, isNew:false, isAdd:true},
  {sym:"GE",   sh:25,  price:339.69, mv:8492,  isNew:false, isAdd:true},
  {sym:"UUUU", sh:300, price:22.01,  mv:6603,  isNew:true,  isAdd:false},
  {sym:"SCHD", sh:200, price:31.57,  mv:6314,  isNew:false, isAdd:false},
  {sym:"SOXL", sh:100, price:56.69,  mv:5669,  isNew:false, isAdd:false},
  {sym:"KGC",  sh:150, price:33.96,  mv:5094,  isNew:false, isAdd:true},
  {sym:"VZ",   sh:100, price:51.17,  mv:5117,  isNew:false, isAdd:false},
  {sym:"NET",  sh:25,  price:185.60, mv:4640,  isNew:true,  isAdd:false},
  {sym:"RTX",  sh:20,  price:209.10, mv:4182,  isNew:false, isAdd:false},
  {sym:"SOFI", sh:200, price:18.78,  mv:3756,  isNew:true,  isAdd:false},
  {sym:"CEG",  sh:10,  price:323.15, mv:3232,  isNew:true,  isAdd:false},
  {sym:"GDX",  sh:25,  price:106.26, mv:2657,  isNew:true,  isAdd:false},
  {sym:"GOOGL",sh:8,   price:302.95, mv:2424,  isNew:true,  isAdd:false},
  {sym:"CCJ",  sh:20,  price:120.65, mv:2413,  isNew:true,  isAdd:false},
  {sym:"TSLA", sh:4,   price:406.96, mv:1628,  isNew:true,  isAdd:false},
  {sym:"CIFR", sh:100, price:16.18,  mv:1618,  isNew:false, isAdd:false},
];
const ELEV_CASH = 7264;
const ELEV_TOTAL = 169069;

// ── ROLLOVER IRA ──────────────────────────────────────────────────────
const ROLL_SELLS = [
  {sym:"SPYM", action:"REDUCE", curr:200, target:100, price:80.75, proceeds:8075,  score:1.4,  reason:"Score 1. Duplicate S&P 500 exposure (you have VOO). Reduce 200→100. Keep 100 as broad anchor."},
  {sym:"VNOM", action:"SELL ALL", curr:20, target:0,  price:44.84, proceeds:897,   score:-9.7, reason:"Score −10. XGB −5.4%/21d. Small position, weak signal. Exit fully."},
  {sym:"AVUV", action:"SELL ALL", curr:15, target:0,  price:113.32,proceeds:1700,  score:4.2,  reason:"Score 4. Minimal conviction. Small-cap value ETF duplicates broad exposure. Redeploy."},
  {sym:"KO",   action:"REDUCE", curr:50, target:25,   price:78.32, proceeds:1958,  score:7.4,  reason:"Score 7. Defensive name, low upside. Reduce 50→25. Keep small income position."},
];
const ROLL_KEEPS = [
  {sym:"SPYM", shares:100, price:80.75,  mv:8075,  note:"Keep 100 shares as S&P anchor."},
  {sym:"SPDW", shares:165, price:47.87,  mv:7899,  note:"International developed. Keep."},
  {sym:"PLTR", shares:50,  price:153.67, mv:7684,  note:"Score 105. Core holding. Keep 50."},
  {sym:"VOO",  shares:10,  price:631.14, mv:6311,  note:"Core S&P ETF. Keep."},
  {sym:"NVDA", shares:20,  price:183.02, mv:3660,  note:"Score 39. Keep — long-term AI play."},
  {sym:"IEMG", shares:48,  price:72.63,  mv:3486,  note:"Score 25. EM exposure. Keep."},
  {sym:"MSFT", shares:5,   price:408.14, mv:2041,  note:"Score 25. Keep small position."},
  {sym:"GOOGL",shares:5,   price:302.95, mv:1515,  note:"Score 66. Keep — will add in Elevance."},
  {sym:"SOFI", shares:100, price:18.78,  mv:1878,  note:"Score 131. Keep — strong buy signal."},
  {sym:"KO",   shares:25,  price:78.32,  mv:1958,  note:"Reduced to 25. Income anchor."},
];
const ROLL_ADDS = [
  {sym:"UUUU", curr:150, add:50,  target:200, price:22.01,  cost:1101, score:173.4, reason:"Score 173. #2 universe. Add 50 more → 200 total."},
];
const ROLL_NEWS = [
  {sym:"NET",  shares:12, price:185.60, cost:2227, score:192.5, reason:"#1 in universe. XGB +46.9%/21d. Must-own across both IRAs."},
  {sym:"CEG",  shares:6,  price:323.15, cost:1939, score:159.6, reason:"Score 160. Nuclear energy. XGB +36.8%/21d. High conviction."},
  {sym:"UEC",  shares:120,price:15.12,  cost:1814, score:102.6, reason:"Score 103. Uranium Energy Corp. XGB +18.1%. Uranium explorer."},
  {sym:"GDX",  shares:12, price:106.26, cost:1275, score:63.7,  reason:"Score 64. Sharpe 1.85. Gold miners diversification."},
  {sym:"CCJ",  shares:10, price:120.65, cost:1207, score:58.6,  reason:"Score 59. Cameco. Uranium. MC +93%."},
  {sym:"KGC",  shares:30, price:33.96,  cost:1019, score:105.8, reason:"Score 106. Sharpe 2.21. Gold miner. Add across both accounts."},
];
const ROLL_FINAL = [
  {sym:"SPYM", sh:100, price:80.75,  mv:8075,  isNew:false, isAdd:false},
  {sym:"SPDW", sh:165, price:47.87,  mv:7899,  isNew:false, isAdd:false},
  {sym:"PLTR", sh:50,  price:153.67, mv:7684,  isNew:false, isAdd:false},
  {sym:"VOO",  sh:10,  price:631.14, mv:6311,  isNew:false, isAdd:false},
  {sym:"UUUU", sh:200, price:22.01,  mv:4402,  isNew:false, isAdd:true},
  {sym:"NVDA", sh:20,  price:183.02, mv:3660,  isNew:false, isAdd:false},
  {sym:"IEMG", sh:48,  price:72.63,  mv:3486,  isNew:false, isAdd:false},
  {sym:"NET",  sh:12,  price:185.60, mv:2227,  isNew:true,  isAdd:false},
  {sym:"SOFI", sh:100, price:18.78,  mv:1878,  isNew:false, isAdd:false},
  {sym:"KO",   sh:25,  price:78.32,  mv:1958,  isNew:false, isAdd:false},
  {sym:"CEG",  sh:6,   price:323.15, mv:1939,  isNew:true,  isAdd:false},
  {sym:"UEC",  sh:120, price:15.12,  mv:1814,  isNew:true,  isAdd:false},
  {sym:"MSFT", sh:5,   price:408.14, mv:2041,  isNew:false, isAdd:false},
  {sym:"GOOGL",sh:5,   price:302.95, mv:1515,  isNew:false, isAdd:false},
  {sym:"GDX",  sh:12,  price:106.26, mv:1275,  isNew:true,  isAdd:false},
  {sym:"CCJ",  sh:10,  price:120.65, mv:1207,  isNew:true,  isAdd:false},
  {sym:"KGC",  sh:30,  price:33.96,  mv:1019,  isNew:true,  isAdd:false},
];
const ROLL_CASH = 5538;
const ROLL_TOTAL = 65028;

const fmtK = n => `$${n>=1000?(n/1000).toFixed(1)+"K":Math.round(n).toLocaleString()}`;
const fmt1 = n => `${n>=0?"+":""}${n.toFixed(1)}%`;
const TABS = ["Elevance IRA","Rollover IRA","Options Acct","Summary"];

function ScoreBar({score}) {
  const r = rating(score);
  const c = ratingColor(r);
  const w = Math.min(100, Math.max(0, (score+30)/260*100));
  return (
    <div style={{display:"flex",alignItems:"center",gap:6}}>
      <div style={{width:48,height:4,background:"#0f172a",borderRadius:2,overflow:"hidden"}}>
        <div style={{width:`${w}%`,height:"100%",background:c,borderRadius:2}}/>
      </div>
      <span style={{color:c,fontWeight:700,fontSize:11}}>{score}</span>
    </div>
  );
}

function Badge({text,color}) {
  return <span style={{background:color+"18",color,border:`1px solid ${color}40`,fontSize:9,fontWeight:700,padding:"2px 7px",borderRadius:3,whiteSpace:"nowrap"}}>{text}</span>;
}

function SellCard({item}) {
  return (
    <div style={{background:"#1e293b",borderRadius:8,padding:"13px 16px",borderLeft:"3px solid #ef4444",display:"flex",justifyContent:"space-between",alignItems:"flex-start",gap:12}}>
      <div style={{flex:1}}>
        <div style={{display:"flex",gap:8,alignItems:"center",marginBottom:5}}>
          <Badge text={item.action} color="#ef4444"/>
          <span style={{fontWeight:800,color:"#f1f5f9",fontSize:14}}>{item.sym}</span>
          <span style={{color:"#475569",fontSize:11}}>{item.shares} shares</span>
          <span style={{color:"#475569",fontSize:11}}>@ ${item.price}</span>
        </div>
        <div style={{fontSize:11,color:"#64748b",lineHeight:1.6}}>{item.reason}</div>
      </div>
      <div style={{textAlign:"right",flexShrink:0}}>
        <div style={{fontSize:10,color:"#475569"}}>Proceeds</div>
        <div style={{fontSize:16,fontWeight:800,color:item.proceeds>0?"#22c55e":"#a855f7"}}>
          {item.proceeds>0?`+${fmtK(item.proceeds)}`:"$0"}
        </div>
      </div>
    </div>
  );
}

function BuyRow({item,rank}) {
  const sc = SC[item.sym]||{};
  const r = rating(item.score);
  const c = ratingColor(r);
  return (
    <tr style={{borderTop:"1px solid #0f172a"}}>
      <td style={{padding:"9px 12px",color:"#334155",fontWeight:700,fontSize:12}}>{rank}</td>
      <td style={{padding:"9px 12px"}}>
        <div style={{display:"flex",gap:6,alignItems:"center"}}>
          {item.curr!=null && <Badge text={`+${item.add} (was ${item.curr})`} color="#84cc16"/>}
          {item.curr==null && <Badge text="NEW" color="#22c55e"/>}
          <span style={{fontWeight:800,color:"#f1f5f9",fontSize:13}}>{item.sym}</span>
        </div>
      </td>
      <td style={{padding:"9px 12px",fontWeight:700,color:c,fontSize:13}}>{item.target||item.shares}</td>
      <td style={{padding:"9px 12px",color:"#64748b"}}>${item.price.toFixed(2)}</td>
      <td style={{padding:"9px 12px",fontWeight:700,color:"#fca5a5"}}>{fmtK(item.cost)}</td>
      <td style={{padding:"9px 12px"}}><ScoreBar score={item.score}/></td>
      <td style={{padding:"9px 12px",color:"#86efac",fontWeight:700,fontSize:11}}>{fmt1(sc.xgb||0)}</td>
      <td style={{padding:"9px 12px",color:"#86efac",fontSize:11}}>{fmt1(sc.mc||0)}</td>
      <td style={{padding:"9px 12px",color:"#c4b5fd",fontSize:11}}>{(sc.sharpe||0).toFixed(2)}</td>
      <td style={{padding:"9px 12px",color:"#64748b",fontSize:10,maxWidth:220}}>{item.reason}</td>
    </tr>
  );
}

function FinalTable({holdings, cash, total}) {
  return (
    <div style={{background:"#1e293b",borderRadius:10,overflow:"auto"}}>
      <table style={{width:"100%",borderCollapse:"collapse",fontSize:11}}>
        <thead>
          <tr style={{background:"#0a0f1e"}}>
            {["Symbol","Shares","Est. Value","% Acct","Score","Rating","Status"].map(h=>(
              <th key={h} style={{padding:"8px 12px",textAlign:"left",color:"#334155",fontSize:10,fontWeight:700,whiteSpace:"nowrap"}}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {[...holdings].sort((a,b)=>b.mv-a.mv).map((h,i)=>{
            const sc=SC[h.sym]||{score:0};
            const r=rating(sc.score);
            const c=ratingColor(r);
            const statusColor = h.isNew?"#22c55e":h.isAdd?"#84cc16":"#475569";
            const statusLabel = h.isNew?"🆕 New position":h.isAdd?"➕ Added shares":"✓ Unchanged";
            return (
              <tr key={h.sym} style={{borderTop:"1px solid #0f172a",background:i%2===0?"#1e293b":"#162032"}}>
                <td style={{padding:"8px 12px",fontWeight:800,color:"#f1f5f9",fontSize:13}}>{h.sym}</td>
                <td style={{padding:"8px 12px",fontWeight:700,color:c}}>{h.sh}</td>
                <td style={{padding:"8px 12px",color:"#94a3b8"}}>{fmtK(h.mv)}</td>
                <td style={{padding:"8px 12px"}}>
                  <div style={{display:"flex",alignItems:"center",gap:5}}>
                    <div style={{width:40,height:3,background:"#0f172a",borderRadius:2,overflow:"hidden"}}>
                      <div style={{width:`${Math.min(100,h.mv/total*100*4)}%`,height:"100%",background:c}}/>
                    </div>
                    <span style={{color:"#64748b",fontSize:10}}>{(h.mv/total*100).toFixed(1)}%</span>
                  </div>
                </td>
                <td style={{padding:"8px 12px"}}><ScoreBar score={sc.score}/></td>
                <td style={{padding:"8px 12px"}}><Badge text={r} color={c}/></td>
                <td style={{padding:"8px 12px",color:statusColor,fontSize:10,fontWeight:h.isNew||h.isAdd?700:400}}>{statusLabel}</td>
              </tr>
            );
          })}
          <tr style={{borderTop:"1px solid #334155",background:"#0a0f1e"}}>
            <td style={{padding:"8px 12px",fontWeight:800,color:"#6366f1"}}>CASH</td>
            <td style={{padding:"8px 12px",color:"#6366f1"}}>—</td>
            <td style={{padding:"8px 12px",fontWeight:700,color:"#6366f1"}}>{fmtK(cash)}</td>
            <td style={{padding:"8px 12px",color:"#6366f1",fontSize:10}}>{(cash/total*100).toFixed(1)}%</td>
            <td colSpan={3} style={{padding:"8px 12px",color:"#475569",fontSize:10}}>Reserve — deploy on dips or next signal cycle</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

export default function App() {
  const [tab, setTab] = useState("Elevance IRA");
  const [elev_view, setElev_view] = useState("actions");
  const [roll_view, setRoll_view] = useState("actions");

  const elev_sell_total = ELEV_SELLS.filter(s=>s.proceeds>0).reduce((a,s)=>a+s.proceeds,0);
  const elev_buy_total = [...ELEV_ADDS,...ELEV_NEWS].reduce((a,b)=>a+b.cost,0);
  const elev_deployable = 32470 + elev_sell_total;

  const roll_sell_total = ROLL_SELLS.reduce((a,s)=>a+s.proceeds,0);
  const roll_buy_total = [...ROLL_ADDS,...ROLL_NEWS].reduce((a,b)=>a+b.cost,0);
  const roll_deployable = 3489 + roll_sell_total;

  const TAB_COLOR = {"Elevance IRA":"#f59e0b","Rollover IRA":"#22c55e","Options Acct":"#a855f7","Summary":"#6366f1"};

  return (
    <div style={{fontFamily:"'DM Sans',system-ui,sans-serif",background:"#060d1a",minHeight:"100vh",color:"#e2e8f0",padding:"16px",fontSize:13}}>
    <div style={{maxWidth:1080,margin:"0 auto"}}>

      {/* Header */}
      <div style={{marginBottom:16,paddingBottom:14,borderBottom:"1px solid #1a2744"}}>
        <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start"}}>
          <div>
            <div style={{fontSize:11,letterSpacing:"0.15em",color:"#475569",fontWeight:600,marginBottom:4}}>FULL UNIVERSE SCAN · 113 SYMBOLS · MONTE CARLO + XGBOOST</div>
            <div style={{fontSize:20,fontWeight:800,color:"#f1f5f9",lineHeight:1.2}}>Optimized IRA Portfolio Plan</div>
            <div style={{fontSize:11,color:"#475569",marginTop:3}}>March 4, 2026 · Individual account untouched</div>
          </div>
          <div style={{display:"flex",gap:10}}>
            {[
              {l:"Elevance Cash",v:fmtK(32470+elev_sell_total),c:"#f59e0b"},
              {l:"Rollover Cash",v:fmtK(roll_deployable),c:"#22c55e"},
              {l:"Options Cash",v:"$1,014",c:"#a855f7"},
            ].map(x=>(
              <div key={x.l} style={{background:"#0f1f3d",borderRadius:8,padding:"8px 14px",textAlign:"right",border:`1px solid ${x.c}30`}}>
                <div style={{fontSize:9,color:"#475569",letterSpacing:"0.1em"}}>{x.l.toUpperCase()}</div>
                <div style={{fontSize:16,fontWeight:800,color:x.c}}>{x.v}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div style={{display:"flex",gap:3,marginBottom:16}}>
        {TABS.map(t=>{
          const active = tab===t;
          const c = TAB_COLOR[t];
          return (
            <button key={t} onClick={()=>setTab(t)} style={{
              padding:"8px 20px",borderRadius:6,border:"none",cursor:"pointer",fontSize:12,fontWeight:700,
              background:active?c+"22":"#0f1f3d",
              color:active?c:"#475569",
              borderBottom:active?`2px solid ${c}`:"2px solid transparent",
              transition:"all 0.15s"
            }}>{t}</button>
          );
        })}
      </div>

      {/* ══ ELEVANCE IRA ══ */}
      {tab==="Elevance IRA" && (
        <div>
          {/* sub-tabs */}
          <div style={{display:"flex",gap:6,marginBottom:14}}>
            {[["actions","Action Plan"],["final","Final Holdings"]].map(([k,l])=>(
              <button key={k} onClick={()=>setElev_view(k)} style={{padding:"5px 14px",borderRadius:5,border:`1px solid ${elev_view===k?"#f59e0b":"#1a2744"}`,cursor:"pointer",fontSize:11,fontWeight:600,background:elev_view===k?"#f59e0b22":"transparent",color:elev_view===k?"#f59e0b":"#475569"}}>{l}</button>
            ))}
          </div>

          {elev_view==="actions" && (
            <div>
              {/* Cash math strip */}
              <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:8,marginBottom:16}}>
                {[
                  {l:"Current Cash",v:"$32,470",c:"#f59e0b"},
                  {l:"+ Sell COP + TQQQ",v:`+${fmtK(elev_sell_total)}`,c:"#ef4444"},
                  {l:"= Deployable",v:fmtK(elev_deployable),c:"#22c55e"},
                  {l:"Cash After All Buys",v:fmtK(ELEV_CASH),c:"#6366f1"},
                ].map(x=>(
                  <div key={x.l} style={{background:"#0f1f3d",borderRadius:8,padding:"10px 14px",textAlign:"center",borderTop:`2px solid ${x.c}`}}>
                    <div style={{fontSize:9,color:"#475569",marginBottom:3,letterSpacing:"0.08em"}}>{x.l.toUpperCase()}</div>
                    <div style={{fontSize:17,fontWeight:800,color:x.c}}>{x.v}</div>
                  </div>
                ))}
              </div>

              {/* Step 1: Sell */}
              <div style={{marginBottom:16}}>
                <div style={{display:"flex",alignItems:"center",gap:10,marginBottom:10}}>
                  <div style={{background:"#ef444420",border:"1px solid #ef444440",borderRadius:4,padding:"3px 12px",fontSize:11,fontWeight:700,color:"#ef4444"}}>STEP 1 · SELL / REMOVE</div>
                  <div style={{fontSize:11,color:"#475569"}}>Execute before any buys</div>
                </div>
                <div style={{display:"flex",flexDirection:"column",gap:7}}>
                  {ELEV_SELLS.map((s,i)=><SellCard key={i} item={s}/>)}
                </div>
              </div>

              {/* Step 2: Adds */}
              <div style={{marginBottom:16}}>
                <div style={{display:"flex",alignItems:"center",gap:10,marginBottom:10}}>
                  <div style={{background:"#84cc1620",border:"1px solid #84cc1640",borderRadius:4,padding:"3px 12px",fontSize:11,fontWeight:700,color:"#84cc16"}}>STEP 2 · ADD TO EXISTING</div>
                  <div style={{fontSize:11,color:"#475569"}}>Increase positions you already hold</div>
                </div>
                <div style={{background:"#0f1f3d",borderRadius:10,overflow:"auto"}}>
                  <table style={{width:"100%",borderCollapse:"collapse",fontSize:11}}>
                    <thead>
                      <tr style={{background:"#060d1a"}}>
                        {["#","Symbol","Target Shares","Price","Cost","Score","XGB 21d","MC 1Y","Sharpe","Why"].map(h=>(
                          <th key={h} style={{padding:"8px 12px",textAlign:"left",color:"#334155",fontSize:10,fontWeight:700,whiteSpace:"nowrap"}}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>{ELEV_ADDS.map((b,i)=><BuyRow key={i} item={b} rank={i+1}/>)}</tbody>
                  </table>
                </div>
              </div>

              {/* Step 3: New */}
              <div style={{marginBottom:14}}>
                <div style={{display:"flex",alignItems:"center",gap:10,marginBottom:10}}>
                  <div style={{background:"#22c55e20",border:"1px solid #22c55e40",borderRadius:4,padding:"3px 12px",fontSize:11,fontWeight:700,color:"#22c55e"}}>STEP 3 · NEW POSITIONS</div>
                  <div style={{fontSize:11,color:"#475569"}}>From full universe scan — not currently held</div>
                </div>
                <div style={{background:"#0f1f3d",borderRadius:10,overflow:"auto"}}>
                  <table style={{width:"100%",borderCollapse:"collapse",fontSize:11}}>
                    <thead>
                      <tr style={{background:"#060d1a"}}>
                        {["#","Symbol","Shares","Price","Cost","Score","XGB 21d","MC 1Y","Sharpe","Why"].map(h=>(
                          <th key={h} style={{padding:"8px 12px",textAlign:"left",color:"#334155",fontSize:10,fontWeight:700,whiteSpace:"nowrap"}}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>{ELEV_NEWS.map((b,i)=><BuyRow key={i} item={b} rank={i+1}/>)}</tbody>
                  </table>
                </div>
              </div>

              {/* Summary */}
              <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr",gap:8}}>
                <div style={{background:"#2d070720",border:"1px solid #ef444430",borderRadius:8,padding:"12px 16px"}}>
                  <div style={{fontSize:10,color:"#475569",marginBottom:3}}>TOTAL SELLS</div>
                  <div style={{fontSize:18,fontWeight:800,color:"#22c55e"}}>+{fmtK(elev_sell_total)}</div>
                  <div style={{fontSize:10,color:"#64748b"}}>COP + TQQQ proceeds</div>
                </div>
                <div style={{background:"#05160e20",border:"1px solid #22c55e30",borderRadius:8,padding:"12px 16px"}}>
                  <div style={{fontSize:10,color:"#475569",marginBottom:3}}>TOTAL INVESTED</div>
                  <div style={{fontSize:18,fontWeight:800,color:"#fca5a5"}}>−{fmtK(elev_buy_total)}</div>
                  <div style={{fontSize:10,color:"#64748b"}}>{ELEV_ADDS.length+ELEV_NEWS.length} buy orders</div>
                </div>
                <div style={{background:"#1e1b4b20",border:"1px solid #6366f130",borderRadius:8,padding:"12px 16px"}}>
                  <div style={{fontSize:10,color:"#475569",marginBottom:3}}>CASH RESERVE</div>
                  <div style={{fontSize:18,fontWeight:800,color:"#818cf8"}}>{fmtK(ELEV_CASH)}</div>
                  <div style={{fontSize:10,color:"#64748b"}}>Deploy on dips</div>
                </div>
              </div>
            </div>
          )}

          {elev_view==="final" && (
            <div>
              <div style={{background:"#0f1f3d",borderRadius:8,padding:"10px 16px",marginBottom:12,border:"1px solid #1a2744",display:"flex",gap:20}}>
                <div><span style={{color:"#475569",fontSize:10}}>Account Total: </span><span style={{color:"#f59e0b",fontWeight:700}}>${ELEV_TOTAL.toLocaleString()}</span></div>
                <div><span style={{color:"#475569",fontSize:10}}>Positions: </span><span style={{color:"#f1f5f9",fontWeight:700}}>{ELEV_FINAL.length}</span></div>
                <div><span style={{color:"#22c55e",fontSize:10}}>🆕 New: </span><span style={{color:"#22c55e",fontWeight:700}}>{ELEV_FINAL.filter(h=>h.isNew).length}</span></div>
                <div><span style={{color:"#84cc16",fontSize:10}}>➕ Added: </span><span style={{color:"#84cc16",fontWeight:700}}>{ELEV_FINAL.filter(h=>h.isAdd).length}</span></div>
                <div><span style={{color:"#6366f1",fontSize:10}}>Cash Reserve: </span><span style={{color:"#6366f1",fontWeight:700}}>{fmtK(ELEV_CASH)}</span></div>
              </div>
              <FinalTable holdings={ELEV_FINAL} cash={ELEV_CASH} total={ELEV_TOTAL}/>
            </div>
          )}
        </div>
      )}

      {/* ══ ROLLOVER IRA ══ */}
      {tab==="Rollover IRA" && (
        <div>
          <div style={{display:"flex",gap:6,marginBottom:14}}>
            {[["actions","Action Plan"],["final","Final Holdings"]].map(([k,l])=>(
              <button key={k} onClick={()=>setRoll_view(k)} style={{padding:"5px 14px",borderRadius:5,border:`1px solid ${roll_view===k?"#22c55e":"#1a2744"}`,cursor:"pointer",fontSize:11,fontWeight:600,background:roll_view===k?"#22c55e22":"transparent",color:roll_view===k?"#22c55e":"#475569"}}>{l}</button>
            ))}
          </div>

          {roll_view==="actions" && (
            <div>
              <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:8,marginBottom:16}}>
                {[
                  {l:"Current Cash",v:"$3,489",c:"#22c55e"},
                  {l:"+ Reduce/Sell",v:`+${fmtK(roll_sell_total)}`,c:"#ef4444"},
                  {l:"= Deployable",v:fmtK(roll_deployable),c:"#22c55e"},
                  {l:"Cash After Buys",v:fmtK(ROLL_CASH),c:"#6366f1"},
                ].map(x=>(
                  <div key={x.l} style={{background:"#0f1f3d",borderRadius:8,padding:"10px 14px",textAlign:"center",borderTop:`2px solid ${x.c}`}}>
                    <div style={{fontSize:9,color:"#475569",marginBottom:3,letterSpacing:"0.08em"}}>{x.l.toUpperCase()}</div>
                    <div style={{fontSize:17,fontWeight:800,color:x.c}}>{x.v}</div>
                  </div>
                ))}
              </div>

              <div style={{marginBottom:16}}>
                <div style={{display:"flex",alignItems:"center",gap:10,marginBottom:10}}>
                  <div style={{background:"#ef444420",border:"1px solid #ef444440",borderRadius:4,padding:"3px 12px",fontSize:11,fontWeight:700,color:"#ef4444"}}>STEP 1 · REDUCE / SELL</div>
                </div>
                <div style={{display:"flex",flexDirection:"column",gap:7}}>
                  {ROLL_SELLS.map((s,i)=><SellCard key={i} item={s}/>)}
                </div>
              </div>

              <div style={{marginBottom:16}}>
                <div style={{display:"flex",alignItems:"center",gap:10,marginBottom:10}}>
                  <div style={{background:"#84cc1620",border:"1px solid #84cc1640",borderRadius:4,padding:"3px 12px",fontSize:11,fontWeight:700,color:"#84cc16"}}>STEP 2 · ADD TO EXISTING</div>
                </div>
                <div style={{background:"#0f1f3d",borderRadius:10,overflow:"auto"}}>
                  <table style={{width:"100%",borderCollapse:"collapse",fontSize:11}}>
                    <thead>
                      <tr style={{background:"#060d1a"}}>
                        {["#","Symbol","Target Shares","Price","Cost","Score","XGB 21d","MC 1Y","Sharpe","Why"].map(h=>(
                          <th key={h} style={{padding:"8px 12px",textAlign:"left",color:"#334155",fontSize:10,fontWeight:700,whiteSpace:"nowrap"}}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>{ROLL_ADDS.map((b,i)=><BuyRow key={i} item={b} rank={i+1}/>)}</tbody>
                  </table>
                </div>
              </div>

              <div style={{marginBottom:14}}>
                <div style={{display:"flex",alignItems:"center",gap:10,marginBottom:10}}>
                  <div style={{background:"#22c55e20",border:"1px solid #22c55e40",borderRadius:4,padding:"3px 12px",fontSize:11,fontWeight:700,color:"#22c55e"}}>STEP 3 · NEW POSITIONS</div>
                  <div style={{fontSize:11,color:"#475569"}}>Best opportunities from full universe scan</div>
                </div>
                <div style={{background:"#0f1f3d",borderRadius:10,overflow:"auto"}}>
                  <table style={{width:"100%",borderCollapse:"collapse",fontSize:11}}>
                    <thead>
                      <tr style={{background:"#060d1a"}}>
                        {["#","Symbol","Shares","Price","Cost","Score","XGB 21d","MC 1Y","Sharpe","Why"].map(h=>(
                          <th key={h} style={{padding:"8px 12px",textAlign:"left",color:"#334155",fontSize:10,fontWeight:700,whiteSpace:"nowrap"}}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>{ROLL_NEWS.map((b,i)=><BuyRow key={i} item={b} rank={i+1}/>)}</tbody>
                  </table>
                </div>
              </div>

              <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr",gap:8}}>
                <div style={{background:"#05160e20",border:"1px solid #22c55e30",borderRadius:8,padding:"12px 16px"}}>
                  <div style={{fontSize:10,color:"#475569",marginBottom:3}}>TOTAL SELLS/REDUCES</div>
                  <div style={{fontSize:18,fontWeight:800,color:"#22c55e"}}>+{fmtK(roll_sell_total)}</div>
                </div>
                <div style={{background:"#2d070720",border:"1px solid #ef444430",borderRadius:8,padding:"12px 16px"}}>
                  <div style={{fontSize:10,color:"#475569",marginBottom:3}}>TOTAL INVESTED</div>
                  <div style={{fontSize:18,fontWeight:800,color:"#fca5a5"}}>−{fmtK(roll_buy_total)}</div>
                </div>
                <div style={{background:"#1e1b4b20",border:"1px solid #6366f130",borderRadius:8,padding:"12px 16px"}}>
                  <div style={{fontSize:10,color:"#475569",marginBottom:3}}>CASH RESERVE</div>
                  <div style={{fontSize:18,fontWeight:800,color:"#818cf8"}}>{fmtK(ROLL_CASH)}</div>
                </div>
              </div>
            </div>
          )}

          {roll_view==="final" && (
            <div>
              <div style={{background:"#0f1f3d",borderRadius:8,padding:"10px 16px",marginBottom:12,border:"1px solid #1a2744",display:"flex",gap:20}}>
                <div><span style={{color:"#475569",fontSize:10}}>Account Total: </span><span style={{color:"#22c55e",fontWeight:700}}>${ROLL_TOTAL.toLocaleString()}</span></div>
                <div><span style={{color:"#475569",fontSize:10}}>Positions: </span><span style={{color:"#f1f5f9",fontWeight:700}}>{ROLL_FINAL.length}</span></div>
                <div><span style={{color:"#22c55e",fontSize:10}}>🆕 New: </span><span style={{color:"#22c55e",fontWeight:700}}>{ROLL_FINAL.filter(h=>h.isNew).length}</span></div>
                <div><span style={{color:"#84cc16",fontSize:10}}>➕ Added: </span><span style={{color:"#84cc16",fontWeight:700}}>{ROLL_FINAL.filter(h=>h.isAdd).length}</span></div>
                <div><span style={{color:"#6366f1",fontSize:10}}>Cash Reserve: </span><span style={{color:"#6366f1",fontWeight:700}}>{fmtK(ROLL_CASH)}</span></div>
              </div>
              <FinalTable holdings={ROLL_FINAL} cash={ROLL_CASH} total={ROLL_TOTAL}/>
            </div>
          )}
        </div>
      )}

      {/* ══ OPTIONS ACCOUNT ══ */}
      {tab==="Options Acct" && (
        <div>
          <div style={{background:"#0f1f3d",borderRadius:10,padding:"16px 20px",marginBottom:14,border:"1px solid #a855f730"}}>
            <div style={{fontSize:13,fontWeight:700,color:"#a855f7",marginBottom:4}}>Options Account ...623 — $1,014 Cash</div>
            <div style={{fontSize:11,color:"#475569"}}>Small account. Three strategies below — choose one based on your risk tolerance. Do NOT split across multiple; pick one and execute fully.</div>
          </div>

          {[
            {
              rank:"Option A",risk:"Highest Risk / Highest Reward",c:"#ef4444",
              trade:"Buy 1× NET $190 Call, exp April 17 2026",
              cost:"~$800–1,000",
              rationale:"NET is the #1 ranked stock across the full 113-symbol universe — score 193, XGB +46.9%/21d. A single call option at ~$9 premium = $900 gives you leveraged exposure if NET moves through $190 by expiry. Max loss = premium paid.",
              pros:["Leverages your #1 ranked name","Max 4–6× return if NET rallies 10%+","Defined risk — lose at most $900"],
              cons:["Binary outcome — worthless if expires OTM","Time decay works against you","Need NET to move quickly"]
            },
            {
              rank:"Option B",risk:"Moderate Risk",c:"#f59e0b",
              trade:"Buy 4× SOFI $20 Call, exp April 17 2026",
              cost:"~$150–200 each = ~$700–800",
              rationale:"SOFI scores 131 with XGB +27.3%/21d. At ~$19, it's near the $20 strike making these near-the-money. 4 contracts = 400 shares of exposure for ~$750. If SOFI moves to $22+, these could be worth 3–5× the premium.",
              pros:["More contracts = more upside leverage","Score 131 — strong buy signal","Lower per-contract cost"],
              cons:["SOFI is volatile, can whipsaw","4 contracts = more commissions","Still binary at expiry"]
            },
            {
              rank:"Option C",risk:"Lowest Risk (Recommended)",c:"#22c55e",
              trade:"Buy 45 shares of UUUU @ ~$22",
              cost:"~$990",
              rationale:"If options feel uncertain, just buy 45 shares of the #2 ranked stock outright. No expiry risk, no time decay, no binary outcome. UUUU scores 173 with XGB +30.8%/21d and MC expected +148% 1-year. You already hold UUUU in both IRAs — adding here keeps the conviction consistent.",
              pros:["No expiry — position doesn't decay","Score 173 — strong buy","Consistent with IRA positions"],
              cons:["Less leverage than options","$990 is small — modest absolute gain","No income from premiums"]
            }
          ].map((opt,i)=>(
            <div key={i} style={{background:"#0f1f3d",borderRadius:10,padding:"18px 20px",marginBottom:12,border:`1px solid ${opt.c}30`,borderLeft:`4px solid ${opt.c}`}}>
              <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",marginBottom:10}}>
                <div>
                  <div style={{display:"flex",gap:8,alignItems:"center",marginBottom:4}}>
                    <Badge text={opt.rank} color={opt.c}/>
                    <Badge text={opt.risk} color={opt.c}/>
                  </div>
                  <div style={{fontSize:15,fontWeight:800,color:"#f1f5f9"}}>{opt.trade}</div>
                </div>
                <div style={{textAlign:"right"}}>
                  <div style={{fontSize:10,color:"#475569"}}>Estimated Cost</div>
                  <div style={{fontSize:16,fontWeight:800,color:opt.c}}>{opt.cost}</div>
                </div>
              </div>
              <div style={{fontSize:12,color:"#64748b",lineHeight:1.7,marginBottom:10}}>{opt.rationale}</div>
              <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:10}}>
                <div style={{background:"#05160e30",borderRadius:6,padding:"10px 12px"}}>
                  <div style={{fontSize:10,color:"#22c55e",fontWeight:700,marginBottom:4}}>✓ PROS</div>
                  {opt.pros.map((p,j)=><div key={j} style={{fontSize:11,color:"#475569",marginBottom:2}}>• {p}</div>)}
                </div>
                <div style={{background:"#2d070730",borderRadius:6,padding:"10px 12px"}}>
                  <div style={{fontSize:10,color:"#ef4444",fontWeight:700,marginBottom:4}}>✗ CONS</div>
                  {opt.cons.map((p,j)=><div key={j} style={{fontSize:11,color:"#475569",marginBottom:2}}>• {p}</div>)}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ══ SUMMARY ══ */}
      {tab==="Summary" && (
        <div>
          {/* Themes */}
          <div style={{background:"#0f1f3d",borderRadius:10,padding:"16px 20px",marginBottom:14,border:"1px solid #1a2744"}}>
            <div style={{fontSize:12,fontWeight:700,color:"#f1f5f9",marginBottom:10}}>📊 KEY THEMES FROM FULL UNIVERSE SCAN</div>
            <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:10}}>
              {[
                {icon:"⚛️",c:"#22c55e",t:"Uranium / Nuclear is the #1 theme",b:"UUUU (#2 universe), UEC (#10), CCJ, CEG all appear in top tier. Nuclear renaissance + AI power demand driving structural bull. Both IRAs now hold multiple uranium plays."},
                {icon:"🌐",c:"#22c55e",t:"NET (Cloudflare) is the top-ranked stock",b:"Score 193. XGB +46.9%/21d — highest short-term momentum in the entire 113-stock universe. AI infrastructure + zero-trust networking. Added to BOTH IRAs."},
                {icon:"🥇",c:"#f59e0b",t:"Gold miners remain best risk-adjusted",b:"KGC (Sharpe 2.21), AEM (Sharpe 2.18), GDX (Sharpe 1.85), NEM (Sharpe 1.72), WPM (Sharpe 1.86) — 5 gold names in the top 30 by risk-adjusted return. 98%+ prob positive."},
                {icon:"🚫",c:"#ef4444",t:"Energy & pharma are the weakest sectors",b:"COP, CVX, XOM, XLE all score below −14. NVO worst in universe (−59). UNH (−27), VRTX (−37), ENPH (−78) also red-flagged. Avoid or exit all energy."},
              ].map((x,i)=>(
                <div key={i} style={{background:"#060d1a",borderRadius:8,padding:"12px 14px",borderLeft:`3px solid ${x.c}`}}>
                  <div style={{fontSize:12,fontWeight:700,color:x.c,marginBottom:4}}>{x.icon} {x.t}</div>
                  <div style={{fontSize:11,color:"#475569",lineHeight:1.6}}>{x.b}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Full action checklist */}
          <div style={{background:"#0f1f3d",borderRadius:10,padding:"16px 20px",marginBottom:14}}>
            <div style={{fontSize:12,fontWeight:700,color:"#f1f5f9",marginBottom:12}}>✅ COMPLETE EXECUTION CHECKLIST</div>
            <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:6}}>
              {[
                {acct:"Elevance IRA",step:"1",action:"SELL COP — all 100 shares",c:"#ef4444"},
                {acct:"Elevance IRA",step:"1",action:"SELL TQQQ — all 100 shares",c:"#ef4444"},
                {acct:"Elevance IRA",step:"1",action:"REMOVE MMATQ — call Schwab",c:"#a855f7"},
                {acct:"Elevance IRA",step:"2",action:"ADD PLTR +50 sh → 100 total",c:"#84cc16"},
                {acct:"Elevance IRA",step:"2",action:"ADD GE +10 sh → 25 total",c:"#84cc16"},
                {acct:"Elevance IRA",step:"2",action:"ADD KGC +100 sh → 150 total",c:"#84cc16"},
                {acct:"Elevance IRA",step:"3",action:"BUY UUUU — 300 shares (new)",c:"#22c55e"},
                {acct:"Elevance IRA",step:"3",action:"BUY NET — 25 shares (new)",c:"#22c55e"},
                {acct:"Elevance IRA",step:"3",action:"BUY SOFI — 200 shares (new)",c:"#22c55e"},
                {acct:"Elevance IRA",step:"3",action:"BUY CEG — 10 shares (new)",c:"#22c55e"},
                {acct:"Elevance IRA",step:"3",action:"BUY GDX — 25 shares (new)",c:"#22c55e"},
                {acct:"Elevance IRA",step:"3",action:"BUY GOOGL — 8 shares (new)",c:"#22c55e"},
                {acct:"Elevance IRA",step:"3",action:"BUY CCJ — 20 shares (new)",c:"#22c55e"},
                {acct:"Elevance IRA",step:"3",action:"BUY TSLA — 4 shares (new)",c:"#22c55e"},
                {acct:"Rollover IRA",step:"1",action:"REDUCE SPYM 200 → 100 shares",c:"#f97316"},
                {acct:"Rollover IRA",step:"1",action:"SELL VNOM — all 20 shares",c:"#ef4444"},
                {acct:"Rollover IRA",step:"1",action:"SELL AVUV — all 15 shares",c:"#ef4444"},
                {acct:"Rollover IRA",step:"1",action:"REDUCE KO 50 → 25 shares",c:"#f97316"},
                {acct:"Rollover IRA",step:"2",action:"ADD UUUU +50 sh → 200 total",c:"#84cc16"},
                {acct:"Rollover IRA",step:"3",action:"BUY NET — 12 shares (new)",c:"#22c55e"},
                {acct:"Rollover IRA",step:"3",action:"BUY CEG — 6 shares (new)",c:"#22c55e"},
                {acct:"Rollover IRA",step:"3",action:"BUY UEC — 120 shares (new)",c:"#22c55e"},
                {acct:"Rollover IRA",step:"3",action:"BUY GDX — 12 shares (new)",c:"#22c55e"},
                {acct:"Rollover IRA",step:"3",action:"BUY CCJ — 10 shares (new)",c:"#22c55e"},
                {acct:"Rollover IRA",step:"3",action:"BUY KGC — 30 shares (new)",c:"#22c55e"},
                {acct:"Options Acct",step:"—",action:"Deploy $1,014 per chosen strategy",c:"#a855f7"},
              ].map((item,i)=>{
                const acctC = {"Elevance IRA":"#f59e0b","Rollover IRA":"#22c55e","Options Acct":"#a855f7"}[item.acct];
                return (
                  <div key={i} style={{background:"#060d1a",borderRadius:5,padding:"7px 12px",display:"flex",alignItems:"center",gap:8}}>
                    <div style={{width:6,height:6,borderRadius:"50%",background:item.c,flexShrink:0}}/>
                    <span style={{color:acctC,fontSize:9,fontWeight:700,minWidth:80}}>{item.acct}</span>
                    <span style={{color:"#475569",fontSize:10,fontWeight:700,minWidth:14}}>S{item.step}</span>
                    <span style={{color:"#94a3b8",fontSize:11}}>{item.action}</span>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Disclaimer */}
          <div style={{background:"#060d1a",border:"1px solid #1a2744",borderRadius:8,padding:"10px 14px"}}>
            <div style={{fontSize:10,color:"#334155",lineHeight:1.6}}>⚠️ Not financial advice. All scores derived from 2-year historical price and technical data only — no fundamental analysis, earnings forecasts, or macro inputs. Individual account left untouched per your instructions. Prices at execution will differ from estimates; use share counts as targets. Consult a licensed financial advisor before trading.</div>
          </div>
        </div>
      )}

    </div>
    </div>
  );
}
