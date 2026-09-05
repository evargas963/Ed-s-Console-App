# ACTIVE_PROGRAM.md — current operator-directed work, nothing else

**This file owns ONE responsibility: the record of current operator-directed work** — what is
in flight, queued or blocked, with its evidence pointers. Statuses here are a record, not standing
authority: the operator directs each session in chat and no agent self-assigns a `NEXT`/`QUEUED`
row. Rows leave this file when they finish (git history keeps them); an item that turns out to be
a defect gets a `governance/root_cause_log.md` row with a due date; what "done" means for any of
it is `OPEN_ITEMS.md` (acceptance specification); the law is `AGENTS.md`. Operator halt words are
in `AGENTS.md`. Rewritten 2026-09-05 (RC-520): DONE rows, the runtime-lock table and the known-risk
list were removed — the locks are their own record, the risks live with their owners.

Status values: `NEXT` | `IN PROGRESS` | `QUEUED` | `BLOCKED`.

## Operator NOW (top of the backlog — the operator directs when it runs)

| ID | Status | Work item |
|---|---|---|
| LP-01 | NEXT | **Institutional session liquidity / value levels (not SMC “pools”).** (1) Fix volume-profile construction: distribute bar volume across `[L,H]` (or tick VP), not typical-price dump — POC/VAH/VAL must match AMT/VP practice. (2) Fix overnight window to prior **trading** session close→open (Monday must include Friday after 16:00). (3) Relabel / demote `sell_side_liquidity`/`buy_side_liquidity` until equal-extreme stop-cluster levels exist and are tested — do not claim “liquidity pools.” (4) Surface **raw** levels (POC/VAH/VAL, PDH/PDL, ORB, VWAP ±σ) on Chart and/or Console v2 — Liquidity Map today lives in hidden `#main` (`display:none`). (5) Find & Prove gate: touch→5/15/30m forward returns vs time-of-day base rate, no lookahead; until PASS, display as structure context only (not Decide). Authority: `liquidity_value_engine.py` / `liquidity_models.py` / `/api/liquidity-snapshot`. Ledger: `OPEN_ITEMS.md` **LP-01**. |

## Open work moved from the former OPEN_ITEMS.md queues (2026-09-05)

- [ ] **RECON-02 Disk-cleanup purge** — ~53.3 GB quarantined (moved, not deleted) 2026-07-15/16. Purge only after one clean trading session AND the operator gives the purge word. Separately: `_backup_pre_exec_identity_v1_20260713.db` (19.29 GB) holds until ~5 clean trading days after the slimming merge. **UPDATE 2026-07-26: the slimming merge landed — RC-6 blob-dedup slimmed the live DB 29.74 → 22.06 GB (verified on a copy, swapped live; original preserved as `data/ed_console.pre_rc6_20260726.db`). The 5-clean-day clock for the pre_exec backup now RUNS from 2026-07-26.** Full purge candidate set + gates: `reports/fp_db_deletion_gating_latest.json`.
- [ ] **OPS-OPERABLE-SURFACE-JOB** — the daily terrain scorecard host task is REGISTERED (`EdTerrainScorecard`, weekdays 16:45 ET — job record: `governance/host_scheduled_jobs.md`, the sole host-job inventory). Still not registered on the host — the recurring Collect job: `python -m tools.run_operable_surface_ops --db data/ed_console.db` (production backfill tol=29 + gate). Optional end-of-day: `--refresh-outcomes --repair59 --quarantine`. Durable gate: `python -m tools.operable_surface_gate --db data/ed_console.db --write-report`. Do not create a silent Windows task without an operator-visible inventory row (see FIND-SCHEDULED-JOBS-VISIBILITY).
- [ ] **PHASE-5 Restructure** — deliberate directory reorganization for a legible repo. After Phase 4; no functional changes mixed in.
- [ ] **FIND-LABEL-INTEGRITY-FORENSICS** — 2026-07-16 scoreboard shows cells too extreme in both directions to be noise: `$SPX` 60c **0.0% on n=108** (0/61 directional), `UNH` 0–6.6% across all horizons (n=244), `MSFT` 60c directional 99.0% (n=101), QQQ 60c 72.3%. Extreme-both-ways is the signature of a labeling/join artifact (inverted labels, timestamp misalignment, broken outcome join), not model quality; every horizon carries `TIMESTAMP_IDENTITY_NOT_PROVEN`. Resolve whether these cells are artifacts before trusting any accuracy number. First Find & Prove work item post-merge; feeds the target-truth lane below.
- [ ] **STAGE-2 Target/label foundation** — continue `docs/stage1_target_label_foundation/` Stage 2: retire the confirmed placeholder thresholds and design the governed target so scoreboard accuracy becomes decision-valid. Preregistered protocol; no outcome mining.
- [ ] **ML-PIPE-V1 predictive-validity closeout** — remaining from the correctness program: operator-host shuffled-label runs on real capture data per model-family×horizon, then a clean governed retrain, then per-ticker/per-horizon validity classification. Until then the standing NOT_PROVEN verdict holds.
- [ ] **SIG-01 scoreboard/actionability accrual** — sessions 2–5 of segmented multi-day evidence toward signal-outcome validation; logger ~32 tickers, snapshot rows landing all session.
- [ ] **OPS-PLAYWRIGHT-E2E-RERUN** — operator host: `npm run test:e2e` (marker stale since 2026-05-25; `tests/test_playwright_must_run.py` fails honestly until a REAL run lands). Blocks the first fully-green pytest since May.
- [ ] **OPS-FULL-SUITE-STAMP** — operator host: fresh `python -m pytest -q tests/` after the E2E run. Prior full run 2026-07-20: 4237 passed / 4 failed; the 3 code failures are fixed but the 4240/4241 tally is UNVERIFIED until a fresh complete run (Cursor veracity audit: "not re-proven").

## Find & Prove queue (open rows only; FP-00..FP-67 history is in git)

Verdicts recorded in the retired rows FP-03..FP-25 are ERA-CONTAMINATED (`OPEN_ITEMS.md` top-level
verdicts, operator 2026-08-01) — citable in neither direction until a clean-protocol re-run.

| ID | Status | Work item |
|---|---|---|
| FP-61 | BLOCKED | **Week-1 G-LABEL card (Claude triage A).** Placeholder thresholds confirmed; freeze models. Card: `reports/fp_week1_label_card_v1.md`. Reply: `reports/fp_claude_edge_reply.md`. Execute only on operator `GO WEEK1 LABEL`. |
| FP-64 | QUEUED | **GEX harvest redesign (FP-63 satisfied 2026-07-22; capture n accruing — 20 days × ~40 tickers wide chains + intraday accrual since 2026-07-31).** Tail-selective + defensive: fade strong long-gamma, stand aside / momentum on strong short-gamma, abstain mid; size by GEX level; re-run §8.6 with abstention/avoided-loss accounting. Not edge until economic gate + Claude verify. |

## Terrain upgrade program — TU (2026-07-21 research synthesis; open rows only)

Source: four-track deep research (positioning inference / beyond-GEX exposures / vol-surface
fields / world data), full citations in the 2026-07-21 session. Operator mechanical lock:
world data is always in scope; "not adoptable with our data" is a banned disposition.
Verified already-held (no work): per-contract-IV (skew-adjusted) gamma profile;
hypothetical-spot flip recompute (the method SqueezeMetrics/Perfiliev/FlashAlpha document);
`pick_hvl_strike` ≡ SpotGamma Absolute Gamma Strike.

| ID | Status | Work item |
|---|---|---|
| TU-05 | QUEUED | **VEX/CEX**: closed-form BS vanna aggregation (charm exists); publish per-vol-pt and spot-vol-beta-coupled units. Capture-side: persist chain top-level `interestRate`, `dividendYield`, `isChainTruncated` (currently dropped before storage). |
| TU-06 | QUEUED | **Cremers-Weinbaum call−put IV spread** (matched-strike, OI-weighted; ~50bps/wk JFQA 2010) + **implied 1-day move** (total-variance interpolation, VIX-style) + own containment stats per ticker. |
| TU-07 | QUEUED | **ΔOI flow signals** (Fodor 2011 call/put ΔOI ratio — the only published signed daily-data signal). Backfillable from 103 days × 52 tickers already in `snapshots`. Join OCC account-type volume (MM share, customer P/C split) as conditioning fields. |
| TU-08 | QUEUED | **Regime dead-zone**: NEUTRAL band + N-close persistence around the flip (SpotGamma ZG-vs-VT architecture; SqueezeMetrics near-zero = no interference). Thresholds backtested in-house, placebo-anchored. |
| TU-09 | QUEUED | **GEX$/ADV$ normalization** (Barbon-Buraschi — only peer-reviewed cross-ticker scaling) using our own 1m-bar ADV; add cross-ticker rank to terrain. |
| TU-10 | QUEUED | **External GEX benchmark**: reconcile our SPY dealer-gamma series against SqueezeMetrics 15y `world_dix.gex` (SPX). Divergence = investigation, not silent trust. |
| TU-11 | QUEUED | **Skew/term fields**: XZZ smirk (10.9%/yr JFQA 2010), Vasquez term-slope, delta-interpolated 25Δ RR — into daily per-ticker logging for later admission testing. |
| TU-12 | QUEUED | **DDOI-lite** intraday snapshot-signing reconciled vs nightly ΔOI (SqueezeMetrics worked example). UNPROVEN at snapshot frequency — register on build; validation design = reproduce Baltussen conditional-momentum split on our own history. |

**Won't build** (dispositioned, not deferred): unsigned net-premium (direction-blind folklore);
max-pain-as-target (expiry-day pinning only — NPP 2005); BKM risk-neutral-skew quadrature
(documented sparse-strike bias; RR25 first); paid Cboe Open-Close (only if TU-07's free OCC
signal proves decision-critical).

## Console rebuild program — CR (v1.2 consensus-stamped; operator GO 2026-07-21)

Design record and review findings: `governance/CONSOLE_REBUILD_PLAN_CR_V1.md`. The GO stands on the
v1.2 spine; the v1.3 delta rides off the GO-critical path until the next consensus round.

| ID | Status | Work item |
|---|---|---|
| CR-01 | IN PROGRESS | **Streaming spine**: Schwab streamer client (LEVELONE_EQUITIES QOS-Express + CHART_EQUITY + sentinel-first books), topic bus + last-value cache, single batched writer into dedicated **`stream_capture.db`** (ed_console.db grows by ZERO bytes), per-feed health states. Acceptance: bounded queues w/ recorded max depth + drop count + parse p99; REST/streamer/terrain contention matrix; measured key accounting. |
| CR-02 | QUEUED | **Trade prints + CVD (capture)**: Alpaca free IEX websocket (operator opens free account), 30-symbol prints, quote-rule signing, CVD; Schwab-signed vs IEX-signed correlation recorded ≥3 sessions. |
| CR-CAP | QUEUED | **Mechanical capture gate**: ≥3 full RTH sessions in stream_capture.db before ANY UI consumes stream topics — display paths refuse to mount pre-gate (fail-closed test). |
| CR-03 | QUEUED | **Console shell**: typed-message websocket replaces polling loops; main chart panel (lightweight-charts, levels-on-chart, VWAP as fair-value reference only); **demote/hide chance-level ML DOM (hard-delete only per §8.3)**. Panels registry + volume profile deferred to CR-03b. |
| CR-04 | QUEUED | **Regime internals (self-computed, register rows)**: U-shape-normalized RVOL ("range/vol conditioning" copy, never "forecast" pre-CR-07); cross-sectional dispersion + tick-breadth/A-D over streamed constituents (universe sized by CR-01's measured key budget; TICK thresholds = folklore, self-validate vs $TICK). |
| CR-05 | IN PROGRESS | **Evidence tiles / CARD PIPELINE** — referee decoupled from player: ALL designs authored externally (Gemini adversarial audits 2026-07-21/22), executed here verbatim, verdicts by 10k-permutation + power gates. STATE: **#1 Baltussen gamma** PENDING (index arm accrues from wide captures — untestable on narrow-chain history; singles n=42/100, needs earnings scrub); **#2 Gao RV momentum** KILLED on singles (n=295, margin −2.1pts, p=0.7524; sentinels accrue; AM/hist gates disclosed); **#3 MOC anticipation** WAITING on sub-minute stream TWAP (NO 1m approximation — external constraint); **#4 Exhaustion reversal** PRE-REGISTERED 2026-07-22 (external spec verbatim: predictor 09:30→15:30, arm ≥1.0× 20d median intraday range, response 15:30→15:55, hit = sign flip, placebo <0.5× quiet days, OUT-OF-SAMPLE LOCK — forward data from 2026-07-22 ONLY, Mar–Jul history contaminated by discovery; singles additionally blocked on earnings scrub; ship bar: n≥100 forward, p<0.05, margin ≥+4.0pts for spread costs). Named data task: free earnings calendar → scrub #1, unblock #4 singles. |
| CR-06 | QUEUED | **Flow instrumentation pane**: snapshot-OFI + signed-volume + depth imbalance with the literal label "explains, does not predict"; impact coefficient on an explicit trailing window with written leakage rules; **trust labels gated on CR-08's conflation numbers**. |
| CR-07 | QUEUED | **Promotion gate (mechanical)**: unproven-register row + PDCA scorecard per construct; no directional prompt before beating its placebo; **TRADE-shaping tiles additionally pass decision-path admission (`decision_gate.py`)**. ORB-on-RVOL = validation candidate only. |
| CR-08 | QUEUED | **One-time calibration study**: Databento $125 credits — measure what 500ms conflation destroys vs full tape for OFI/signing on SPY; gates CR-06 trust labels. |

**Kills (do not build as predictors)**: VPIN (Andersen-Bondarenko: zero incremental power
vs volume+RV), TICK-extreme rules, VWAP-magnet, unconditional intraday momentum,
overnight-drift harvest (NightShares liquidated), minutes cross-asset lead-lag (ES/VIX/
bond→equity all HFT-arbed), DIX thresholds (vendor-only evidence; replicate in-house from
FINRA inputs before any use), naive FINRA short-ratio reads (FINRA's own notice), 0DTE
net-flow direction (retail lottery demand), gap-fill percentages, book heatmap/footprint/
DOM eye-candy at minutes horizons.

## Sequence (ops / repo)

1. **Quarantine purge** — after one clean trading session + operator purge word (RECON-02 above).
2. **Phase 5 — restructure** — deliberate directory reorganization toward `docs/ARCHITECTURE.md`; no functional changes mixed in; **after** Find & Prove is moving.
3. **Find & Prove** — the queue above is the record of candidate work and evidence; the operator directs execution in chat.

## F2 expansion roadmap (operator directive 2026-07-24)

Baseline banked: SPY draft-cell validation (F1 S1-S5), F2 175-cell grid CLEAN NULL
(`054dbd35`), meta-XGB v1 price-only KILL-family with clean controls (`917fbda8`).
Protocol: every expansion step runs the exact F2 flow — frozen prereg, S3 data gates, economic
evaluator (Holm + DSR + 2x-cost + sign-shuffle placebo hard halt), two-way audit; no unverified
asset or horizon touches serving (the law is `AGENTS.md` Find & Prove substance, RC-210).

| Phase | Study | State | Notes |
|---|---|---|---|
| EXP-1 | **QQQ full study** (grid + meta under its own prereg) | QUEUED | Demoted 2026-07-27 under LP-01. Runner gains `--ticker`; QQQ bar coverage thinner than SPY (56,943 pre-repair bars) — sample floors decide honestly. Tech-heavy validation of the pipeline. |
| EXP-2 | **SPY + QQQ focused vertical studies (15/30-min)** | QUEUED | Verticals 15-60 were already inside the F2 family; EXP-2 is the FOCUSED prereg pair examining win/loss asymmetry + DSR behavior at 15c/30c windows once EXP-1 lands. |
| EXP-3 | **IWM + selected high-beta singles** | QUEUED | Per-ticker volume/liquidity gate BEFORE prereg (Framework Step 8 tier acknowledgment; singles carry gap/halt microstructure SPY does not). |
| EXP-0 | **Dealer-gamma conditioning channel** | BLOCKED ON DATA | The evidenced conditioning source. Unblocks via post-epoch accrual (era floor 1784502281; ~4 sessions at 2026-07-24) or the chain-archive greeks recompute (operator go/no-go). Runs before or alongside EXP-1 the moment data exists. |

UI provenance migration (`bayesian_fusion` -> `meta_xgb_tb_v1`) stays PARKED until a
meta study passes the F2 gate AND operator admission; spec + literal inventory live in
the 2026-07-23/24 session log and the migration is one atomic commit when authorized.
