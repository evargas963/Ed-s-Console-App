# Open items

Open-work ledger for the charter phases (Collect / Find & Prove / Decide). Rows close only with a
commit SHA (and test cite where code changed). History lives in git — closed and superseded rows
are removed, not accumulated; the pre-slimming ledger is preserved at tag-time in history
(`git log --follow OPEN_ITEMS.md`).

**Last rewritten:** 2026-07-16 — post-slimming reconciliation (PR #44 merged @ `8f4c922`).
**Operator NOW (2026-07-27):** **LP-01** is the top open item — see `ACTIVE_PROGRAM.md` Operator NOW table. Work this before residual GEX/F2 queue rows.

---

## Standing truths (change these only with evidence)

| Fact | Status |
|---|---|
| Predictive validity (any horizon beats chance, OOS, net of costs) | **NOT_PROVEN** — 2026-06-01 gate verdict stands |
| Real-money readiness | **NOT_APPROVED** |
| Decision-path admission registry (`governance/decision_path_admissions.json`) | **BUILT_EMPTY** — gate live in `call_engine.compute_call` via `decision_gate.py`; nothing admitted; directional calls force WAIT (running server picks this up on its next restart) |
| Card fidelity overall / universal runtime live proof | **NOT_PROVEN** |
| FP-03..FP-25 battery + LP-01 levels verdicts (kills AND signals) | **ERA-CONTAMINATED — not citable either direction until re-run under the clean protocol (operator 2026-08-01; see Validity notes below)** |

---

## GOVERNING LAW — ONE app, ONE computation, ONE lock (operator 2026-07-17; the anti-churn backbone; do NOT proliferate)

This is the single ruling standard. Everything specific is a CHECK under it, never a new separate lock.

1. **ONE app.** `start_ed_console.bat` → `python -m uvicorn` → `server.py` is the app. The `.ps1`/`.bat` for retrain/scoreboard/research are OFFLINE JOBS against the same DB, not separate apps. There is no "research app."
2. **ONE computation.** Every job (research/backtest/training/scoreboard) IMPORTS and CALLS the live functions (`compute_exposures_by_strike` → `aggregate_net_gex` / `math_levels.*`); it must NEVER reimplement them. "Validated in research" = "runs live" by construction. First unification DONE 2026-07-17: `research/gex_r1_screen_v1/signal.py::gex_0dte_from_chain` now delegates to the live `compute_exposures_by_strike`→`aggregate_net_gex` (numerically identical, ratio 1.0000, tests green, screen unchanged at 204 signals). Sweep the rest of research/training for the same pattern next.
3. **ONE lock = the Institutional Correctness gate — BUILT 2026-07-17: `tools/check_institutional_correctness.py`.** Institutional = logic + math + fidelity + single-source, repo-wide. New correctness requirements are REGISTERED AS CHECKS inside this one gate — never a new lock. Check 1 live: `no_synthetic_domain_fixtures_in_tests` (AST — inline option-chain contracts in tests must load REAL data from `tests/fixtures/`, or declare `# institutional-synthetic-ok: <reason>` for genuine fail-closed/edge cases; `tests/archive/` out of scope). **DONE 2026-07-17: found systemic (44 violations across 20 files) and driven to ZERO — gate PASSES, 213 touched tests green, correctness tests moved to a real captured chain (`tests/fixtures/real_spy_0dte_chain_with_poison.json`), fail-closed tests justified in-line, nothing weakened to pass. WIRED as blocking pre-commit (`.pre-commit-config.yaml` id: institutional-correctness).** Each check is ENFORCED (must be zero, blocks pre-commit) or ADVISORY (visible debt → drive to zero → flip to enforced; the ratchet). Whole-codebase baseline: `python tools/check_institutional_correctness.py`. Registered 2026-07-17 (9 checks; inventory `reports/institutional_debt_inventory.md`): **ENFORCED (block commits, all 0)** = no_synthetic_domain_fixtures, no_silent_swallow (3 sites justified), no_todo_without_tracking_id. **ADVISORY debt to drive down** = function_complexity 455, function_length 393, file_length 38, ruff_quality 1147, no_fake_defaults 10, mypy_types (DORMANT until mypy installed). single-source stays review-enforced (a general auto-detector cries wolf; the GEX reimplementation was fixed manually). Worst file by far: `server.py` (81 items). Fix plan = batches, worst-file-first, WITH operator review + tests — NOT autonomous. NOTE: Layer 1 mechanical is ~complete; Layer 2 (design) partly mechanical + partly review; Layer 3 (real-fix-vs-workaround / elegance) is human by definition — not mechanizable, never claim otherwise.

## Now — post-slimming sequence

- [ ] **LP-01 Institutional session liquidity / value levels** — **TOP OF QUEUE (operator 2026-07-27).** Not SMC “liquidity pools.” Fix VP (volume across bar range, not typical-price dump); overnight = prior trading close→open; demote sell/buy-side liquidity labels until stop-cluster levels are proven; surface POC/VAH/VAL + PDH/PDL + ORB + VWAP on Chart and/or Console v2 (Liquidity Map is in hidden `#main`); touch→forward-return proof vs TOD base rate before any Decide influence. Code: `liquidity_value_engine.py`, `liquidity_models.py`, `/api/liquidity-snapshot`. Program row: `ACTIVE_PROGRAM.md` LP-01. Related residual: UI-04 P1D (PDH walk-back — prior trading day already fixed; overnight still calendar-blind).
- [x] **RECON-01 Operator-doc reconciliation** — `OPEN_ITEMS.md` + `ACTIVE_PROGRAM.md` rebuilt against the charter; stale pointers in `governance/OPERATOR_DECISION_REGISTER.md` fixed. Closed @ `5c5f239` (PR #45).
- [ ] **RECON-02 Disk-cleanup purge** — ~53.3 GB quarantined (moved, not deleted) 2026-07-15/16. Purge only after one clean trading session AND the operator gives the purge word. Separately: `_backup_pre_exec_identity_v1_20260713.db` (19.29 GB) holds until ~5 clean trading days after the slimming merge. **UPDATE 2026-07-26: the slimming merge landed — RC-6 blob-dedup slimmed the live DB 29.74 → 22.06 GB (verified on a copy, swapped live; original preserved as `data/ed_console.pre_rc6_20260726.db`). The 5-clean-day clock for the pre_exec backup now RUNS from 2026-07-26.** Full purge candidate set + gates: `reports/fp_db_deletion_gating_latest.json`.
- [ ] **OPS-OPERABLE-SURFACE-JOB** — ALSO covers (2026-07-20, operator-approved): daily terrain scorecard at 15:30 CT — `python tools/terrain_backtest_report_v1.py` → `reports/terrain_backtest_latest.md`; host task to be registered by the operator with this row as its visible record (`schtasks /Create /SC DAILY /TN EdTerrainScorecard /TR "cmd /c cd /d C:\Users\evarg\Documents\Trading\EdWebConsole && python tools\terrain_backtest_report_v1.py" /ST 15:30`). Recurring Collect job not yet registered on the host: `python -m tools.run_operable_surface_ops --db data/ed_console.db` (production backfill tol=29 + gate). Optional end-of-day: `--refresh-outcomes --repair59 --quarantine`. Durable gate: `python -m tools.operable_surface_gate --db data/ed_console.db --write-report`. Do not create a silent Windows task without an operator-visible inventory row (see FIND-SCHEDULED-JOBS-VISIBILITY).
- [x] **OPS-GEX-MORNING-FULL-MONDAY-GATE** — CLOSED 2026-08-01. The row's ask was "confirm live collector is up on code that includes `option_chain_morning_full` before counting forward GEX days." Confirmed by query: the table carries fresh daily captures — 2026-07-27 through 2026-07-31 at 37–38 tickers/day (`select et_date,count(*) from option_chain_morning_full group by et_date order by et_date desc limit 5`). The collector is demonstrably up and writing on current code (wide-capture writer landed pre-`6c47b89b`; RC-162 @ `202237c7` reads the same pipeline). The forward-counting question the gate protected is itself moot: GEX-R1's day-level bet was KILLED on certified greeks (§8.6), so no forward GEX days are being counted.
- [ ] **PHASE-4 Decision-path gate (mechanical)** — `decision_gate.py` (fail-closed admission verdict) + empty `governance/decision_path_admissions.json` + gate block in `call_engine.compute_call` (last directional authority; would-be direction preserved in `wait_blocker.gated_signal` for the scoring loop) + `tests/test_decision_gate.py`. Landed on branch `decision-path-gate-v1`; closes with the merge SHA. Runtime activation: on the next live-server restart every directional call shows `WAIT — decision path not admitted` until the Find & Prove program earns the first admission.
- [ ] **PHASE-5 Restructure** — deliberate directory reorganization for a legible repo. After Phase 4; no functional changes mixed in.

## Post-slimming FINDs (host + ops)

- [ ] **FIND-SCHWAB-WORKER-LEAK** — `schwab-py` (via `multiprocess`) leaks spawn workers: 15 orphaned Python processes accumulated from scheduled runs before the 2026-07-16 kill; RE-OBSERVED 2026-07-20 — 13 live `multiprocess.spawn` zombies from Jul 17–18 (~39 CPU-s each, PIDs in Cursor's audit); kill after confirming no parent trainer, then the root fix below. Root cause: Schwab client processes not shut down cleanly at end of scheduled jobs. Fix direction: explicit client close/terminate in the scheduled entry points (scoreboard/backfill runners), then observe zero orphans across a week of scheduled runs.
- [x] **FIND-SCHEDULED-JOBS-VISIBILITY** — CLOSED 2026-07-27. The demanded inventory exists: `governance/host_scheduled_jobs.md` — all three Ed tasks (TerrainScorecard, Stream Capture, Daily Scoreboard) with schedule, command, log path, and same-day Last Result = 0 measured live via Get-ScheduledTask/Info. The file carries the standing rule: any task create/rewire/remove updates the inventory in the same change. Motivating incident recorded there: EdTerrainScorecard was scheduled-but-inert for weeks (RC-97) precisely because its definition lived outside version control and outside any inventory.
- [ ] **GAMMA-INTRADAY-CADENCE-V1** (product-stage, NOT for the morning-regime screen) — gamma levels (flip/pin/walls/net_gamma) change intraday as spot moves, 0DTE decays, and OI shifts. The once-daily `option_chain_morning_full` capture is correct for the GEX-R1 morning-regime hypothesis (set stance at open), but a live intraday gamma product needs the WIDE chain refreshed periodically (e.g. every 5–15 min) on a separate low-priority track, decoupled from the per-cycle 20-strike UI fetch. Note: the app ALREADY computes per-snapshot narrow-chain levels every cycle — so intraday levels exist but are narrow/untrustworthy until FIND-GAMMA-FULLCHAIN-STRIKES + sanitization + flip-method land. Sequence AFTER FP-64 proves the morning hypothesis pays; do not scope into tonight.
- [ ] **FIND-LIVE-FLIP-WIDE-CHAIN-V1** (the UI flip is still wrong even after Fix 3) — verified 2026-07-17: `option_chain_morning_full` (wide capture) is **write-only research** — nothing reads it — and the LIVE level compute (`compute_exposures_by_strike`) still runs on the per-cycle 20-strike chain. So the Gamma Flip (and walls/pin) shown ON THE UI stay narrow-limited even after the wide morning capture works. To make the DISPLAYED flip correct, a wide chain must feed the live level compute (periodic wide fetch → live exposures), overlapping GAMMA-INTRADAY-CADENCE-V1. Until then: research/backtest flip can be correct (from the wide table) while the UI flip is not. **ALSO IN SCOPE (2026-07-26, RC-43 reopened): WING-IV TREATMENT.** MEASURED (`python tools/flip_iv_sensitivity_v1.py`, 173 wide chains): the flip's IV sensitivity is almost entirely in the wings — flattening only |moneyness|>3% moves the flip a median **0.3627% of spot** (max 3.80) vs **0.0144%** for near-ATM-only (93.6% within 0.1%). Raw vendor IV is least reliable exactly there, so a wide-chain flip inherits wing-IV noise. Sequenced, NOT a now-task: first validate against an EXTERNAL flip (operator has Barchart access) on a date with a morning wide capture; if a smoothed-wing flip lands closer to Barchart than raw per-strike, wing smoothing is a proven accuracy fix and ships with the wide-chain live compute. Bounding caveat: the measured figures come from aggressive FLATTENINGS, which over-state a real smoothed-surface difference.
- [ ] **CHECK: levels self-declare trust** (a check registered under the ONE Institutional Correctness gate — NOT its own lock). The finite correctness contract every level must meet: (1) sanitized greeks [DONE], (2) single source of truth = one `compute_exposures_by_strike` [TRUE, verified server.py:6083 — all of flip/pin/walls/HVL/max_pain/net_gex/voids derive from it; EM is a separate IV band by design], (3) canonical methods [flip cumulative DONE], (4) full strike coverage to negligible OI/gamma [research Fix 3; live pending FIND-LIVE-FLIP-WIDE-CHAIN], (5) near-term expiries [≤37d], (6) chain fresh. Mechanical lock: each level self-declares `TRUSTED` only if 1–6 hold, else `LOW_CONFIDENCE_NARROW_CHAIN` / `STALE` / `UNSANITIZED`, surfaced in the Key Levels UI (dim/badge) and gated by ONE test asserting the flag derives from input quality. Flip self-declares LOW_CONFIDENCE until FIND-LIVE-FLIP-WIDE-CHAIN lands. This benchmark IS the anti-churn: a bounded checklist, not open-ended.
- [ ] **FIND-GAMMA-FULLCHAIN-STRIKES-V1** (makes the flip actually trustworthy) — audit 2026-07-17: `option_chain_morning_full` capture (server.py:7684) reuses the live UI chain, which is hardwired to `CHAIN_STRIKE_COUNT=20` (server.py:3062) ≈ ±10 strikes (~±1.3% for SPY). It captures multi-expiry (≤37d ✓) but strike-narrow, so the gamma flip still can't see far-OTM put walls and will hug spot regardless of method. Fix: `maybe_persist_morning_full_chain` does its OWN once-daily `safe_get_chain(client, ticker, strike_count=BIG)` (≈100–200 or full range), independent of the 20-strike live fetch (keep UI at 20 for latency). Cursor implements, Claude verifies. Unblocks trustworthy FIND-GAMMA-FLIP-METHOD-V1 output.
- [~] **FIND-GREEK-SANITIZATION-V1** — LANDED 2026-07-17, **Claude-verified on real data** (`gamma_is_plausible` wired at 6 sites; test green; the −91965 SPY-748P day recomputes from net_gamma +1.99e9 → −10,779, sign-flip neutralized). Close on commit SHA. — audit 2026-07-17 (`reports/gex_gamma_flip_audit.md` Finding 0): raw Schwab per-contract gamma is occasionally poisoned on **0DTE deep-ITM** contracts (|delta|≈1, true gamma≈0) where Schwab's near-expiry engine returns garbage (e.g. SPY 748P gamma **−91965**, OI 21605). Rare (SPY 0.11%, QQQ/IWM ~0.02%) but OI-weighted it obliterates net_gamma/GEX/flip for the whole snapshot. Aggregation pipeline itself is faithful (pin/walls reconstructed 25/25). Fix: sanitize greeks before aggregation — hard-reject `gamma<0`, cap/drop `gamma>~0.5–1.0`, optionally `|delta|≥0.98 ⇒ gamma≈0`; apply in live level compute AND research GEX build; unit test with the −91965 fixture. Cursor implements, Claude verifies. Do FIRST (blocks trustworthy FIND-GAMMA-FLIP-METHOD-V1 and FP-64).
- [x] **FIND-GAMMA-FLIP-METHOD-V1** — CLOSED 2026-07-19. The audited method was not just mis-ordered, it was wrong: cumulative-sum of net GEX does not reproduce the gamma profile (measured on a real SPY reference chain: corr 0.086, cumsum never crosses zero, divergence 2.19e9). Replaced by the canonical construction — total dealer gamma **recomputed at every hypothetical spot** (`math_levels.py::compute_gamma_profile`), zero-crossing interpolated (`gamma_flip_from_profile`), served through `compute_gamma_flip_v2` which returns a **confidence flag** so a narrow chain can never be displayed as trustworthy. Live path rewired (`server.py`); old `compute_gamma_flip` and `tests/test_gamma_flip_method_v1.py` deleted (zero production callers). Wide-chain agreement with Barchart remains UNPROVEN — tracked in `governance/unproven_register.md`, due 2026-07-21.
- [ ] **FIND-SNAPSHOT-BAR-STAMP-V1** (durable fix for the timestamp-jitter class) — forensic 2026-07-17 (read-only): host clock, timezone, and `ts_et` are all CORRECT, and `price_bars_1m` is 100% minute-aligned (60s bars). The dislocation is that **snapshot/decision write-timestamps are stamped at arbitrary poll-seconds**, not on the bar edge (second-of-minute is uniform, not clustered at :00). This is the root of the 29s join tolerance (`daily_scoreboard.BACKFILL_JOIN_TOL_SEC=29`), the ±29–30s residual (FP-18), and the FP-24/32 colocation work — those refuse *new* mis-aligned live writes but don't retire the class. Bites hardest on the 1-candle (60s) outcome join; minor at 5c+. **Fix direction:** stamp each snapshot/decision with the `bar_start_ts_utc` of the minute it was computed in (floor the poll instant to its 1m bar), so snapshot↔`price_bars_1m`↔outcome joins are **exact by construction** instead of tolerance-based; then the join tol can drop to 0 and the residual class retires at the source. Separate Collect-hardening track — do NOT fold into the GEX-R1 bet (which sidesteps it by running on `price_bars_1m` and joining by ET day). Connects to **FIND-LABEL-INTEGRITY-FORENSICS** (`TIMESTAMP_IDENTITY_NOT_PROVEN`).

## Gamma product directions (candidate — chase to see if they earn their place; sequence after FP-64 proves harvest)

- [ ] **GAMMA-SCANNER-RADAR** — background scanner computing the gamma regime + a "popping" flag (unusual move/vol/short-gamma) across ALL ~32 collected tickers, alerting the operator regardless of which ticker the UI shows. Best-fit monitoring product; TOS scanners can't compute our gamma-regime signal. Operator-requested 2026-07-17.
- [ ] **GAMMA-STRIKE-PICKER** — trade-construction helper: given operator intent (fast day-trade → max gamma near ATM; higher-probability → target-delta ITM), suggest the strike. Separate from the regime signal; a helper, not the edge.
- [x] **GAMMA-PROFILE-CHARTS** — CLOSED 2026-08-01: delivered across two shipped surfaces. GEX by strike renders on the Chart tab as the blue/red per-strike bars (accrual pipeline, RC-159/RC-161/RC-162 @ `202237c7`, tests `tests/test_chart_accrual_consumer_v1.py` = 10 passed reading the rendered file); flip level, call/put walls and pin render on the Terrain tab (SSOT `/api/terrain` wide capture, per RC-33). Both dependencies the row named are satisfied: full-chain capture exists (`option_chain_morning_full`, daily rows through 2026-07-31) and the flip formula was corrected under FIND-GAMMA-FLIP-METHOD-V1 (closed 2026-07-19, below).
- [ ] **SCOREBOARD-ECONOMIC-REWORK** — keep the scoreboard's purpose (measure → refine inputs → improve signal) but change the metric from direction-accuracy-vs-placeholder to dollars-after-costs of the gamma-conditioned strategy, per regime. Ties to F1/F2 in `reports/fp_levelset_directive_for_cursor.md`.
- [ ] **UNIVERSE-EXPAND-NEWS-NAMES** — extend beyond SPY/QQQ/IWM sentinels to liquid single names (NVDA/TSLA/META/AAPL…), where short-gamma trend days on news may pay best; per-ticker calibration required. Operator: SPY/QQQ/IWM were never binding, just his early starting point.
- [ ] **TOS-SLIPPAGE-CALIBRATION** — calibrate the FP-64 cost model's slippage/leakage to the operator's REAL ThinkOrSwim fills (not theoretical option spread), so the economic gate is honest to his execution.

## Directional bias on the Chart — DIR-** (operator 2026-08-01; discussion-stage, NOTHING built)

**Operator's question, exactly:** GEX dollars roughly equal and options volume roughly equal on
*both* sides of spot — what breaks the tie and says which way spot goes? **Constraint: the existing
GEX and options-volume rendering on the Chart tab is NOT to be touched.** Every row below is
additive or research-only.

**Standing truth that governs all of it:** predictive validity is `NOT_PROVEN`, 18 Find & Prove
studies returned 0 PASS cells, and GEX-R1 was retired at −0.02 (p=0.88) on certified greeks. No row
here may be described as edge until it clears a placebo. All of them start `UNPROVEN`.

- [ ] **DIR-01 (ONE open item — sub-points a–g are facets of it, deliberately not separate rows;
  the ledger is over its cap and may only shrink).**

  **a) DEX as the tie-breaker (the direct answer to the operator's question).** GEX ≈ ∂DEX/∂S:
  DEX is the *level* of the dealer hedge book in shares, GEX is its *slope* per point of spot. The
  Chart currently renders the slope and the flow with the level missing between them. Why it can break
  a symmetric tie specifically: gamma is positive for calls and puts alike, so two clusters of equal
  |GEX| on either side of spot look identical; delta is signed by contract type and moneyness, so the
  same two clusters generally have *different* DEX. That asymmetry is the candidate signal.
  **MEASURED 2026-08-01 (this is a redundancy check, NOT an edge claim):** per-strike correlation
  between `net_delta` and `net_gamma`, computed through the repo's own
  `math_exposure_core.compute_exposures_by_strike` on stored `option_chain_morning_full` chains for
  2026-07-31 — QQQ **0.20**, NVDA **0.52**, SPY **0.55**, IWM **0.91** across 107–145 strikes each.
  So DEX is *not* a restatement of GEX for QQQ/NVDA/SPY, and *nearly is* for IWM — the amount it adds
  is name-dependent and must be measured per ticker, never assumed. Reproduce with
  `.venv/Scripts/python.exe -c "import sqlite3,json;from math_exposure_core import compute_exposures_by_strike;c=sqlite3.connect('file:data/ed_console.db?mode=ro',uri=True);r=c.execute(\"select ticker,spot,chain_json from option_chain_morning_full order by ts_utc desc limit 4\").fetchall();print([(t,len(compute_exposures_by_strike(json.loads(j),spot=s)[0])) for t,s,j in r])"`.
  **NO NEW FEED REQUIRED:** `aggregate_net_dex` and per-strike `net_delta` already exist in
  `math_exposure_core`, and `chain_json` already banks `delta`, `gamma`, `openInterest`,
  `totalVolume`, `bid`, `ask`, `volatility` per contract.

  **b) ΔOI is the cheapest symmetry-breaker we are not using.** Volume is unsigned AND
  ambiguous: it cannot distinguish a position being OPENED from one being CLOSED. Two strikes with
  identical GEX and identical options volume mean opposite things if open interest ROSE at one and
  FELL at the other — a wall forming versus a wall dissolving. `option_chain_morning_full` banks
  per-contract `openInterest` daily (401 rows as of 2026-08-01), so day-over-day ΔOI per strike is
  computable from data already on disk. This is a Collect-side derivation, not a signal; it changes
  what the existing yellow bars MEAN without changing how they render.

  **c) Signed flow — what is and is NOT available (kill the per-trade plan before it is
  built).** The textbook construction is `DEX_t = DEX_open + Σ(signed_volume × Δ_at_trade × 100)`
  with the quote rule signing each print. **We cannot do that: the Schwab feed carries NO options
  trade prints** (see the console rebuild decision — Schwab streamer, no trade prints; Alpaca IEX is
  equities only). What IS available is `totalVolume` per contract per chain snapshot, so the honest
  substitute is Δ`totalVolume` BETWEEN snapshots classified against the bid/ask at the snapshot
  boundaries — a coarse, interval-level approximation that cannot know where inside the interval a
  print landed. Treat it as a weak instrument and pair it with DIR-02, which does not need trade
  signing at all. Anyone proposing per-trade quote-rule signing must first name the trade feed.

  **d) Charm as the time-indexed component (where directional content actually lives).**
  Charm is ∂Δ/∂t — a *rate*, so it converts into a projected share count only against the delta
  position it decays against, i.e. against DEX. That makes DIR-01 a prerequisite rather than an
  alternative. `compute_charm_by_strike` already exists and its sign was FD-verified; `compute_net_charm`
  had an inverted sign, fixed at `053c679f`. The charm VOTE remains **UNAPPROVED** and a residual
  near-expiry T-convention faucet is still open — both must close before charm may condition anything.

  **e) Equal dollars at unequal distance are not equal.** A cluster 0.3% from spot and one
  2% away can carry identical GEX dollars and impose very different hedging pressure per unit of spot
  movement, because the hedge only fires as spot traverses the strike. Any tie-break rule must be
  distance-weighted, and the weighting must be *fitted or justified*, not asserted — an arbitrary
  decay is a free parameter and would make the whole thing ESTIMATED at best.

  **f) The dealer-side convention is the load-bearing assumption, and it is wrong more often
  than the literature admits.** GEX needs ONE assumption (which side dealers are on). DEX needs that
  assumption PLUS correct call/put attribution, so errors compound: a wrong dealer-side assumption
  degrades GEX gracefully but can flip DEX's sign outright. Systematic call-overwriting and buffered
  ETF programs mean customers are net *sellers* of calls at whole strike bands, putting dealers LONG
  those calls and inverting the standard convention exactly there. The operator holds such a position
  personally (Parametric). Keep the locked convention for internal consistency, and treat DEX as a
  **conditioning variable that scales and signs the charm/vanna flow**, never as a standalone
  directional read. A first ad-hoc probe of this on 2026-08-01 used a `putCall` sign factor on top of
  the vendor delta, which double-counted the sign for puts and produced correlations of −0.56 to
  +0.70; recomputing through the repo's own function gave +0.20 to +0.91. The sign convention is
  exactly where this breaks, and it broke on the first attempt.

  **g) The study that would settle it (design, not yet run).** Subsample = sessions where the
  GEX-dollar and options-volume clusters above and below spot are BALANCED within a stated tolerance
  (that is the operator's scenario, and it must be defined mechanically, not by eye). Candidate
  discriminators, each tested alone and in combination: net DEX sign, ΔOI asymmetry, charm-projected
  share flow, distance-weighted cluster mass. Requirements are the standing ones — pre-registered,
  purged/embargoed walk-forward, cost-aware, **placebo-controlled** (displaced clusters, as in LP-01
  where the placebo scored HIGHER and correctly killed the signal), and a stated minimum n with a CI
  that excludes zero. Until it passes, nothing here may reach `governance/decision_path_admissions.json`
  and the Chart renders no directional arrow.

  **h) Charm extends the worked example; the operator's "score" ask (2026-08-01).** Same SPY
  2026-07-31 stored chain, per-strike charm via `math_levels.compute_charm_by_strike` (+call/−put
  convention, units = delta-shares/day): ABOVE spot −526,350 · BELOW −1,224,759 · TOTAL
  −1,751,108 sh/day. Beside gamma ~2:1 and volume 0.75:1, charm sits at ~0.43:1 — and unlike DEX
  it is a FLOW with units and an advance-computable sign (it fires from the clock alone), which
  is the tie-breaker property. CAVEATS: the chain includes 0DTE contracts where the open
  near-expiry T-convention faucet lives, so magnitudes are illustrative only; and the proposed
  above-vs-below directional SCORE is exactly facet (g)'s deliverable — its weights must come OUT
  of the study, never be hand-picked (a hand-weighted score is free parameters wearing a
  formula). Reproduce: load the latest SPY `option_chain_morning_full` row, run
  `compute_exposures_by_strike` + `math_levels.compute_charm_by_strike`, sum per side of spot.

  **i) Chart-tab consumer design (operator direction, 2026-08-01; mockup shown inline, nothing
  built; operator: "subject to change").** A five-row strip — GEX, OV, ΔOI, DEX, charm — laid
  out to READ LEFT-TO-RIGHT LIKE THE PRICE AXIS: **BELOW-spot column | spot (center) |
  ABOVE-spot column** (operator 2026-08-01, superseding the above/below column order in the
  first mockup). It LIVES IN THE SPACE of the raw-levels card inserted under LP-01 Step 4
  (`#rawlevels`); the candle chart stays where it is; the red/blue + yellow bars area is loved
  and untouched. Every number REAL (no fixtures, per the standing UI-data law), re-splitting
  live as spot moves, each row wearing its evidence tier — and **charm does not render at all
  until APPROVED** (T-convention faucet closed + vote), not even greyed. Broader UI
  functional-design consistency cleanup is deferred by the operator: LATER, not now. Below it a MECHANICAL READING line
  (restates measured facts with units, no forecast) and a LOCKED "Bias" slot that fills in only
  when a scoring rule passes facet (g), citing the study. Levels stop rendering always-on:
  culled to A+ credible ones, appearing as proximity PILLS on the candle canvas only when spot
  comes within a threshold (percent or ticks — operator to pick); "A+ credible" requires the
  clean re-run since the LP-01 verdicts are voided, or pure mechanical provenance until then.
  UI overlap cleanup rides along. METHOD NOTE recorded for ΔOI: per-strike delta FIRST, then
  bucket by TODAY's spot — the naive above/below-per-day comparison let the moving spot boundary
  masquerade as OI change and inverted the sign (naive: above −387,645; correct: above +104,621,
  below −173,741, SPY 2026-07-30→31). Reproduce: two latest SPY `option_chain_morning_full`
  rows, per-strike OI delta, bucket by the newer spot.

## Validity — probing notes (operator + Claude, 2026-08-01; prose on purpose, not queue rows)

**Citation rule (operator 2026-08-01):** a study run on contaminated data is NOT citable
evidence — in either direction — until re-run under a clean protocol. Falling under it today:
the LP-01 touch study (`tools/lp01_touch_study_v1.py` is flagged by the institutional gate for
NO trading-session scoping AND no calendar authority on `price_bars_1m`, which carries extended
hours by design) and the FP-03..FP-25 battery (bar/greek repairs landed mid-sequence; the
earlier ~30-null battery is already VOID for the corrupted era). Contamination biases toward
"nothing moved", so the KILLS are as untrustworthy as the signals. Honest status of all of it:
**UNKNOWN, not disproven.**

**Clean-test protocol (required for any re-run):** RTH-scoped via the `time_et` authority ·
certified greeks (`greeks_recomputed_v1`) only · repaired-bar era only · placebo mandatory ·
pre-registered.

**Unapproved inventory (probed 2026-08-01; each item tracked in its own home, listed here so the
set is visible in one place):** register `governance/unproven_register.md` — 6 UNPROVEN rows,
one (intraday flip-drift magnitude) OVERDUE since 2026-07-31 · root-cause log — RC-58, RC-107,
RC-168 OPEN and RC-102/110/115/117/124/165/166 PARTIAL · charm — near-expiry T-convention faucet
open; the charm VOTE stays UNAPPROVED until it closes.

## Find & Prove queue

- [ ] **FIND-LABEL-INTEGRITY-FORENSICS** — 2026-07-16 scoreboard shows cells too extreme in both directions to be noise: `$SPX` 60c **0.0% on n=108** (0/61 directional), `UNH` 0–6.6% across all horizons (n=244), `MSFT` 60c directional 99.0% (n=101), QQQ 60c 72.3%. Extreme-both-ways is the signature of a labeling/join artifact (inverted labels, timestamp misalignment, broken outcome join), not model quality; every horizon carries `TIMESTAMP_IDENTITY_NOT_PROVEN`. Resolve whether these cells are artifacts before trusting any accuracy number. First Find & Prove work item post-merge; feeds the target-truth lane below.
- [ ] **SCOREBOARD-TARGET-TRUTH SCOREBOARD_SEMANTICS_TARGET_TRUTH_AND_60C_ROOT_CAUSE_FORENSIC_V1** — two separate lanes (branch `scoreboard-target-truth-60c-forensic-v1`). Lane A (scoreboard schema v4, operator-semantic safety: trade-decision ALL card, confusion matrices, baselines, fail-closed accuracy presentation, invalid-threshold exclusion) contains HEAD backfill behavior only — no identity-first attachment code is part of the Lane-A package. Lane B (identity-first outcome attachment, `calibration/backfill_outcomes.py` + tests) is NOT in the Lane-A patch — it exists only as uncommitted worktree design; LANE B COMMIT_READY = NO (requires the separate data-impact mission: compound identity, production-copy reconciliation, old-vs-new weights/decisions, migration/rollback, RTH proof). Forensic packet: `reports/scoreboard_forensic/july13_2026_target_truth_forensic.json` — LEGACY_PLACEHOLDER_THRESHOLD CONFIRMED (100% of labeled July-13 rows; 60c threshold spans 0.86–416 bps of spot); target redesign OPEN via the preregistered research protocol.
- [ ] **QUALITY_CIRCLE_SIGNAL_REFINEMENT_V1** — ENABLED / NOT_STARTED (operator 2026-07-09) — DEPENDS ON DAILY_SCOREBOARD_DENOMINATOR_FIRST_V1: input layer VALID as of `06a3f9e8e73811d61364b2829ff462d7b90474de`. The continuous signal-refinement loop consumes the denominator-first scoreboard (eligible grid + quality_circle section) as its measurement substrate. Boundary (binding): the scoreboard identifies weak tickers/horizons/coverage gaps; it does NOT itself approve model or signal-rule changes — any refinement requires a separate audited lane.
- [ ] **STAGE-2 Target/label foundation** — continue `docs/stage1_target_label_foundation/` Stage 2: retire the confirmed placeholder thresholds and design the governed target so scoreboard accuracy becomes decision-valid. Preregistered protocol; no outcome mining.
- [ ] **ML-PIPE-V1 predictive-validity closeout** — remaining from the correctness program: operator-host shuffled-label runs on real capture data per model-family×horizon, then a clean governed retrain, then per-ticker/per-horizon validity classification. Until then the standing NOT_PROVEN verdict holds.
- [ ] **SIG-01 scoreboard/actionability accrual** — sessions 2–5 of segmented multi-day evidence toward signal-outcome validation; logger ~32 tickers, snapshot rows landing all session.

## Audit remainder 2026-07-20 (Cursor sweeping + Bugbot; every non-fixed finding is a row here — prose closes nothing)

- [x] **AUDIT-QUOTE-MEMO-V1** (CLOSED 2026-07-28, RC-112: `_memoized_quote_response` shared by fast lane + `resolve_spot`; acceptance test `test_quote_memo_one_vendor_call_serves_both_paths` passing) — one fix, two audit risks: `/api/terrain` does an unmemoised `safe_get_quote` per poll while the fast lane fetches the same ticker independently (double Schwab fetch, Bugbot/Cursor risk #9), and `get_terrain_radar` ranks on ≤60s loop-time spot while the card reprices live (risk #2). Fix: short-TTL (~1s) server-side quote memo shared by fast lane + `resolve_spot`; memoised quotes then make repricing the radar's top rows affordable. Claude drafts next; closes with commit SHA + a test proving one vendor call serves both paths inside the TTL.
- [ ] **AUDIT-TAPE-OVERFLOW-SHORT-VIEWPORTS** — at 1440×810 the ALERT TAPE tile overflows 30px and at 1366×768 44px (scrollable, not clipped-blind, but the operator wants visible data); radar rail scrolling is intended-by-design and stays. Fix: short-height media query slims tape row padding/font or caps visible entries with a count badge.
- [ ] **AUDIT-CEILING-NARROW-VERDICT-UNOBSERVED** — a ticker needing >TERRAIN_STRIKE_COUNT_MAX(=100) strikes must fetch the ceiling and report LOW_CONFIDENCE_NARROW_CHAIN. UNOBSERVED: $SPX, the only current >100-need ticker, is UNAVAILABLE via empty profile (RC-11 — no contract with OI+plausible gamma) so it never reaches the span verdict. Closes when a >100-need ticker WITH usable greeks is observed reporting NARROW off a live cycle, or a governed synthetic-free test drives the endpoint with a real wide chain truncated to 100.
- [ ] **OPS-PLAYWRIGHT-E2E-RERUN** — operator host: `npm run test:e2e` (marker stale since 2026-05-25; `tests/test_playwright_must_run.py` fails honestly until a REAL run lands). Blocks the first fully-green pytest since May.
- [ ] **OPS-FULL-SUITE-STAMP** — operator host: fresh `python -m pytest -q tests/` after the E2E run. Prior full run 2026-07-20: 4237 passed / 4 failed; the 3 code failures are fixed but the 4240/4241 tally is UNVERIFIED until a fresh complete run (Cursor veracity audit: "not re-proven").

## Defects and held decisions

- [ ] **HELD-RECONCILE-MULTICROSS** — `edReconcileRegime` is exact only for the served (nearest-spot) flip; on multi-crossing profiles a live spot crossing a DIFFERENT boundary shows the old regime for ≤5s until the poll re-anchors. ACCEPTED-DESIGN (operator may overrule): closing it means shipping the 241-point profile to the browser per poll to close a ≤5s cosmetic window; the server recomputes exactly every poll. Revisit only if a real mis-display is observed live.

- [ ] **ML-META-JSON-VERIFICATION-ASYMMETRY** — `_load_lstm` verifies only the `.pt` checkpoint; its `lstm_*_meta.json` is consumed inside `lstm_model.load_lstm` without the Item-4 pre-deserialization verification that xgb/transformer metas get. Found 2026-07-16 while fixing the meta-stack role regression. Fix direction: verify `lstm_meta` in `_load_lstm` before `load_lstm` reads it (same pattern as `transformer_meta` at `ml_predict.py::_load_transformer`).

- [ ] **UI-01 analytics key identity** — root cause of the 2026-07-08 frozen-cards incident: client-retained `activeExpiry` diverges → silent SSE rejection + exact-key GET misses → pending-shell churn. Fix design approved, not started: server-resolved `selected_exp` (generation-guarded), single client key-builder, `analytics_cache_key` payload echo.
- [ ] **UI-04 key-levels display honesty** — P1B: vanna shown is a vega/(S·iv) proxy (label or replace); P1C: charm analytic sign unproven while feeding the call-engine Greeks vote (prove or gate); P1D: PDH prior-trading-day path fixed; overnight calendar-blind residual folded into **LP-01**.
- [ ] **UI-05 guest cold-fusion SLA at the open burst** — mechanism fixes landed (priority pools, chain gate, mkt-ctx single-flight); remaining: RTH open-burst reproof, guest-universe repeatability, SLA regression enforcement.
- [ ] **ECON-01 replay-context residuals** — denominator defect fixed and locked; parent stays open on calibration-version pinning, purged/embargo execution, broader LSTM/Transformer point-in-time windowing, RTH producer-guard observation.
- [ ] **MODEL-04 stale-model serving policy** — evidence delivered (per-ticker vintage table 2026-07-10; ten tickers on pre-correctness 2026-04-30 bundles; guests route through governed anchors). Serve/unserve/retrain policy = operator decision, held.
- [ ] **BUILD-IDENTITY git_sha semantics** — `/api/build.git_sha` reads repo HEAD at request time, not the running process. `process_identity` block (startup SHA + PID) is the working method. Remaining: flip legacy top-level `git_sha` to process identity — operator call.
- [ ] **GOV-REMOTE-ENFORCEMENT** — branch protection verified (PR + required checks + no force-push) but `enforce_admins=false` leaves the admin direct-push channel open. Operator settings decision.
- [ ] **UI-EXPLAIN orphan payload surfaces** — design approved, not rendered: `pred_headline` → explanation rail; `reversal_risk`/`reversal_label` → paired risk chip; closes with rendered DOM + RTH proof for all dispositioned fields. Universal RTH runtime proof (all enrolled tickers, browser DOM, live transport) remains open behind an RTH session window.

---

*Everything not listed here was either closed with evidence (see git history), superseded by the
2026-07 slimming (retired programs: Schwab V4 register, ablation grid law, governance stage plans,
mega walks), or is intentionally not tracked. If a removed concern turns out to be live, it comes
back as a new row with fresh evidence.*
