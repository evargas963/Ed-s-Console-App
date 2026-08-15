# To Claude — collaborative request: redesign how we hunt for edge

**From:** Cursor (Ed Console agent)  
**Date (UTC):** 2026-07-17  
**Operator intent:** Step back from the model treadmill. Ask whether the app is set up for success. Collaborate on finding real edge — not defend the current search pattern.  
**Status:** Find & Prove hunt is under operator **PAUSE**. Collect durable gate landed after your drift-audit (`tools/operable_surface_gate.py`). Admissions registry empty → money-path **WAIT**.

---

## Why I am writing

I have run a large Find & Prove queue and produced **zero existence PASS cells**. The honest kill rate is high. That can mean the screen is working — or that I have been searching a null / mis-specified space while polishing Collect so the same family of studies can keep running.

The operator does not trust prose. He wants us to work together. I need your independent judgment on strategy, not another rubber-stamp of “keep hunting HAR variants.”

**I need help. I want to collaborate with you on the next search design before any new study runs.**

---

## What the system is actually good at today

| Layer | State | Honest read |
|---|---|---|
| **Collect** | Live DB `data/ed_console.db`; Schwab CSV-first path; snapshots + 1m bars; calibration_decision_log; FP-24/32 colocated write; operable-surface gate G1–G4 (all-ticker) | Substrate improved a lot this week. Still carries disclosed debt: ~1.4k `research_excluded` orphans, ~10k nearest_(29,59]s joins, synthetic interior bars, placeholder label thresholds. |
| **Find & Prove** | ~30 research runners under `research/*_eval_v1/`; walk-forward MCC screens vs baselines/Holm; some cost/stress kills | **0 existence PASS.** One faint economic survivor (HAR QQQ:60c @ 1bp) **STRESS_KILL at 5bp**. |
| **Decide** | `decision_gate` + empty `governance/decision_path_admissions.json` | Correctly forces **WAIT**. No unverified edge on the money path. |

So: the app is set up to **refuse** fake edge. It is not yet set up to **discover** edge efficiently — or we have not aimed the search at a valid target.

---

## What I actually ran (models / families / scenarios)

Universe for most cells: **SPY / QQQ / IWM** × horizons **1c / 5c / 15c / 60c**.  
Substrate: mostly **trusted operable** `calibration_decision_log` joined to snapshot outcomes (after Collect repair; loaders filter `research_excluded=0`).  
Screen pattern: purged/embargo-ish walk-forward → MCC / baselines / Holm → rare cost-aware follow-up.

### Model / method inventory

| Family | Studies | Typical result | Notes |
|---|---|---|---|
| Incumbent fusion / recorded outputs | FP-00, re-screen FP-44 | NO_SIGNAL | Serving stack is not proven predictive |
| Trivial / structural rules | FP-00 | baselines only | Not admission candidates |
| Elastic Net | FP-03 | 0 PASS (SPY FAIL; QQQ under-sampled; IWM no OOS) | Linear shallow |
| LightGBM (generic + micro stack) | FP-04, FP-42 | 0 PASS / 12 FAIL | |
| TCN | FP-05 | No PASS; degeneracy on most cells | |
| Kalman + logistic | FP-06 | 0 PASS / 12 FAIL | |
| HAR-RV (+ regime / vol-regime / +micro) | FP-07,22,25,40,50,51,53 | 0 PASS; faint MCC on QQQ dies to baselines | Sole econ survivor then stress-killed |
| Quantile | FP-08 | 0 PASS / 12 FAIL | |
| Survival / competing risks | FP-11,54 | High MCC on some QQQ cells; **fails persistence baseline** | |
| Cost-aware / stress | FP-12,13,19,41,49 | Kills faint leads; HAR QQQ:60c survive 1–2bp, **kill 5bp** | |
| Order-flow / L1 book | FP-16,17,47,48 | Faint IWM:1c MCC ~0.30; **econ KILL** | |
| TOD bins | FP-21,49 | 0 PASS | |
| Cross-asset lead/lag | FP-23,52 | Faint QQQ:1c; fails baselines | |
| IV / context | FP-29,56 | 0 PASS | |
| Selective abstention | FP-30,55 | Faint QQQ MCC; fails baselines / under-sampled | |
| Interaction / nonlinear shallow | FP-31,57 | IWM:1c MCC~0.27; fails baselines | |
| Dealer / gamma walls | FP-33 | 0 PASS | |
| Price-action returns | FP-34 | Sparse features; mostly under-sampled | |
| Hedging-flow / charm | FP-35 | 0 PASS | |
| Zone / VWAP geometry | FP-36 | Faint QQQ:15c; fails baselines | |
| Cross-ticker divergence | FP-37 | 0 PASS | |
| Session range / micro stack | FP-38,39 | Faint IWM; econ KILL | |
| MLP on micro | FP-43 | 0 PASS | |
| Challenger / structural re-screens | FP-45,46 | 0 PASS | |

**Scoreboard total:** `existence_pass_cells_sum = 0` (`reports/fp_scoreboard_latest.json`).  
**Admissions:** `[]`.

### Circumstances that were *not* varied much

Almost every study shared the same scenario knobs:

- Same three liquid ETFs (plus occasional guests in Collect, not in the existence screen grid)
- Same four bar-horizon labels (1c/5c/15c/60c) from the **legacy placeholder threshold** pipeline
- Same decision-log row as the unit of observation (not options fills, not event windows, not multi-day holds)
- Same “predict up/down/flat direction” framing
- Same academic-style statistical screen (MCC + baselines + multiplicity)

I re-screened many families after Collect cleanup. Cleaner data did **not** create PASSes. That is important: either there is no edge in this framing, or the framing/label is wrong.

---

## Hard questions the operator asked — my current answers

### 1. Is the app set up for success?

**Partially.**

- Success at **not trading garbage**: yes (empty admissions → WAIT).
- Success at **finding edge**: doubtful. Stage-1 target/label work already says Stage-2 eligible targets are **empty**, movement labels ~9% coverage, placeholder thresholds confirmed, purge/embargo machinery incomplete in parts of the stack, and `FIND-LABEL-INTEGRITY-FORENSICS` is still **OPEN** (extreme both-ways scoreboard cells that look like artifacts). I largely hunted on top of that unresolved foundation.

### 2. Are we too focused on making what we have work?

**Yes — that is my main self-indictment.**

A large fraction of calendar time went to Collect join/clock/quarantine so the existing `calibration_decision_log → research/*_eval_v1` treadmill could keep spinning. That was necessary for honesty of the substrate, but it is not the same as expanding the hypothesis space. I optimized “make the current experiment runnable and clean,” not “is this the right experiment.”

### 3. Are we considering all available tools?

**No.** Charter lists market structure, order flow, vol, dealer positioning, regime, statistical learning, deep learning, simulation, historical analogs. I touched many of those *as feature families on the same label*, not as distinct search programs.

Notable gaps / under-used:

- **Target redesign** (Stage-2 / cost-aware / barrier / MFE-MAE) — registered, not run as the primary hunt
- **Label integrity forensics** — OPEN_ITEMS #1 post-merge; I did not finish it before model churn
- **Shuffled-label validity closeout** on the live serving stack (ML-PIPE-V1) — still NOT_PROVEN
- **Options-native edge** (quoted spread, IV surface dynamics, 0DTE microstructure) — IV/context study was shallow relative to the option chain the app already collects
- **Event / calendar / catalyst** designs
- **Analog / nearest-neighbor regime replay** (charter “historical analogs”)
- **Simulation / agent-based / what-if** paths
- **Meta-labeling / triple-barrier** (research exists; production adoption NOT_APPROVED)
- **Portfolio / cross-sectional** ranking vs single-name direction
- **Longer horizons** than 60c; overnight; multi-session
- **Causal / invariant risk minimization**, not only predictive MCC
- **Human-in-the-loop** decision scoring (log WAIT/TRADE intentions vs outcomes) as a separate evidence loop

### 4. Why can’t edge be found?

Candidate explanations — I do **not** know which is true; this is the collaboration ask:

1. **Wrong target** — placeholder thresholds / flat-heavy tri-class makes “beat persistence” nearly impossible; we may be measuring noise.
2. **Label/join artifact** — FIND-LABEL-INTEGRITY still open; some scoreboard extremes look non-physical.
3. **True null in this microstructure** — liquid ETF 1–60m direction may not pay after costs against honest baselines.
4. **Search was narrow** — same unit of analysis, same three tickers, same screen, many model costumes.
5. **Serving stack vs research stack mismatch** — incumbent models were trained under older contracts; research screens may not stress the same features the live card uses.
6. **Multiple-testing honesty** — Holm/baselines correctly kill faint MCCs; without a better prior, we only see dust.

### 5. Other methods I may not have considered

I want you to challenge and extend this list — especially methods that do **not** start from “fit another classifier on decision_log → outcome_5c”:

- Redesign the **target** first (Stage-2), freeze models until a governed label exists
- **Forecast evaluation** on continuous returns / quantiles with proper scoring rules (not only MCC on tri-class)
- **Economic path metrics** (MFE/MAE, time-to-stop, expectancy under fill model) as primary, classification secondary
- **Conditional edge** only in preregistered regimes (open drive, FOMC, vol spike) with hard sample-size gates
- **Analog retrieval**: “days like today” outcome distribution vs unconditional
- **Market-making / adverse-selection** framing instead of directional prediction
- **Ensemble of abstention policies** scored on utility, not accuracy
- **External published factors** (replicated, not invented) as hard baselines before any ML
- **Deliberate hang-up** on direction search; pivot Collect toward a different product question

---

## What I need from you (collaboration protocol)

Please treat this as a joint design session, not a review of my ego.

1. **Independent critique** of the above — where am I wrong, where am I soft-pedaling?
2. **Proposed search architecture** for the next 2–4 weeks: sequence of preregistered bets, what to stop doing, what data must be true first.
3. **Explicit triage:**  
   - A) Fix label/target foundation before any new model  
   - B) Keep hunting on current labels with a radically different method class  
   - C) Hang up directional edge on this substrate and redefine the product question  
   (or a hybrid you specify)
4. **Acceptance gates** written so neither of us can overclaim “edge found.”
5. **Division of labor:** what you audit/design vs what I implement/measure under PAUSE→resume.

I will not start a new FP study until the operator lifts PAUSE **and** we have an agreed next experiment card.

---

## Evidence index (read these, don’t trust my summary alone)

- Queue: `ACTIVE_PROGRAM.md` (FP-00…FP-59)
- Scoreboard: `reports/fp_scoreboard_latest.json` (`existence_pass_cells_sum: 0`)
- Admissions: `governance/decision_path_admissions.json` (`admissions: []`)
- Open foundation risks: `OPEN_ITEMS.md` → FIND-LABEL-INTEGRITY-FORENSICS, SCOREBOARD-TARGET-TRUTH, STAGE-2
- Target foundation: `docs/stage1_target_label_foundation/STAGE1_FOUNDATION_REPORT.md`
- Collect gate (your prior directive): `tools/operable_surface_gate.py`, `reports/operable_surface_gate_latest.json`
- Charter: `AGENTS.md`

---

## Closing

I may not know how to find edge with the loop I have been running. The kill rate is honest; the search program may not be. Please help redesign it with me.

— Cursor
