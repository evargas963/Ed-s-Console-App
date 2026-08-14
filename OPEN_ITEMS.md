# PROJECT A — MASTER BOARD (single structural denominator)

**Closure rule (binding):** a checkbox may be `[x]` ONLY with an exact commit SHA (and test cite where code changed); absent that SHA it is `[ ]` with status text. No closure is inferred from prose, CLOSED_WITH_EVIDENCE labels, CI, neighbouring rows, parent status, another ticker/horizon, or memory.

**Board scope (single denominator):** the canonical Project A denominator is the ENTIRE board under the file H1 `# PROJECT A — MASTER BOARD`. Every active section belongs to that one denominator — all PA sections (PA-1..PA-48, including the PA-48 canonical atomic homes), the F/RC defect board, the `## OPEN ROOT-CAUSE LEDGER DENOMINATOR`, and the `## EXISTING REPO WORK-ITEM SYSTEM RECONCILIATION`. The denominator is NOT any single internal `##` section. The `## LEGACY / HISTORICAL MATERIAL` region is non-closable history (plain bullets, no checkbox state) that lives under this board but contributes no closable items. Nothing is considered closed merely because it is absent from an older list. The single current execution queue is **PA-46** (a pointer view, not an independent closable copy).

**Last rewritten:** 2026-08-13 — Project A master board landed onto `main` (canonical file from `cursor/project-a-board-audit` @ `0e93624`); STATUS_CHANGE / ADD only for slim-`main` leftovers. Board not shrunk. Competing slim ledger (~63 lines, last rewritten 2026-07-16) is superseded as a second "now"; its leftover rows live in **PA-48**, not as a parallel program. `ACTIVE_PROGRAM.md` is a pointer: now = **PA-46**. Charter remains `AGENTS.md`. **2026-08-13 discovery:** six source files the board cited were **absent from `main`** (they only lived on feature branches). Restored onto this branch with SOURCE NAMESPACE banners. **Second census (same day):** governance/reports grepped; material leftovers ADDed to PA-48; F-series CLOSED_WITH_EVIDENCE still `[ ]` because no SHA exists on `main` (RC-344/339/342/340/343 commits are empty in `git log --all`). How to read the ~1125 `[ ]` boxes: most are parent acceptance criteria (PA-1..PA-47), not 1125 independent jobs. Execution queue = **PA-46**. Leftover atomic work = **PA-48**. F-rows labeled CLOSED_WITH_EVIDENCE stay `[ ]` until an exact SHA is on the row — that is the closure rule, not proof they still need doing. **Not 100% complete:** PA-41 stays open; archive/artifacts/`docs/issue19_*` bodies were not fully Read.

The rows in the "## LEGACY / HISTORICAL MATERIAL" region below preserve pre-Project-A work as history only; they are NOT part of the closable Project A denominator.

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

## LEGACY / HISTORICAL MATERIAL
> (historical — NOT part of the Project A closable denominator; every section below is a `###` subordinate of this one heading)
> The rows below predate the Project A master board. They are retained as history/pointers only and are deliberately rendered as plain bullets (no `[ ]`/`[x]` state) so they are never counted in the Project A closable denominator. Material work they name is NOT left as history — every material item has an explicit, closable atomic home on the board below. LP-01's level requirement maps to the atomic technical rows **F15** (POC/VAH/VAL) and **F31** (price-level snapshot fallback); every other named material legacy item carries its own atomic checkbox in **`## PA-48 — LEGACY MATERIAL WORK — CANONICAL ATOMIC HOMES`** (no generic "→ PA-nn parent" pointers — each home names the material requirement itself). Full original text with checkbox state is preserved in git history at `b7178549a499f8b84c5b4dfb51b69d3058e9a89d:OPEN_ITEMS.md` (blob `90c0f23ec7de63df274e9c5c12184debbb1d317a`).

### Now — post-slimming sequence (historical)

- **LP-01 Institutional session liquidity / value levels** — **TOP OF QUEUE (operator 2026-07-27).** Not SMC “liquidity pools.” Fix VP (volume across bar range, not typical-price dump); overnight = prior trading close→open; demote sell/buy-side liquidity labels until stop-cluster levels are proven; surface POC/VAH/VAL + PDH/PDL + ORB + VWAP on Chart and/or Console v2 (Liquidity Map is in hidden `#main`); touch→forward-return proof vs TOD base rate before any Decide influence. Code: `liquidity_value_engine.py`, `liquidity_models.py`, `/api/liquidity-snapshot`. Program row: `ACTIVE_PROGRAM.md` LP-01. Related residual: UI-04 P1D (PDH walk-back — prior trading day already fixed; overnight still calendar-blind).
- **RECON-01 Operator-doc reconciliation** — `OPEN_ITEMS.md` + `ACTIVE_PROGRAM.md` rebuilt against the charter; stale pointers in `governance/OPERATOR_DECISION_REGISTER.md` fixed. Closed @ `5c5f239` (PR #45).
- **RECON-02 Disk-cleanup purge** — ~53.3 GB quarantined (moved, not deleted) 2026-07-15/16. Purge only after one clean trading session AND the operator gives the purge word. Separately: `_backup_pre_exec_identity_v1_20260713.db` (19.29 GB) holds until ~5 clean trading days after the slimming merge. **UPDATE 2026-07-26: the slimming merge landed — RC-6 blob-dedup slimmed the live DB 29.74 → 22.06 GB (verified on a copy, swapped live; original preserved as `data/ed_console.pre_rc6_20260726.db`). The 5-clean-day clock for the pre_exec backup now RUNS from 2026-07-26.** Full purge candidate set + gates: `reports/fp_db_deletion_gating_latest.json`.
- **OPS-OPERABLE-SURFACE-JOB** — ALSO covers (2026-07-20, operator-approved): daily terrain scorecard at 15:30 CT — `python tools/terrain_backtest_report_v1.py` → `reports/terrain_backtest_latest.md`; host task to be registered by the operator with this row as its visible record (`schtasks /Create /SC DAILY /TN EdTerrainScorecard /TR "cmd /c cd /d C:\Users\evarg\Documents\Trading\EdWebConsole && python tools\terrain_backtest_report_v1.py" /ST 15:30`). Recurring Collect job not yet registered on the host: `python -m tools.run_operable_surface_ops --db data/ed_console.db` (production backfill tol=29 + gate). Optional end-of-day: `--refresh-outcomes --repair59 --quarantine`. Durable gate: `python -m tools.operable_surface_gate --db data/ed_console.db --write-report`. Do not create a silent Windows task without an operator-visible inventory row (see FIND-SCHEDULED-JOBS-VISIBILITY).
- **OPS-GEX-MORNING-FULL-MONDAY-GATE** — CLOSED 2026-08-01. The row's ask was "confirm live collector is up on code that includes `option_chain_morning_full` before counting forward GEX days." Confirmed by query: the table carries fresh daily captures — 2026-07-27 through 2026-07-31 at 37–38 tickers/day (`select et_date,count(*) from option_chain_morning_full group by et_date order by et_date desc limit 5`). The collector is demonstrably up and writing on current code (wide-capture writer landed pre-`6c47b89b`; RC-162 @ `202237c7` reads the same pipeline). The forward-counting question the gate protected is itself moot: GEX-R1's day-level bet was KILLED on certified greeks (§8.6), so no forward GEX days are being counted.
- **PHASE-4 Decision-path gate (mechanical)** — `decision_gate.py` (fail-closed admission verdict) + empty `governance/decision_path_admissions.json` + gate block in `call_engine.compute_call` (last directional authority; would-be direction preserved in `wait_blocker.gated_signal` for the scoring loop) + `tests/test_decision_gate.py`. Landed on branch `decision-path-gate-v1`; closes with the merge SHA. Runtime activation: on the next live-server restart every directional call shows `WAIT — decision path not admitted` until the Find & Prove program earns the first admission.
- **PHASE-5 Restructure** — deliberate directory reorganization for a legible repo. After Phase 4; no functional changes mixed in.

### Post-slimming FINDs (host + ops)

- **FIND-SCHWAB-WORKER-LEAK** — `schwab-py` (via `multiprocess`) leaks spawn workers: 15 orphaned Python processes accumulated from scheduled runs before the 2026-07-16 kill; RE-OBSERVED 2026-07-20 — 13 live `multiprocess.spawn` zombies from Jul 17–18 (~39 CPU-s each, PIDs in Cursor's audit); kill after confirming no parent trainer, then the root fix below. Root cause: Schwab client processes not shut down cleanly at end of scheduled jobs. Fix direction: explicit client close/terminate in the scheduled entry points (scoreboard/backfill runners), then observe zero orphans across a week of scheduled runs.
- **FIND-SCHEDULED-JOBS-VISIBILITY** — CLOSED 2026-07-27. The demanded inventory exists: `governance/host_scheduled_jobs.md` — all three Ed tasks (TerrainScorecard, Stream Capture, Daily Scoreboard) with schedule, command, log path, and same-day Last Result = 0 measured live via Get-ScheduledTask/Info. The file carries the standing rule: any task create/rewire/remove updates the inventory in the same change. Motivating incident recorded there: EdTerrainScorecard was scheduled-but-inert for weeks (RC-97) precisely because its definition lived outside version control and outside any inventory.
- **GAMMA-INTRADAY-CADENCE-V1** (product-stage, NOT for the morning-regime screen) — gamma levels (flip/pin/walls/net_gamma) change intraday as spot moves, 0DTE decays, and OI shifts. The once-daily `option_chain_morning_full` capture is correct for the GEX-R1 morning-regime hypothesis (set stance at open), but a live intraday gamma product needs the WIDE chain refreshed periodically (e.g. every 5–15 min) on a separate low-priority track, decoupled from the per-cycle 20-strike UI fetch. Note: the app ALREADY computes per-snapshot narrow-chain levels every cycle — so intraday levels exist but are narrow/untrustworthy until FIND-GAMMA-FULLCHAIN-STRIKES + sanitization + flip-method land. Sequence AFTER FP-64 proves the morning hypothesis pays; do not scope into tonight.
- **FIND-LIVE-FLIP-WIDE-CHAIN-V1** (the UI flip is still wrong even after Fix 3) — verified 2026-07-17: `option_chain_morning_full` (wide capture) is **write-only research** — nothing reads it — and the LIVE level compute (`compute_exposures_by_strike`) still runs on the per-cycle 20-strike chain. So the Gamma Flip (and walls/pin) shown ON THE UI stay narrow-limited even after the wide morning capture works. To make the DISPLAYED flip correct, a wide chain must feed the live level compute (periodic wide fetch → live exposures), overlapping GAMMA-INTRADAY-CADENCE-V1. Until then: research/backtest flip can be correct (from the wide table) while the UI flip is not. **ALSO IN SCOPE (2026-07-26, RC-43 reopened): WING-IV TREATMENT.** MEASURED (`python tools/flip_iv_sensitivity_v1.py`, 173 wide chains): the flip's IV sensitivity is almost entirely in the wings — flattening only |moneyness|>3% moves the flip a median **0.3627% of spot** (max 3.80) vs **0.0144%** for near-ATM-only (93.6% within 0.1%). Raw vendor IV is least reliable exactly there, so a wide-chain flip inherits wing-IV noise. Sequenced, NOT a now-task: first validate against an EXTERNAL flip (operator has Barchart access) on a date with a morning wide capture; if a smoothed-wing flip lands closer to Barchart than raw per-strike, wing smoothing is a proven accuracy fix and ships with the wide-chain live compute. Bounding caveat: the measured figures come from aggressive FLATTENINGS, which over-state a real smoothed-surface difference.
- **CHECK: levels self-declare trust** (a check registered under the ONE Institutional Correctness gate — NOT its own lock). The finite correctness contract every level must meet: (1) sanitized greeks [DONE], (2) single source of truth = one `compute_exposures_by_strike` [TRUE, verified server.py:6083 — all of flip/pin/walls/HVL/max_pain/net_gex/voids derive from it; EM is a separate IV band by design], (3) canonical methods [flip cumulative DONE], (4) full strike coverage to negligible OI/gamma [research Fix 3; live pending FIND-LIVE-FLIP-WIDE-CHAIN], (5) near-term expiries [≤37d], (6) chain fresh. Mechanical lock: each level self-declares `TRUSTED` only if 1–6 hold, else `LOW_CONFIDENCE_NARROW_CHAIN` / `STALE` / `UNSANITIZED`, surfaced in the Key Levels UI (dim/badge) and gated by ONE test asserting the flag derives from input quality. Flip self-declares LOW_CONFIDENCE until FIND-LIVE-FLIP-WIDE-CHAIN lands. This benchmark IS the anti-churn: a bounded checklist, not open-ended.
- **FIND-GAMMA-FULLCHAIN-STRIKES-V1** (makes the flip actually trustworthy) — audit 2026-07-17: `option_chain_morning_full` capture (server.py:7684) reuses the live UI chain, which is hardwired to `CHAIN_STRIKE_COUNT=20` (server.py:3062) ≈ ±10 strikes (~±1.3% for SPY). It captures multi-expiry (≤37d ✓) but strike-narrow, so the gamma flip still can't see far-OTM put walls and will hug spot regardless of method. Fix: `maybe_persist_morning_full_chain` does its OWN once-daily `safe_get_chain(client, ticker, strike_count=BIG)` (≈100–200 or full range), independent of the 20-strike live fetch (keep UI at 20 for latency). Cursor implements, Claude verifies. Unblocks trustworthy FIND-GAMMA-FLIP-METHOD-V1 output.
- **FIND-GREEK-SANITIZATION-V1** — STATUS: NOT_PROVEN (no commit SHA per closure rule). LANDED 2026-07-17, **Claude-verified on real data** (`gamma_is_plausible` wired at 6 sites; test green; the −91965 SPY-748P day recomputes from net_gamma +1.99e9 → −10,779, sign-flip neutralized). Close on commit SHA. — audit 2026-07-17 (`reports/gex_gamma_flip_audit.md` Finding 0): raw Schwab per-contract gamma is occasionally poisoned on **0DTE deep-ITM** contracts (|delta|≈1, true gamma≈0) where Schwab's near-expiry engine returns garbage (e.g. SPY 748P gamma **−91965**, OI 21605). Rare (SPY 0.11%, QQQ/IWM ~0.02%) but OI-weighted it obliterates net_gamma/GEX/flip for the whole snapshot. Aggregation pipeline itself is faithful (pin/walls reconstructed 25/25). Fix: sanitize greeks before aggregation — hard-reject `gamma<0`, cap/drop `gamma>~0.5–1.0`, optionally `|delta|≥0.98 ⇒ gamma≈0`; apply in live level compute AND research GEX build; unit test with the −91965 fixture. Cursor implements, Claude verifies. Do FIRST (blocks trustworthy FIND-GAMMA-FLIP-METHOD-V1 and FP-64).
- **FIND-GAMMA-FLIP-METHOD-V1** — CLOSED 2026-07-19. The audited method was not just mis-ordered, it was wrong: cumulative-sum of net GEX does not reproduce the gamma profile (measured on a real SPY reference chain: corr 0.086, cumsum never crosses zero, divergence 2.19e9). Replaced by the canonical construction — total dealer gamma **recomputed at every hypothetical spot** (`math_levels.py::compute_gamma_profile`), zero-crossing interpolated (`gamma_flip_from_profile`), served through `compute_gamma_flip_v2` which returns a **confidence flag** so a narrow chain can never be displayed as trustworthy. Live path rewired (`server.py`); old `compute_gamma_flip` and `tests/test_gamma_flip_method_v1.py` deleted (zero production callers). Wide-chain agreement with Barchart remains UNPROVEN — tracked in `governance/unproven_register.md`, due 2026-07-21.
- **FIND-SNAPSHOT-BAR-STAMP-V1** (durable fix for the timestamp-jitter class) — forensic 2026-07-17 (read-only): host clock, timezone, and `ts_et` are all CORRECT, and `price_bars_1m` is 100% minute-aligned (60s bars). The dislocation is that **snapshot/decision write-timestamps are stamped at arbitrary poll-seconds**, not on the bar edge (second-of-minute is uniform, not clustered at :00). This is the root of the 29s join tolerance (`daily_scoreboard.BACKFILL_JOIN_TOL_SEC=29`), the ±29–30s residual (FP-18), and the FP-24/32 colocation work — those refuse *new* mis-aligned live writes but don't retire the class. Bites hardest on the 1-candle (60s) outcome join; minor at 5c+. **Fix direction:** stamp each snapshot/decision with the `bar_start_ts_utc` of the minute it was computed in (floor the poll instant to its 1m bar), so snapshot↔`price_bars_1m`↔outcome joins are **exact by construction** instead of tolerance-based; then the join tol can drop to 0 and the residual class retires at the source. Separate Collect-hardening track — do NOT fold into the GEX-R1 bet (which sidesteps it by running on `price_bars_1m` and joining by ET day). Connects to **FIND-LABEL-INTEGRITY-FORENSICS** (`TIMESTAMP_IDENTITY_NOT_PROVEN`).

### Gamma product directions (candidate — chase to see if they earn their place; sequence after FP-64 proves harvest)

- **GAMMA-SCANNER-RADAR** — background scanner computing the gamma regime + a "popping" flag (unusual move/vol/short-gamma) across ALL ~32 collected tickers, alerting the operator regardless of which ticker the UI shows. Best-fit monitoring product; TOS scanners can't compute our gamma-regime signal. Operator-requested 2026-07-17.
- **GAMMA-STRIKE-PICKER** — trade-construction helper: given operator intent (fast day-trade → max gamma near ATM; higher-probability → target-delta ITM), suggest the strike. Separate from the regime signal; a helper, not the edge.
- **GAMMA-PROFILE-CHARTS** — CLOSED 2026-08-01: delivered across two shipped surfaces. GEX by strike renders on the Chart tab as the blue/red per-strike bars (accrual pipeline, RC-159/RC-161/RC-162 @ `202237c7`, tests `tests/test_chart_accrual_consumer_v1.py` = 10 passed reading the rendered file); flip level, call/put walls and pin render on the Terrain tab (SSOT `/api/terrain` wide capture, per RC-33). Both dependencies the row named are satisfied: full-chain capture exists (`option_chain_morning_full`, daily rows through 2026-07-31) and the flip formula was corrected under FIND-GAMMA-FLIP-METHOD-V1 (closed 2026-07-19, below).
- **SCOREBOARD-ECONOMIC-REWORK** — keep the scoreboard's purpose (measure → refine inputs → improve signal) but change the metric from direction-accuracy-vs-placeholder to dollars-after-costs of the gamma-conditioned strategy, per regime. Ties to F1/F2 in `reports/fp_levelset_directive_for_cursor.md`.
- **UNIVERSE-EXPAND-NEWS-NAMES** — extend beyond SPY/QQQ/IWM sentinels to liquid single names (NVDA/TSLA/META/AAPL…), where short-gamma trend days on news may pay best; per-ticker calibration required. Operator: SPY/QQQ/IWM were never binding, just his early starting point.
- **TOS-SLIPPAGE-CALIBRATION** — calibrate the FP-64 cost model's slippage/leakage to the operator's REAL ThinkOrSwim fills (not theoretical option spread), so the economic gate is honest to his execution.

### Directional bias on the Chart — DIR-** (operator 2026-08-01; discussion-stage, NOTHING built)

**Operator's question, exactly:** GEX dollars roughly equal and options volume roughly equal on
*both* sides of spot — what breaks the tie and says which way spot goes? **Constraint: the existing
GEX and options-volume rendering on the Chart tab is NOT to be touched.** Every row below is
additive or research-only.

**Standing truth that governs all of it:** predictive validity is `NOT_PROVEN`, 18 Find & Prove
studies returned 0 PASS cells, and GEX-R1 was retired at −0.02 (p=0.88) on certified greeks. No row
here may be described as edge until it clears a placebo. All of them start `UNPROVEN`.

- **DIR-01 (ONE open item — sub-points a–g are facets of it, deliberately not separate rows;
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

### Validity — probing notes (operator + Claude, 2026-08-01; prose on purpose, not queue rows)

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

### Find & Prove queue

- **FIND-LABEL-INTEGRITY-FORENSICS** — 2026-07-16 scoreboard shows cells too extreme in both directions to be noise: `$SPX` 60c **0.0% on n=108** (0/61 directional), `UNH` 0–6.6% across all horizons (n=244), `MSFT` 60c directional 99.0% (n=101), QQQ 60c 72.3%. Extreme-both-ways is the signature of a labeling/join artifact (inverted labels, timestamp misalignment, broken outcome join), not model quality; every horizon carries `TIMESTAMP_IDENTITY_NOT_PROVEN`. Resolve whether these cells are artifacts before trusting any accuracy number. First Find & Prove work item post-merge; feeds the target-truth lane below.
- **SCOREBOARD-TARGET-TRUTH SCOREBOARD_SEMANTICS_TARGET_TRUTH_AND_60C_ROOT_CAUSE_FORENSIC_V1** — two separate lanes (branch `scoreboard-target-truth-60c-forensic-v1`). Lane A (scoreboard schema v4, operator-semantic safety: trade-decision ALL card, confusion matrices, baselines, fail-closed accuracy presentation, invalid-threshold exclusion) contains HEAD backfill behavior only — no identity-first attachment code is part of the Lane-A package. Lane B (identity-first outcome attachment, `calibration/backfill_outcomes.py` + tests) is NOT in the Lane-A patch — it exists only as uncommitted worktree design; LANE B COMMIT_READY = NO (requires the separate data-impact mission: compound identity, production-copy reconciliation, old-vs-new weights/decisions, migration/rollback, RTH proof). Forensic packet: `reports/scoreboard_forensic/july13_2026_target_truth_forensic.json` — LEGACY_PLACEHOLDER_THRESHOLD CONFIRMED (100% of labeled July-13 rows; 60c threshold spans 0.86–416 bps of spot); target redesign OPEN via the preregistered research protocol.
- **QUALITY_CIRCLE_SIGNAL_REFINEMENT_V1** — ENABLED / NOT_STARTED (operator 2026-07-09) — DEPENDS ON DAILY_SCOREBOARD_DENOMINATOR_FIRST_V1: input layer VALID as of `06a3f9e8e73811d61364b2829ff462d7b90474de`. The continuous signal-refinement loop consumes the denominator-first scoreboard (eligible grid + quality_circle section) as its measurement substrate. Boundary (binding): the scoreboard identifies weak tickers/horizons/coverage gaps; it does NOT itself approve model or signal-rule changes — any refinement requires a separate audited lane.
- **STAGE-2 Target/label foundation** — continue `docs/stage1_target_label_foundation/` Stage 2: retire the confirmed placeholder thresholds and design the governed target so scoreboard accuracy becomes decision-valid. Preregistered protocol; no outcome mining.
- **ML-PIPE-V1 predictive-validity closeout** — remaining from the correctness program: operator-host shuffled-label runs on real capture data per model-family×horizon, then a clean governed retrain, then per-ticker/per-horizon validity classification. Until then the standing NOT_PROVEN verdict holds.
- **SIG-01 scoreboard/actionability accrual** — sessions 2–5 of segmented multi-day evidence toward signal-outcome validation; logger ~32 tickers, snapshot rows landing all session.

### Audit remainder 2026-07-20 (Cursor sweeping + Bugbot; every non-fixed finding is a row here — prose closes nothing)

- **AUDIT-QUOTE-MEMO-V1** (CLOSED 2026-07-28, RC-112: `_memoized_quote_response` shared by fast lane + `resolve_spot`; acceptance test `test_quote_memo_one_vendor_call_serves_both_paths` passing) — one fix, two audit risks: `/api/terrain` does an unmemoised `safe_get_quote` per poll while the fast lane fetches the same ticker independently (double Schwab fetch, Bugbot/Cursor risk #9), and `get_terrain_radar` ranks on ≤60s loop-time spot while the card reprices live (risk #2). Fix: short-TTL (~1s) server-side quote memo shared by fast lane + `resolve_spot`; memoised quotes then make repricing the radar's top rows affordable. Claude drafts next; closes with commit SHA + a test proving one vendor call serves both paths inside the TTL.
- **AUDIT-TAPE-OVERFLOW-SHORT-VIEWPORTS** — at 1440×810 the ALERT TAPE tile overflows 30px and at 1366×768 44px (scrollable, not clipped-blind, but the operator wants visible data); radar rail scrolling is intended-by-design and stays. Fix: short-height media query slims tape row padding/font or caps visible entries with a count badge.
- **AUDIT-CEILING-NARROW-VERDICT-UNOBSERVED** — a ticker needing >TERRAIN_STRIKE_COUNT_MAX(=100) strikes must fetch the ceiling and report LOW_CONFIDENCE_NARROW_CHAIN. UNOBSERVED: $SPX, the only current >100-need ticker, is UNAVAILABLE via empty profile (RC-11 — no contract with OI+plausible gamma) so it never reaches the span verdict. Closes when a >100-need ticker WITH usable greeks is observed reporting NARROW off a live cycle, or a governed synthetic-free test drives the endpoint with a real wide chain truncated to 100.
- **OPS-PLAYWRIGHT-E2E-RERUN** — operator host: `npm run test:e2e` (marker stale since 2026-05-25; `tests/test_playwright_must_run.py` fails honestly until a REAL run lands). Blocks the first fully-green pytest since May.
- **OPS-FULL-SUITE-STAMP** — operator host: fresh `python -m pytest -q tests/` after the E2E run. Prior full run 2026-07-20: 4237 passed / 4 failed; the 3 code failures are fixed but the 4240/4241 tally is UNVERIFIED until a fresh complete run (Cursor veracity audit: "not re-proven").

### Defects and held decisions

- **HELD-RECONCILE-MULTICROSS** — `edReconcileRegime` is exact only for the served (nearest-spot) flip; on multi-crossing profiles a live spot crossing a DIFFERENT boundary shows the old regime for ≤5s until the poll re-anchors. ACCEPTED-DESIGN (operator may overrule): closing it means shipping the 241-point profile to the browser per poll to close a ≤5s cosmetic window; the server recomputes exactly every poll. Revisit only if a real mis-display is observed live.

- **ML-META-JSON-VERIFICATION-ASYMMETRY** — `_load_lstm` verifies only the `.pt` checkpoint; its `lstm_*_meta.json` is consumed inside `lstm_model.load_lstm` without the Item-4 pre-deserialization verification that xgb/transformer metas get. Found 2026-07-16 while fixing the meta-stack role regression. Fix direction: verify `lstm_meta` in `_load_lstm` before `load_lstm` reads it (same pattern as `transformer_meta` at `ml_predict.py::_load_transformer`).

- **UI-01 analytics key identity** — root cause of the 2026-07-08 frozen-cards incident: client-retained `activeExpiry` diverges → silent SSE rejection + exact-key GET misses → pending-shell churn. Fix design approved, not started: server-resolved `selected_exp` (generation-guarded), single client key-builder, `analytics_cache_key` payload echo.
- **UI-04 key-levels display honesty** — P1B: vanna shown is a vega/(S·iv) proxy (label or replace); P1C: charm analytic sign unproven while feeding the call-engine Greeks vote (prove or gate); P1D: PDH prior-trading-day path fixed; overnight calendar-blind residual folded into **LP-01**.
- **UI-05 guest cold-fusion SLA at the open burst** — mechanism fixes landed (priority pools, chain gate, mkt-ctx single-flight); remaining: RTH open-burst reproof, guest-universe repeatability, SLA regression enforcement.
- **ECON-01 replay-context residuals** — denominator defect fixed and locked; parent stays open on calibration-version pinning, purged/embargo execution, broader LSTM/Transformer point-in-time windowing, RTH producer-guard observation.
- **MODEL-04 stale-model serving policy** — evidence delivered (per-ticker vintage table 2026-07-10; ten tickers on pre-correctness 2026-04-30 bundles; guests route through governed anchors). Serve/unserve/retrain policy = operator decision, held.
- **BUILD-IDENTITY git_sha semantics** — `/api/build.git_sha` reads repo HEAD at request time, not the running process. `process_identity` block (startup SHA + PID) is the working method. Remaining: flip legacy top-level `git_sha` to process identity — operator call.
- **GOV-REMOTE-ENFORCEMENT** — branch protection verified (PR + required checks + no force-push) but `enforce_admins=false` leaves the admin direct-push channel open. Operator settings decision.
- **UI-EXPLAIN orphan payload surfaces** — design approved, not rendered: `pred_headline` → explanation rail; `reversal_risk`/`reversal_label` → paired risk chip; closes with rendered DOM + RTH proof for all dispositioned fields. Universal RTH runtime proof (all enrolled tickers, browser DOM, live transport) remains open behind an RTH session window.

---

*(Historical note only: the 2026-07 slimming retired the Schwab V4 register, ablation grid law, governance stage plans, and mega walks. This note does NOT narrow the Project A denominator below — nothing is closed merely by being absent from an older list.)*

---

## PROJECT A — INSTITUTIONAL REPO REHABILITATION MASTER BOARD

> **Added 2026-08-12 (operator-authorized documentation-preservation write).** This is the durable
> Project A master checklist. It is deliberately expansive and must not be shrunk. Rows are never
> silently deleted — future changes use ADD / STATUS_CHANGE / RECONCILIATION. Checkbox rule:
> exactly one closure rule governs this board — the **binding Closure rule at the top of this file**:
> a checkbox is `[x]` ONLY when it is fully proven AND an exact commit SHA (plus test cite where code
> changed) is recorded on the row; every other state — OPEN / FAIL / BLOCKED / NOT_PROVEN / HISTORICAL /
> GAP / unproven acceptance target, and any "CLOSED_WITH_EVIDENCE"/"proven PASS" label lacking that SHA —
> stays `[ ]`. No second or weaker closure rule exists here.
>
> **Governing mission:** SEARCH → FIND → PROVE → FIX → TEST → IMPROVE → NEXT. Work the repo, not the
> board. The board is durable memory of everything that still needs technical proof. This is NOT a
> governance project; parent closure requires every material child closed. SPY/QQQ/IWM are anchors,
> not scope boundaries — all fixes repo-wide and ticker-universal unless a proven economic reason
> requires otherwise.

## PA-1 — UNIVERSALITY (HARD PARENT REQUIREMENT)
The repository is universal. SPY/QQQ/IWM are anchors, not scope boundaries.
- [ ] All fixes are repo-wide by default
- [ ] All fixes are ticker-agnostic by default
- [ ] No SPY-only closure
- [ ] No SPY/QQQ/IWM-only closure
- [ ] Anchor tickers used only as representative validation/control points
- [ ] Guest/non-anchor ticker path proven where applicable
- [ ] Newly introduced ticker follows same canonical semantic authority
- [ ] No hardcoded anchor-ticker branch changes semantic truth
- [ ] Same preprocessing semantics across tickers
- [ ] Same train/serve semantics across tickers
- [ ] Same replay/backfill semantics across tickers
- [ ] Same artifact identity rules across tickers
- [ ] Same cache identity rules across tickers
- [ ] Same missingness semantics across tickers
- [ ] Same fallback rules across tickers
- [ ] Same decision rules across tickers unless intentionally ticker-specific
- [ ] Same UI semantics across tickers
- [ ] Same provenance contract across tickers
- [ ] Same runtime routing rules across tickers
- [ ] Any legitimate ticker-specific exception explicitly identified
- [ ] Any legitimate ticker-specific exception economically justified
- [ ] Any legitimate ticker-specific exception versioned/tested separately
- [ ] Anchor success never substitutes for universal construction proof
- [ ] At least one non-anchor/guest behavioral test where ticker-specific routing is material
- [ ] **UNIVERSALITY_STATUS = PASS**

## PA-2 — ONE FAUCET / SINGLE SEMANTIC AUTHORITY  (LIVE_REACHABLE_PRODUCERS(C) == 1)
- [ ] Every material semantic concept identified
- [ ] Backend producers identified
- [ ] Training producers identified
- [ ] Serving producers identified
- [ ] Replay producers identified
- [ ] Backfill producers identified
- [ ] SQL-derived producers identified
- [ ] Frontend-derived producers identified
- [ ] Cache/reconstruction producers identified
- [ ] Compatibility-shim producers identified
- [ ] Helpers counted when they independently compute truth
- [ ] Wrappers counted when they independently compute truth
- [ ] Builders counted when they independently compute truth
- [ ] Resolvers counted when they independently compute truth
- [ ] Selectors counted when they independently compute truth
- [ ] Normalizers counted when they independently compute truth
- [ ] Transformers counted when they independently compute truth
- [ ] Properties/getters counted when they independently compute truth
- [ ] Inline calculations counted
- [ ] Same meaning under different names searched
- [ ] Same name with different meaning separated
- [ ] Legitimately distinct economic concepts explicitly named distinctly
- [ ] Fallbacks do not silently become second faucets
- [ ] Frontend is never an independent money-path truth authority
- [ ] Replay does not independently re-derive semantics differently
- [ ] Backfill does not independently reinterpret semantics
- [ ] Cache identity never substitutes stale semantic truth
- [ ] **ONE_FAUCET_STATUS = PASS**

## PA-3 — CURRENT CANONICAL / EVIDENCED F-SERIES (F01–F42, gaps)
> **Count (repo-grounded, corrected):** LOWEST = F01, HIGHEST = F42, **EVIDENCED ITEMS = 37** (supersedes Claude's earlier 34 — the difference is F33/F34/F37b, which ARE evidenced F-rows, not merely RC mappings). GAPS = F04, F16, F19, F28, F30, F37-parent (F37b exists). Explicit OPEN = **F10, F15, F25, F31, F39**. F32 = one-authority lock evidenced BUT broader RC-328/artifact-compatibility state NOT_PROVEN. F33/F34/F37b preserved; F35 kept distinct from F01.
- [ ] **F01** — Model denominator / XGB engineered-row parity — CLOSED_WITH_EVIDENCE (RC-344/RC-339; broader universality reproof remains part of parent)
- [ ] **F02** — Net GEX at spot (vendor aggregate vs repriced; distinct books, consumers separated) — CLOSED_WITH_EVIDENCE
- [ ] **F03** — Gamma profile (one formula authority; terrain materializes once; one pinned `now`) — CLOSED_WITH_EVIDENCE
- [ ] **F04** — Reserved/disputed historical slot (gamma/delta walls & pin) — HISTORICAL / NOT_PROVEN (literal ID not repo-tracked; RC-292 overlap; semantic live)
- [ ] **F05** — Trade actionability (one authority; frontend carries; mirror-absent withholds; reopen relocked) — CLOSED_WITH_EVIDENCE
- [ ] **F06** — Expected move semantics (distinct methodologies, source-tagged) — CLOSED_WITH_EVIDENCE
- [ ] **F07** — Gamma regime (one backend sign classifier; client does not reconstruct/write) — CLOSED_WITH_EVIDENCE
- [ ] **F08** — ATR (standard TR+SMA authority; feature variant distinct; Wilder quarantined) — CLOSED_WITH_EVIDENCE
- [ ] **F09** — RTH/session (clock boundary centralized; clock vs calendar distinguished) — CLOSED_WITH_EVIDENCE
- [ ] **F10** — Candle direction — OPEN / WAITING_FOR_HOST_RETRAIN
  - [ ] One dead-band classifier authority (`classify_direction`)
  - [ ] Live producer count = 1 (no second encoder)
  - [ ] Server + normalization delegate to the one authority
  - [ ] Historical normalized rows rebuilt under the dead-band definition
  - [ ] Production training population corrected
  - [ ] SPY/QQQ/IWM retrained under the corrected definition
  - [ ] Non-anchor / universal retrain routing proven
  - [ ] Force-retrain / cache-bypass proven
  - [ ] PREPROCESSING_VERSION bumped atomically with the retrained artifacts
  - [ ] Compatible artifacts published
  - [ ] Governed eval on the retrained generation
  - [ ] Calibration compatibility proven
  - [ ] Atomic promotion of the retrained generation
  - [ ] Runtime restarted on the compatible generation
  - [ ] Runtime train/serve parity proven
  - [ ] Replay/backfill compatibility proven
  - [ ] Universality across tickers proven
- [ ] **F11** — Flow imbalance (one persisted authority; source travels; kwargs contract locked) — CLOSED_WITH_EVIDENCE
- [ ] **F12** — Relative volume variants (distinct RVOL quantities; consumers mapped) — CLOSED_WITH_EVIDENCE
- [ ] **F13** — Black-Scholes valuation T (one `time_to_expiry_years`; expired fail closed) — CLOSED_WITH_EVIDENCE
- [ ] **F14** — VWAP bands (one canonical producer; frontend carries; signal-layer named distinct) — CLOSED_WITH_EVIDENCE
- [ ] **F15** — POC/VAH/VAL — OPEN (Phase 2A / liquidity_value_engine). **2026-08-14 third audit:** swapping the fusion proxy onto the engine changed a live model feature (780.25 → 780.75). Reverted: `signal_layer_v1._volume_profile_proxy` is again the close-price 12-bin. Display path stays the engine. Divergence filed as **RC-330**. Dirty bars fail closed in the engine. Children stay `[ ]` until acceptance is measured on `origin/main`. Remaining: one population site, replay/backfill/frontend, fallback, universality, runtime, retrain-if-unified.
  - [x] Exact semantic contract defined for POC/VAH/VAL — Closed @ `462a581`. Typical-price bin, 70% VA, engine 4dp. Tests: `tests/test_liquidity_engine.py`.
  - [ ] One canonical population site
  - [ ] No alternate population masquerading as the canonical one — REOPENED 2026-08-14. Two input contracts @ `462a581`. Engine now sanitizes dirty bars; wrapper is pass-through. Acceptance measured on this branch (`engine_vp([{'volume':1}])==(None,None,None)`); `[x]` only on `origin/main` SHA.
  - [ ] Session / as-of boundary specified
  - [ ] Live path populates from the canonical producer — `_fetch_state` calls `fetch_price_levels` which calls the engine pass-through. Test: `test_fetch_state_live_path_uses_engine_volume_profile`. `[x]` only on `origin/main` SHA.
  - [ ] Replay path populates from the canonical producer
  - [ ] Backfill path populates from the canonical producer
  - [ ] Frontend path carries the canonical value (no reconstruction)
  - [ ] Fallback + missingness semantics governed
  - [x] Mutation proof (changed inputs change outputs) — Closed @ `462a581`. Tests: `tests/test_liquidity_engine.py`.
  - [ ] Universality across tickers proven
  - [ ] Runtime proof on loaded code
- [ ] **F16** — Reserved/disputed VIX-regime row — HISTORICAL / NOT_PROVEN (identity reconciled; producer `vix_bucket`/`vix_level`; consumers/missingness/fallback/universality/defect-status unproven)
- [ ] **F17** — Realized volatility cadence (`bar_minutes` required; no silent default) — CLOSED_WITH_EVIDENCE
- [ ] **F18** — Charm drift target (not substituted with pin/net-GEX; governed absence; real UI path fixed) — CLOSED_WITH_EVIDENCE
- [ ] **F19** — Reserved/disputed freshness/actionability row — HISTORICAL / NOT_PROVEN (actionability F05 closed; freshness → RC-282 OPEN)
- [ ] **F20** — Pin width (one authority; market_state + server delegate) — CLOSED_WITH_EVIDENCE
- [ ] **F21** — VWAP side (one `derive_vwap_side`; consumers delegate) — CLOSED_WITH_EVIDENCE
- [ ] **F22** — Dominant direction (one triplet authority; DB+UI delegate; missing guarded) — CLOSED_WITH_EVIDENCE, latent hardening verification retained
- [ ] **F23** — Crossed spread (withheld at source; dead helper retired) — CLOSED_WITH_EVIDENCE
- [ ] **F24** — VWAP distance (signed `spot - vwap`; train/serve parity) — CLOSED_WITH_EVIDENCE
- [ ] **F25** — Canonical ticker storage and artifact identity — OPEN / BLOCKED / PRIOR CLOSURES PREMATURE
  - [ ] `ticker_storage_key` single authority established
  - [ ] SPX / `$SPX` identity adjudicated
  - [ ] Readers / writers / logging-universe normalized to the authority
  - [ ] Train-write path canonical
  - [ ] Resume path canonical
  - [ ] Cache path canonical
  - [ ] Artifact-dir path canonical
  - [ ] Arch-eval path canonical
  - [ ] Guest-anchor path canonical
  - [ ] DB-key path canonical
  - [ ] Replay path canonical
  - [ ] Focused tests pass
  - [ ] Entire-repo denominator reverified (remaining identity faucets = 0)
  - [ ] Non-anchor / universal proven
  - [ ] Clean scoped commit lands + exact SHA recorded
  - [ ] Integrated into the production line
  - [ ] Runtime loaded on F25 code + runtime identity proof
  - [ ] Parent RC-345 / F25 closure recorded
- [ ] **F26** — Empirical horizon probability (one authority; UI withholds; no client argmax) — CLOSED_WITH_EVIDENCE
- [ ] **F27** — Higher-timeframe OHLC (one batch synthesizer; live accumulator distinct) — CLOSED_WITH_EVIDENCE
- [ ] **F28** — Reserved/disputed absorption score — HISTORICAL / NOT_PROVEN (producer `liquidity.absorption_score`; consumers/missingness/fallback/dup-search/universality/defect unproven)
- [ ] **F29** — Movement-target threshold (one per-horizon selector; no local reconstruction) — CLOSED_WITH_EVIDENCE
- [ ] **F30** — Reserved/disputed current spot — HISTORICAL / NOT_PROVEN (live spot authority / fast quote / candle-mark-last / train-serve-replay sources / fallbacks / staleness / universality unproven)
- [ ] **F31** — Price-level snapshot fallback — OPEN (Phase 2A)
  - [ ] Canonical population + single producer
  - [ ] Pre-open / RTH / replay semantics specified
  - [ ] Stale-cache handling defined
  - [ ] Input fingerprint governs freshness
  - [ ] Mutual exclusion of sources enforced
  - [ ] Governed fallback semantics
  - [ ] No second truth for the snapshot
  - [ ] Universality across tickers proven
  - [ ] Runtime proof on loaded code
- [ ] **F32** — Confluence `cf_*` authority — NOT_PROVEN (Cursor refuses upgrade while RC-328 OPEN)
  - [ ] Canonical `confluence_features_for_bar` exists
  - [ ] Current code routes train through it
  - [ ] Current code routes serve through it
  - [ ] Wall-clock window semantics defined
  - [ ] RC-328 OPEN conflict reconciled
  - [ ] Train + serve population parity proven
  - [ ] Caller fallback semantics defined
  - [ ] Universality across tickers proven
  - [ ] Ledger contradiction eliminated
- [ ] **F33** — `net_gamma_prev` (raw prior 1m; batch+serve unified; inline producer removed) — CLOSED_WITH_EVIDENCE (RC-342)
- [ ] **F34** — XGB pre-engineering enrichment (five scheduler routes use canonical preparer) — CLOSED_WITH_EVIDENCE (RC-340)
- [ ] **F35** — Training/serving DB identity — children CLOSED_WITH_EVIDENCE; broader DB-authority parent NOT_PROVEN
  - [ ] `train_ticker` forwards `db_path`
  - [ ] Confluence cache carries DB identity
  - [ ] Six callers wired to pass DB identity
  - [ ] Repo-wide parent DB-identity universality audit complete
  - [ ] Every DB-reading lane binds its intended DB
  - [ ] No default DB silently replaces the caller DB
  - [ ] Sandbox DB cannot become production authority
  - [ ] Replay / backfill / artifact-lineage DB identity proven
  - [ ] Universal ticker / data-source proof
- [ ] **F36** — Signal-layer VWAP anchor (source-tagged session preferred; rolling labeled) — CLOSED_WITH_EVIDENCE
- [ ] **F37** — Reserved parent slot — GAP / NOT_PROVEN (parent semantic unproven; F37b exists)
- [ ] **F37b** — LSTM zone encoding (shared `encode_zone`; both sites delegate) — CLOSED_WITH_EVIDENCE (RC-343)
- [ ] **F38** — Training tensor cache identity (content hash; changed labels ⇒ miss; negative control) — CLOSED_WITH_EVIDENCE (universal cache-key inventory remains part of parent)
- [ ] **F39** — Confluence missingness — OPEN (explicitly OPEN despite omission from a shorter RC-345 master-open summary)
  - [ ] Measured-neutral separated from unavailable
  - [ ] Measured-neutral separated from missing-history
  - [ ] Measured-neutral separated from missing-clock
  - [ ] Measured-neutral separated from missing-input
  - [ ] Caller fallback cannot collapse absence into a value
  - [ ] Train / serve / replay / backfill encoding explicit
  - [ ] Active artifact impact measured
  - [ ] Retrain requirement proven
  - [ ] Root code fix landed
  - [ ] Version change applied if required
  - [ ] Retrain executed if required
  - [ ] Calibration compatibility proven
  - [ ] Runtime proof on loaded code
  - [ ] Universality across tickers proven
- [ ] **F40** — MC/GARCH sigma cadence (MC own `BAR_MINUTES`; 5m hardcode removed; live reproof) — CLOSED_WITH_EVIDENCE
- [ ] **F41** — Selected DTE / expiry (selectors require expiry; empty fails closed; no search-all) — CLOSED_WITH_EVIDENCE
- [ ] **F42** — GEX dollars (`gex_dollars_per_1pct_at_strike`; one `compute_exposures_by_strike`; γ×OI×mult×spot²×0.01; one-producer lock) — CLOSED_WITH_EVIDENCE

## PA-4 — MATERIAL NON-F / RC DEFECT BOARD (stay until technically resolved or proven duplicate children)
- [ ] **RC-292** — Gamma-pin semantic collision — OPEN (parent stays open). **2026-08-13/14 measured on this `main`:** Console `kl_gamma_pin` is stamped from `cs.gamma_pin` (`server.py`) = `pick_gamma_pin_strike` = largest `|net GEX$|` per 1% on the selected expiry. HVL is the total-gamma concentration. `pick_pin_and_strength` / `pick_net_gex_peak_strike` / `chart.html` are absent on this `main`. **Label/tooltip/lock @ `0e304f6`. `pin_score` @ `6d14ee2`. Persist + semantic stamp @ `d71bb5e`. Normalized-table stamp @ `053251e`.** Remaining: universality, runtime proof. Charm no longer emits a colliding `gamma_pin` alias.
  - [x] `pin_score` intended semantic recovered — Closed @ `6d14ee2`. Tests: `tests/test_institutional_key_levels.py`.
  - [x] UI label made consistent with the bound semantic — Closed @ `0e304f6`. Tests: `tests/test_institutional_key_levels.py`.
  - [x] Tooltip made consistent with the bound semantic — Closed @ `0e304f6`. Tests: `tests/test_institutional_key_levels.py`.
  - [x] Persisted `gamma_pin` made consistent with the bound semantic — Closed @ `d71bb5e`. Tests: `tests/test_institutional_key_levels.py`.
  - [x] Backward-safe migration for persisted values — Closed @ `d71bb5e` + `053251e`. `gamma_pin_semantic=net_gex_peak`; NULL on old rows means the same writer semantic; numbers not rewritten. Existing `snapshots_1m_normalized` gets the same ALTER (Issue 16). Tests: `tests/test_institutional_key_levels.py`.
  - [x] Behavioral + mutation lock in place — Closed @ `0e304f6`. Tests: `tests/test_institutional_key_levels.py`.
  - [ ] Universality across tickers proven
  - [ ] Runtime proof on loaded code
- [ ] **RC-282** — Freshness / stale actionability — OPEN
  - [ ] Semantic of freshness / actionability defined
  - [ ] Live + UI impact characterized
  - [ ] Stale data cannot remain actionable
  - [ ] Fallback semantics defined
  - [ ] Universality across tickers proven
  - [ ] Root code fix landed
  - [ ] Runtime proof on loaded code
- [ ] **RC-285** — model published `LIVE, edge=0` fabricated zero — OPEN (parent stays open). **2026-08-14 adversarial REJECT:** `1117f19` forbade fabricating edge as 0 then permitted fabricating it as `val_accuracy·100`. Write-site `None` stands. Accuracy fallback removed; UI renders `edge === null` as `—`. LSTM still *requests* `val_accuracy` as its key (RC-291). `[x]` only on `origin/main` SHA.
  - [x] Semantic of the fabricated-zero defect defined — Closed @ `1117f19`. Absent metric ≠ measured zero.
  - [x] Live path characterized — Closed @ `1117f19`. `_fetch_state` → `model_health` → `/api/state`. Tests: `tests/test_model_edge_absent_is_not_zero_v1.py`.
  - [x] Root cause identified — Closed @ `1117f19`. Unread field; `.get(..., 0)` / `float(raw or 0)` / literal `"edge": 0`.
  - [ ] Fix landed — REOPENED 2026-08-14. Accuracy-as-edge fallback violated the principle. Fallback removed this branch; close on `origin/main`.
  - [ ] Proof recorded — REOPENED 2026-08-14. Acceptance: `model_health_edge_from_meta({'val_accuracy':0.55}, 'edge_pp') is None` AND DOM `edge:null` → `—`.
  - [ ] Unmeasured `edge_pp` is not published as `val_accuracy·100`
  - [ ] Model-health UI renders `edge === null` as `—` (not 0 / NaN / throw)
  - [ ] Universality across tickers proven
- [ ] **RC-297** — derivation inventory drifted from code — OPEN (parent stays open). **2026-08-14 adversarial REJECT:** `8ca1f18` added a dormant `if terrain_engine.py exists` clause plus a file-exists loop subsumed by `test_mega2_inventory_covers_every_function`. Guard is now active: planted `*_engine.py` / `terrain_engine.py` outside `MEGA2_FILES` fails today. `[x]` only on `origin/main` SHA.
  - [x] Semantic of the inventory-drift defect defined — Closed @ `8ca1f18`. Drift = inventory AST mismatch in `MEGA2_FILES`.
  - [x] Live path characterized — Closed @ `8ca1f18`. Gate is `tests/test_mega2_traceable_audit.py` (offline).
  - [x] Root cause identified — Closed @ `8ca1f18`. Hand-maintained register; out-of-scope file uninventoried.
  - [ ] Fix landed — REOPENED 2026-08-14. Inert + redundant test is not enforcement. Active plant-guard this branch.
  - [ ] Proof recorded — REOPENED 2026-08-14. Acceptance: tree-fed `uninventoried_engine_modules(git ls-files) == []` AND a real `zzz_engine.py` plant in a tmp git repo is flagged.
  - [ ] Universality across tickers proven
- [ ] **RC-301** — absence-coerced-to-a-value as a CLASS — OPEN (parent stays open). **2026-08-14 adversarial CONDITIONAL:** except-literal fix @ `5d68d93` is real; the gate is a proxy. Docstring now enumerates what it does NOT catch. Uncovered shapes live in **RC-318**. Remaining: class-wide disposition, universality.
  - [x] Semantic of the absence-coercion class defined — Closed @ `5d68d93`. `-> float` + except literal.
  - [x] Live path characterized — Closed @ `5d68d93`. `parity_f_minus_spot_from_contracts` + `tools/check_absence_has_a_type.py` in hardening.
  - [x] Root cause identified — Closed @ `5d68d93`. Return type forecloses `None`.
  - [x] Fix landed — Closed @ `5d68d93` for the two except-literal sites the gate measures. Not the CLASS.
  - [x] Proof recorded — Closed @ `5d68d93`. Tests: `tests/test_absence_has_a_type_gate_v1.py`.
  - [ ] Universality across tickers proven
- [ ] **RC-318** — absence-coerced-to-a-value shapes the RC-301 gate cannot see — OPEN. Spawned by RC-301. Gate flags only `-> float` + except + numeric *literal*. Due dates below are disposition dates, not close licenses.
  - [ ] `lstm_data.py:648` `# absence-ok` except-literal `return 0.0` into a non-nullable encoder. Honest fix: absence mask channel, not 0.0. Due 2026-08-21.
  - [ ] `lstm_data.py:644` None-branch `if v is None: return 0.0` (unmarked; same `_safe_float`). Honest fix: absence mask channel. Due 2026-08-21.
  - [ ] Unannotated functions returning a numeric literal from `except` — gate misses (a). 0 sites on this tree 2026-08-14. Due 2026-08-21 to re-scan / decide.
  - [ ] `-> float | None` functions returning `0.0` from `except` — gate misses (b). 0 sites on this tree 2026-08-14. Due 2026-08-21 to re-scan / decide.
  - [ ] Non-literal fabrications (`return x or 0.0`) — gate misses (c). Measured 2026-08-14 money-path: `db.py:1963`, `db.py:2356`, `liquidity_value_engine.py:249` (sort key), `planes/l1_runtime.py:55`, `server.py:1271`, `training_provenance.py:294`. Due 2026-08-21.
- [ ] **RC-329** — one-producer gate blind to consumer-name→semantic — OPEN (parent stays open). **2026-08-14 second audit:** 1/17 was not one source. `KEY_LEVEL_CONSUMER_REGISTRY` now drives all 17 `kl_*` labels/tips in the payload; KEY LEVELS tables have no hardcoded `label:`. **Pin-fix rebase BLOCKER (OPEN):** `git rebase` of `cursor/pin-fix-net-gex-label-556d` onto this SHA starts 339 commits back and conflicts in 10 files on the first commit. The tip relabel (`ef5c0a2`) re-introduces hardcoded `label:` on `kl_gamma_pin`/`kl_hvl`; this branch already binds those names from `KEY_LEVEL_CONSUMER_REGISTRY` (`Net Γ Peak` / `HVL`) with no painted `label:`. Do not land the paint lineage. Rewrite or drop pin-fix. `[x]` only on `origin/main` SHA.
  - [x] Semantic of the gate blindness defect defined — Closed @ `bb85651`. One writer per name ≠ one (definition, scope).
  - [x] Live path characterized — Closed @ `bb85651`. Console KEY LEVELS `kl_gamma_pin` row.
  - [x] Root cause identified — Closed @ `bb85651`. No registry linking payload key to semantic.
  - [ ] Fix landed — REOPENED 2026-08-14. Two-copy bind is not one source. Payload emit this branch.
  - [ ] Proof recorded — REOPENED 2026-08-14. Acceptance: no hardcoded `label:` on the `kl_gamma_pin` KEY LEVELS row; pin-fix branch label equals main.
  - [ ] Universality across tickers proven
- [ ] **RC-330** — display POC and fusion-feature POC are different algorithms — OPEN. Spawned by F15. Display: `liquidity_value_engine` typical-price tick-bin. Fusion feature: `signal_layer_v1._volume_profile_proxy` close-price 12-bin (restored 2026-08-14 after a silent swap changed the live stack). Do not unify without retrain + non-degradation of every model that consumes `signal_layer_v1`. Due: retrain plan before any engine-delegate on the feature path.
  - [ ] Retrain + validate every model that consumes `signal_layer_v1` if the feature algorithm is changed
  - [ ] Or keep the two algorithms and document the split (current)
  - [ ] Universality across tickers proven
- [ ] **RC-328** — Confluence train/serve population — OPEN
  - [ ] Verify current code closes the original defect
  - [ ] Canonical population site established
  - [ ] Train population routes through the canonical site
  - [ ] Serve population routes through the canonical site
  - [ ] Window semantics defined
  - [ ] Time-based lookback specified
  - [ ] Missingness semantics defined
  - [ ] Universality across tickers proven
  - [ ] Reconcile with F32
  - [ ] Close ledger honestly (no contradiction)

### RC-324 — Price-Level Snapshot Identity / Atomic Materialization
> CODE_APPEARS_FIXED != CLOSED_WITH_EVIDENCE — RC-324 stays OPEN in the ledger even though current code looks repaired.
- [ ] RC-324 formally CLOSED_WITH_EVIDENCE
- [ ] Snapshot input fingerprint includes full material OHLCV/time content
- [ ] Interior bar-data changes alter the fingerprint
- [ ] Read → decide → build → write is protected by `_MATERIALIZE_LOCK`
- [ ] Behavioral regression proof confirmed against the actual materialization path
- [ ] Concurrent same-generation duplicate-result negative control confirmed
- [ ] Stale snapshot reuse negative control confirmed
- [ ] Same-generation double-materialization cannot mint conflicting truths
- [ ] Cache/fingerprint semantics proven universal across applicable tickers
- [ ] Session/pre-open/RTH variants cannot bypass the canonical snapshot identity
- [ ] Replay/backfill path cannot independently materialize a conflicting semantic
- [ ] root_cause_log RC-324 reconciled with exact FIXED evidence
- [ ] Parent/child status consistent
- STATUS: OPEN

### F32 / RC-328 — Active artifact compatibility with the repaired cf_* population (REQUIRED)
> CURRENT CODE PARITY DOES NOT PROVE CURRENT ARTIFACT PARITY. The active artifacts may have been trained BEFORE the RC-332/RC-340 confluence-population repair; if so, serve now uses a semantic population different from what the loaded model learned. Do NOT assume "serve moved toward what train learned" — PROVE what the active artifact actually learned.
- [ ] Exact active artifact generation identified
- [ ] Exact artifact training timestamp identified
- [ ] Exact artifact training code SHA identified
- [ ] Exact artifact preprocessing version identified
- [ ] Exact artifact feature-schema version identified
- [ ] Exact artifact training DB identified
- [ ] Exact artifact training confluence population identified
- [ ] Determine whether active artifact predates RC-332 / canonical confluence-population repair
- [ ] Determine whether active artifact predates RC-340 related confluence fixes
- [ ] Prove artifact learned the same cf_* semantic now produced at serve time
- [ ] Compare old vs current cf_* population semantics if artifact predates repair
- [ ] Quantify material feature divergence on real data if generations differ
- [ ] Quantify effect by ticker
- [ ] Quantify effect by horizon where applicable
- [ ] Include at least one non-anchor/guest ticker if the path applies
- [ ] Determine whether retraining is REQUIRED
- [ ] Determine whether recalibration is REQUIRED
- [ ] Determine whether preprocessing/semantic version bump is REQUIRED
- [ ] If retraining required: rebuild training data under canonical semantics
- [ ] If retraining required: force cache bypass
- [ ] If retraining required: retrain all applicable supported ticker paths
- [ ] If retraining required: governed evaluation
- [ ] If retraining required: calibration compatibility proof
- [ ] If retraining required: atomic artifact promotion
- [ ] If retraining required: runtime restart/load proof
- [ ] Runtime train/serve/artifact semantic parity proven
- [ ] Replay/backfill compatibility proven
- [ ] RC-328 cannot close from code wiring alone
- [ ] F32 cannot close while artifact semantic compatibility is NOT_PROVEN
- UNIVERSALITY_STATUS: NOT_PROVEN until proven

## PA-5 — DATA TRUTH / MARKET DATA
- [ ] One canonical production DB authority
- [ ] Sandbox DB mechanically non-production
- [ ] All runtime DB paths explicit
- [ ] All training DB paths explicit
- [ ] All replay DB paths explicit
- [ ] All backfill DB paths explicit
- [ ] DB identity travels into artifact lineage
- [ ] No silent default DB
- [ ] No competing production truth
- [ ] Timestamp units canonical
- [ ] UTC/ET conversion canonical
- [ ] RTH classification canonical
- [ ] Holiday calendar correct
- [ ] Early-close calendar correct
- [ ] DST handling correct
- [ ] Bar durations correct
- [ ] No overlapping bars
- [ ] No duplicate bars
- [ ] No out-of-order bars
- [ ] Gap detection
- [ ] Staleness detection
- [ ] Repair provenance
- [ ] Live vs repaired/backfilled distinction
- [ ] Corporate-action handling
- [ ] Splits
- [ ] Dividends where relevant
- [ ] Symbol changes
- [ ] Delistings where relevant
- [ ] Underlying/index identity
- [ ] SPX and `$SPX` same-instrument identity
- [ ] Options chain timestamp fidelity
- [ ] NBBO fidelity
- [ ] Bid/ask sizes
- [ ] Last trade timing
- [ ] L2 where used
- [ ] Greeks provenance
- [ ] OI provenance
- [ ] Volume provenance
- [ ] DTE/expiry provenance
- [ ] No revised/future-known vendor data masquerading as historical observation
- [ ] **DATA_TRUTH_STATUS = PASS**

## PA-6 — POINT-IN-TIME / TEMPORAL INTEGRITY
- [ ] Every decision has exact `AS_OF`
- [ ] Every feature has source timestamp
- [ ] Every feature available by decision `AS_OF`
- [ ] No lookahead from future bars
- [ ] No future label leakage
- [ ] No corrected-future-data leakage
- [ ] Options OI timing honest
- [ ] Options Greeks timing honest
- [ ] Corporate-action knowledge point-in-time honest
- [ ] Reference data point-in-time honest
- [ ] Replay uses only information available then
- [ ] Backtest uses point-in-time data
- [ ] Training joins are causal
- [ ] As-of joins are causal
- [ ] Session boundaries causal
- [ ] Historical repair timestamps distinguish observation vs later correction
- [ ] **POINT_IN_TIME_STATUS = PASS**

## PA-7 — TRAIN / SERVE / REPLAY / BACKFILL PARITY (every material feature)
- [ ] Same producer
- [ ] Same formula
- [ ] Same units
- [ ] Same ticker normalization
- [ ] Same population
- [ ] Same lookback
- [ ] Same as-of
- [ ] Same session filter
- [ ] Same missingness
- [ ] Same categorical map
- [ ] Same imputation
- [ ] Same scaling
- [ ] Same ordering
- [ ] Same feature name
- [ ] Same feature schema version
- [ ] Same preprocessing version
- [ ] Same DB identity
- [ ] Same fallback policy
- [ ] Same source methodology
- [ ] Same time resolution
- [ ] Replay parity
- [ ] Backfill parity
- [ ] Non-anchor ticker parity
- [ ] **PARITY_STATUS = PASS**

## PA-8 — FEATURE LINEAGE
- [ ] Every live model feature inventoried
- [ ] Producer known
- [ ] Raw source known
- [ ] Transformation known
- [ ] Units known
- [ ] Lookback known
- [ ] Population known
- [ ] Missingness known
- [ ] Timestamp known
- [ ] Category map known
- [ ] Imputation known
- [ ] Train route known
- [ ] Serve route known
- [ ] Replay route known
- [ ] Backfill route known
- [ ] Artifact schema known
- [ ] No unused/dead feature masquerading as live
- [ ] No live feature missing from training
- [ ] No training feature missing from serving
- [ ] No duplicate semantics under different names
- [ ] **FEATURE_LINEAGE_STATUS = PASS**

## PA-9 — SEMANTIC VERSIONING / MIGRATION
- [ ] Material semantic versions explicit where meaning changed
- [ ] Preprocessing version tied to artifacts
- [ ] Dataset semantic generation identifiable
- [ ] Persisted historical values interpretable
- [ ] Backfill semantic changes versioned
- [ ] Mixed generations detectable
- [ ] Consumers reject incompatible generation
- [ ] No version bump ahead of artifacts
- [ ] No artifacts ahead of runtime code
- [ ] Migration preserves provenance
- [ ] Rollback supported
- [ ] **SEMANTIC_VERSION_STATUS = PASS**

## PA-10 — TRAINING DATASET LINEAGE
- [ ] Exact source DB
- [ ] Exact ticker universe
- [ ] Exact date range
- [ ] Exact row count
- [ ] Exact query/filter
- [ ] Exact RTH/session contract
- [ ] Exact labels
- [ ] Exact feature schema
- [ ] Exact preprocessing version
- [ ] Exact content hash
- [ ] Exact exclusion rules
- [ ] Exact corporate-action version
- [ ] Exact missingness treatment
- [ ] Exact train/validation/test splits
- [ ] Exact folds
- [ ] Exact embargo
- [ ] Exact random seeds
- [ ] Reproducible dataset
- [ ] Artifact contains/links lineage
- [ ] **DATASET_LINEAGE_STATUS = PASS**

## PA-11 — MODEL-CODE CORRECTNESS (every decision-influencing model)
- [ ] Mathematical implementation matches intended algorithm
- [ ] Input tensor shape correct
- [ ] Output semantics correct
- [ ] Class order correct
- [ ] Horizon mapping correct
- [ ] Loss function correct
- [ ] Training target correct
- [ ] No label inversion
- [ ] No class-order inversion
- [ ] No silent fallback model
- [ ] No stale artifact
- [ ] No incompatible pickle/model load
- [ ] No hidden reduced model path masquerading as full stack
- [ ] Deterministic preprocessing
- [ ] Golden-file tests
- [ ] Numerical invariants
- [ ] Behavioral mutation tests
- [ ] **MODEL_CODE_CORRECTNESS = PASS**

## PA-12 — MODEL VALIDATION (each model × ticker × horizon)
- [ ] Shuffle-label test
- [ ] Lookahead test
- [ ] Purged K-fold
- [ ] Embargo
- [ ] Walk-forward
- [ ] True out-of-sample
- [ ] Beat random baseline
- [ ] Beat majority-class baseline
- [ ] Beat persistence baseline
- [ ] Beat simple technical baseline where applicable
- [ ] Ablation
- [ ] Feature importance stability
- [ ] Calibration
- [ ] Per-ticker calibration
- [ ] Per-horizon calibration
- [ ] Reliability diagrams
- [ ] Brier score
- [ ] ECE
- [ ] Confidence calibration
- [ ] Regime robustness
- [ ] Liquidity-regime robustness
- [ ] Volatility-regime robustness
- [ ] Cost-adjusted edge
- [ ] Slippage-adjusted edge
- [ ] Multiple-testing correction where needed
- [ ] Holm-Bonferroni where appropriate
- [ ] Promotion threshold justified
- [ ] Demotion threshold justified
- [ ] **MODEL_VALIDATION_STATUS = PASS**

## PA-13 — META / FUSION LEAKAGE
- [ ] Base-model predictions truly out-of-fold for meta training
- [ ] Meta learner never trains on base in-sample predictions
- [ ] Purging respected across base/meta
- [ ] Embargo respected
- [ ] Calibration does not leak
- [ ] Ensemble selection does not leak
- [ ] Horizon overlap leakage examined
- [ ] Same-day/time dependence handled
- [ ] Artifact-generation separation
- [ ] Training/serving feature-order parity
- [ ] **META_LEAKAGE_STATUS = PASS**

## PA-14 — CALIBRATION
- [ ] Calibration dataset independent
- [ ] Calibration generation versioned
- [ ] Per ticker where evidence supports
- [ ] Per horizon
- [ ] Sparse-support handling
- [ ] Regime dependence tested
- [ ] Stale calibration rejected
- [ ] Artifact/calibration compatibility enforced
- [ ] Calibration cannot silently default
- [ ] Calibration rollback
- [ ] Reliability continuously monitored
- [ ] **CALIBRATION_STATUS = PASS**

## PA-15 — MODEL REPRODUCIBILITY
- [ ] Random seeds recorded
- [ ] Python version recorded
- [ ] Library versions recorded
- [ ] Hardware/runtime differences characterized
- [ ] Dataset hash recorded
- [ ] Feature schema recorded
- [ ] Preprocessing version recorded
- [ ] Training configuration recorded
- [ ] Fold definitions recorded
- [ ] Calibration data recorded
- [ ] Repeated runs statistically equivalent within declared tolerance
- [ ] Instability blocks promotion
- [ ] **REPRODUCIBILITY_STATUS = PASS**

## PA-16 — MODEL PROMOTION / DEMOTION
- [ ] Candidate must beat baseline
- [ ] Candidate must prove OOS edge
- [ ] Candidate must pass leakage checks
- [ ] Candidate must pass calibration
- [ ] Candidate must pass cost/slippage
- [ ] Candidate must pass universality
- [ ] Candidate artifact lineage complete
- [ ] Candidate can run shadow
- [ ] Champion/challenger comparison
- [ ] Promotion atomic
- [ ] Rollback atomic
- [ ] Decayed model demoted
- [ ] Broken artifact fail-closed
- [ ] **PROMOTION_STATUS = PASS**

## PA-17 — EDGE DECAY / DRIFT
- [ ] Rolling OOS edge
- [ ] Feature drift
- [ ] Label drift
- [ ] Probability drift
- [ ] Calibration drift
- [ ] Regime drift
- [ ] Ticker-specific decay
- [ ] Horizon-specific decay
- [ ] Artifact age vs edge
- [ ] Empirical model half-life
- [ ] Retraining cadence empirically justified
- [ ] Automatic retraining never substitutes for validation
- [ ] Demotion on decay
- [ ] **EDGE_DECAY_STATUS = PASS**

## PA-18 — ABSTENTION / TRADE-WAIT-AVOID
- [ ] TRADE definition proven
- [ ] WAIT definition proven
- [ ] AVOID definition proven
- [ ] Abstention-by-default
- [ ] WAIT improves loss avoidance
- [ ] AVOID filters low-quality regimes
- [ ] Coverage vs edge frontier measured
- [ ] Abstention by ticker
- [ ] Abstention by horizon
- [ ] Abstention by regime
- [ ] Abstention by data-quality state
- [ ] False abstention cost measured
- [ ] No incentive to maximize trade count
- [ ] **ABSTENTION_EDGE_STATUS = PASS**

## PA-19 — DECISION ENGINE
- [ ] Inputs canonical
- [ ] Probability triplets canonical
- [ ] Confidence canonical
- [ ] Fusion canonical
- [ ] Policy canonical
- [ ] Risk vetoes canonical
- [ ] Entry state canonical
- [ ] Final bias canonical
- [ ] Final tradeable canonical
- [ ] WAIT reason canonical
- [ ] AVOID reason canonical
- [ ] No UI override
- [ ] No fallback override
- [ ] Missing input lowers/withholds decision rather than invents certainty
- [ ] Stale data lowers/withholds decision
- [ ] Incompatible artifacts block actionability
- [ ] **DECISION_ENGINE_STATUS = PASS**

## PA-20 — DECISION ATTRIBUTION (every decision)
- [ ] Exact timestamp
- [ ] Exact ticker
- [ ] Exact expiry/context
- [ ] Exact source data
- [ ] Exact feature values
- [ ] Exact model generation
- [ ] Exact model probabilities
- [ ] Exact calibration
- [ ] Exact fusion result
- [ ] Exact policy rule
- [ ] Exact veto
- [ ] Exact risk computation
- [ ] Exact final decision
- [ ] Exact reason for WAIT/AVOID
- [ ] Offline replay reproduces same result
- [ ] **DECISION_ATTRIBUTION_STATUS = PASS**

## PA-21 — DECISION LEDGER / REPLAY
- [ ] Every decision stored
- [ ] Inputs recoverable
- [ ] Model generation stored
- [ ] Semantic generation stored
- [ ] Artifact identity stored
- [ ] DB/source identity stored
- [ ] Outcome joined causally
- [ ] Exact replay possible
- [ ] Replay cannot use future-corrected truth
- [ ] Differences explainable
- [ ] Replay universal across tickers
- [ ] **DECISION_REPLAY_STATUS = PASS**

## PA-22 — ECONOMIC INVARIANTS
- [ ] Probabilities sum correctly
- [ ] Probabilities bounded
- [ ] Confidence bounded
- [ ] Volatility non-negative
- [ ] Spread non-negative or withheld
- [ ] DTE non-negative or withheld
- [ ] Stop lies on loss side
- [ ] Target lies on profit side
- [ ] Worse liquidity cannot improve execution quality
- [ ] Higher estimated costs cannot increase net edge
- [ ] Lower risk budget cannot increase allowed size
- [ ] Missing evidence cannot increase conviction
- [ ] Stale evidence cannot increase conviction
- [ ] Gamma sign economically consistent
- [ ] Call/put wall identities preserved
- [ ] Distance sign conventions consistent
- [ ] Unit invariants preserved
- [ ] **ECONOMIC_INVARIANTS_STATUS = PASS**

## PA-23 — NUMERICAL UNITS / PRECISION
- [ ] Dollars vs points explicit
- [ ] Percent vs decimal explicit
- [ ] Annualized vs per-bar volatility explicit
- [ ] Shares vs contracts explicit
- [ ] Option multiplier explicit
- [ ] Raw gamma vs GEX explicit
- [ ] Gamma per $1 vs per 1% explicit
- [ ] Seconds/ms/ns explicit
- [ ] Calendar DTE vs trading-time T explicit
- [ ] Rounding only at presentation boundary where possible
- [ ] No float truncation changing decision semantics
- [ ] No mixed units under same field name
- [ ] **UNITS_PRECISION_STATUS = PASS**

## PA-24 — SENSITIVITY / COUNTERFACTUAL ROBUSTNESS
- [ ] Small price perturbation
- [ ] Small spread perturbation
- [ ] IV perturbation
- [ ] Gamma-wall perturbation
- [ ] Volume perturbation
- [ ] Missing feature
- [ ] Stale feature
- [ ] Probability perturbation
- [ ] Threshold-nearby behavior
- [ ] Regime transition
- [ ] No pathological discontinuity
- [ ] Monotonic behavior where economically expected
- [ ] **SENSITIVITY_STATUS = PASS**

## PA-25 — DECISION STABILITY / CHURN
- [ ] LONG↔SHORT flip frequency measured
- [ ] TRADE↔WAIT churn measured
- [ ] Confidence oscillation measured
- [ ] Entry-state churn measured
- [ ] One-tick-noise sensitivity measured
- [ ] Hysteresis justified where used
- [ ] Smoothing never hides genuine risk
- [ ] UI state never more authoritative than decision truth
- [ ] **DECISION_STABILITY_STATUS = PASS**

## PA-26 — ORDER FLOW / OPTIONS MICROSTRUCTURE
- [ ] NBBO inputs correct
- [ ] Bid/ask size use correct
- [ ] Last trade use correct
- [ ] Trade-sign inference justified
- [ ] Customer/firm/MM flow distinctions correct if used
- [ ] OI semantics correct
- [ ] Options volume semantics correct
- [ ] Delta/gamma/vanna/charm semantics correct
- [ ] DTE filtering correct
- [ ] Expiry selection correct
- [ ] Contract multiplier correct
- [ ] Dealer-sign assumptions explicit/tested
- [ ] Gamma flip semantics correct
- [ ] Gamma walls semantics correct
- [ ] Delta walls semantics correct
- [ ] Vanna/charm semantics correct
- [ ] Pin semantics correct
- [ ] Flow acceleration semantics correct
- [ ] Missing/stale chain handling
- [ ] **OPTIONS_MICROSTRUCTURE_STATUS = PASS**

## PA-27 — LIQUIDITY / VALUE ENGINE
- [ ] PDH
- [ ] PDL
- [ ] PDC
- [ ] Prior POC
- [ ] Prior VAH
- [ ] Prior VAL
- [ ] Overnight high
- [ ] Overnight low
- [ ] ORB high
- [ ] ORB low
- [ ] ORB midpoint
- [ ] VWAP
- [ ] VWAP ±1σ
- [ ] VWAP ±2σ
- [ ] Today POC
- [ ] Today VAH
- [ ] Today VAL
- [ ] Support liquidity
- [ ] Resistance liquidity
- [ ] Fair value
- [ ] Breakout trigger
- [ ] Breakdown trigger
- [ ] VWAP supply
- [ ] VWAP demand
- [ ] Sweep/deep sweep
- [ ] Afternoon value
- [ ] One authority for each semantic
- [ ] No stale-value substitution
- [ ] Pre-open behavior governed
- [ ] Missingness explicit
- [ ] Universality
- [ ] **LIQUIDITY_VALUE_STATUS = PASS**

## PA-28 — EXECUTION REALISM
- [ ] Entry defined precisely
- [ ] Next-bar timing correct
- [ ] Stop logic
- [ ] Target logic
- [ ] Timeout
- [ ] Vertical barrier
- [ ] Same-bar stop/target ambiguity
- [ ] Force-flat
- [ ] Session close
- [ ] Spread
- [ ] Slippage
- [ ] Commission
- [ ] Fees
- [ ] Partial fills
- [ ] Queue assumptions if relevant
- [ ] Latency
- [ ] Market impact
- [ ] Opening auction
- [ ] Closing auction
- [ ] Halt handling
- [ ] Locked market
- [ ] Crossed market
- [ ] One-sided market
- [ ] Option liquidity
- [ ] **EXECUTION_REALISM_STATUS = PASS**

## PA-29 — RISK ENGINE
- [ ] Position size calculation
- [ ] Risk budget
- [ ] Volatility scaling
- [ ] Stop distance
- [ ] Portfolio exposure
- [ ] Correlation exposure
- [ ] Max trade risk
- [ ] Max ticker risk
- [ ] Max sector risk where applicable
- [ ] Max daily loss
- [ ] Consecutive-loss controls
- [ ] Drawdown control
- [ ] Gap risk
- [ ] Expiry risk
- [ ] Extreme-volatility risk
- [ ] Model uncertainty
- [ ] Missing-data risk
- [ ] Staleness risk
- [ ] **RISK_ENGINE_STATUS = PASS**

## PA-30 — KILL SWITCHES / FAILURE MODES
- [ ] Manual emergency stop
- [ ] Data stale kill
- [ ] Data missing kill
- [ ] Artifact incompatible kill
- [ ] Model failure kill
- [ ] DB failure kill
- [ ] Vendor failure kill
- [ ] Abnormal spread kill
- [ ] Runtime exception kill
- [ ] Excess latency kill
- [ ] Excess daily loss kill
- [ ] Corrupted-state kill
- [ ] Tested behaviorally
- [ ] Fail closed
- [ ] **KILL_SWITCH_STATUS = PASS**

## PA-31 — VENDOR / DEPENDENCY FAILURE
- [ ] Schwab outage
- [ ] Partial Schwab response
- [ ] Auth expiration
- [ ] Timeout
- [ ] Rate limit
- [ ] Missing field
- [ ] Field becomes null
- [ ] Field becomes zero
- [ ] Structurally valid but implausible value
- [ ] Stale chain
- [ ] Fresh-quote-stale-Greeks mismatch
- [ ] Fresh-underlying-stale-options mismatch
- [ ] Fallback source provenance
- [ ] No silent semantic substitution
- [ ] **VENDOR_FAILURE_STATUS = PASS**

## PA-32 — ADVERSARIAL MARKET STATES
- [ ] Zero volume
- [ ] Huge spread
- [ ] Crossed quote
- [ ] Locked quote
- [ ] One-sided quote
- [ ] Missing chain
- [ ] Partial chain
- [ ] Extreme IV
- [ ] Invalid IV
- [ ] Zero IV
- [ ] Near expiry
- [ ] Expired contract
- [ ] Huge overnight gap
- [ ] Missing bars
- [ ] Duplicate bars
- [ ] Out-of-order bars
- [ ] Halt
- [ ] Early close
- [ ] DST transition
- [ ] Vendor field disappears
- [ ] Corrupted cache
- [ ] Mixed artifact generations
- [ ] **ADVERSARIAL_MARKET_STATE_STATUS = PASS**

## PA-33 — ARTIFACT IDENTITY (every active artifact)
- [ ] Exact ticker
- [ ] Exact horizon
- [ ] Exact model type
- [ ] Exact training dataset hash
- [ ] Exact feature schema
- [ ] Exact preprocessing version
- [ ] Exact semantic version
- [ ] Exact category maps
- [ ] Exact imputation
- [ ] Exact calibration generation
- [ ] Exact code SHA
- [ ] Exact training DB identity
- [ ] Exact promotion generation
- [ ] Exact creation timestamp
- [ ] Compatible runtime requirements
- [ ] Fail-close on mismatch
- [ ] Atomic promotion
- [ ] Atomic rollback
- [ ] **ARTIFACT_IDENTITY_STATUS = PASS**

## PA-34 — CACHE CORRECTNESS
- [ ] Material input identity included
- [ ] Content changes invalidate
- [ ] DB identity included
- [ ] Ticker identity included
- [ ] Horizon included
- [ ] Semantic generation included
- [ ] Feature schema included
- [ ] Preprocessing version included
- [ ] No stale tensor reuse
- [ ] No cross-ticker collision
- [ ] No SPX-$SPX collision except intentional canonicalization
- [ ] No cross-DB collision
- [ ] No stale decision cache
- [ ] No stale price-level cache
- [ ] Negative-control mutation tests
- [ ] **CACHE_STATUS = PASS**

## PA-35 — CHAMPION / CHALLENGER
- [ ] Champion immutable during comparison
- [ ] Challenger runs shadow
- [ ] Same inputs
- [ ] Same as-of
- [ ] Same costs
- [ ] Decision delta recorded
- [ ] Edge delta measured
- [ ] Calibration compared
- [ ] Abstention compared
- [ ] Stability compared
- [ ] Latency compared
- [ ] Universal ticker comparison
- [ ] Promotion only on evidence
- [ ] **CHAMPION_CHALLENGER_STATUS = PASS**

## PA-36 — UI / OPERATOR TRUTH
- [ ] Every displayed value has canonical backend source
- [ ] No frontend recomputation of semantic truth
- [ ] Direction carried, not recomputed
- [ ] Confidence carried, not recomputed
- [ ] Gamma regime carried, not recomputed
- [ ] Gamma pin carried, not recomputed
- [ ] Charm target carried, not recomputed
- [ ] Expected move carried, not recomputed
- [ ] VWAP carried, not recomputed
- [ ] Price levels carried, not recomputed
- [ ] Risk carried, not recomputed
- [ ] Entry state carried, not recomputed
- [ ] Tradeable state carried, not recomputed
- [ ] WAIT reason carried, not recomputed
- [ ] AVOID reason carried, not recomputed
- [ ] Stale state carried, not recomputed
- [ ] Withheld state carried, not recomputed
- [ ] Missing state carried, not recomputed
- [ ] Source/methodology visible where materially necessary
- [ ] Ticker switch clears stale values
- [ ] Expiry switch clears stale values
- [ ] SSE/REST race safe
- [ ] Fast surface consistent with full state
- [ ] No fake or default confidence
- [ ] No fake or default price level
- [ ] No UI green/actionable state when backend says stale/non-actionable
- [ ] **OPERATOR_TRUTH_STATUS = PASS**

## PA-37 — OBSERVABILITY
- [ ] Runtime SHA visible
- [ ] Artifact generation visible
- [ ] DB identity visible internally
- [ ] Data freshness visible
- [ ] Last successful market-data update visible
- [ ] Last model inference visible
- [ ] Last decision visible
- [ ] Inference latency visible
- [ ] Feature failures visible
- [ ] Artifact failures visible
- [ ] Fallback usage visible
- [ ] Withhold reasons visible
- [ ] Cache hit-miss visible
- [ ] Recompute reasons visible
- [ ] Vendor failures visible
- [ ] Model degradation visible
- [ ] Kill-switch state visible
- [ ] **OBSERVABILITY_STATUS = PASS**

## PA-38 — PERFORMANCE / LATENCY
- [ ] Data ingest latency
- [ ] Normalization latency
- [ ] Feature computation latency
- [ ] Model inference latency
- [ ] Fusion latency
- [ ] Decision latency
- [ ] API latency
- [ ] UI update latency
- [ ] Cache effectiveness
- [ ] Cold-start latency
- [ ] Warm latency
- [ ] P50
- [ ] P95
- [ ] P99 where relevant
- [ ] No correctness compromise to meet SLA
- [ ] **PERFORMANCE_STATUS = PASS**

## PA-39 — SECURITY / SECRETS
- [ ] API secrets not committed
- [ ] Tokens protected
- [ ] Logs do not leak credentials
- [ ] Debug endpoints gated
- [ ] File paths safe
- [ ] SQL injection reviewed
- [ ] Unsafe deserialization reviewed
- [ ] Artifact loading threat model
- [ ] Dependency vulnerabilities reviewed
- [ ] Local network exposure intentional
- [ ] **SECURITY_STATUS = PASS**

## PA-40 — DEAD CODE / RETIREMENT
- [ ] Dead producers removed
- [ ] Legacy semantic authorities retired
- [ ] Old fallbacks removed
- [ ] Obsolete compatibility shims have retirement conditions
- [ ] Dead models removed
- [ ] Dead artifact formats removed
- [ ] Dead UI paths removed
- [ ] Dead research code cannot reach production
- [ ] No duplicate implementation retained "just in case"
- [ ] **RETIREMENT_STATUS = PASS**

## PA-41 — DISCOVERY DENOMINATOR (critical — F01–F42 is not proof of no other duplicate semantics)
- [ ] Independent file census
- [ ] All tracked Python
- [ ] JavaScript
- [ ] HTML inline scripts
- [ ] CSS if semantic behavior exists
- [ ] SQL
- [ ] PowerShell
- [ ] Batch files
- [ ] Makefiles
- [ ] Shell scripts
- [ ] Templates
- [ ] Config with executable expressions
- [ ] Training scripts
- [ ] Scheduler scripts
- [ ] Research scripts capable of feeding production
- [ ] Backtest
- [ ] Replay
- [ ] Cache
- [ ] Migration
- [ ] Compatibility shims
- [ ] Generated execution surfaces
- [ ] Unknown extensions classified
- [ ] Excluded files justified
- [ ] Zero-candidate sampling
- [ ] Structural clones
- [ ] Semantic clones
- [ ] Different-name same-truth producers
- [ ] SQL-derived producers
- [ ] Frontend-derived producers
- [ ] New material defects added to board
- [ ] No unclassified material candidates remain
- [ ] **DISCOVERY_DENOMINATOR_STATUS = PASS**

## PA-42 — TESTING / MUTATION
- [ ] Behavioral tests hit actual code path
- [ ] Mutation tests reintroduce second producer
- [ ] Mutation tests reintroduce fallback
- [ ] Mutation tests reintroduce frontend recomputation
- [ ] Mutation tests reintroduce missing→zero collapse
- [ ] Mutation tests reintroduce wrong units
- [ ] Mutation tests reintroduce train/serve divergence
- [ ] Mutation tests reintroduce stale-cache reuse
- [ ] Mutation tests reintroduce wrong ticker normalization
- [ ] Mutation tests reintroduce wrong DB identity
- [ ] Golden files
- [ ] Economic invariants
- [ ] Universal ticker tests
- [ ] Runtime tests
- [ ] Negative controls
- [ ] **TESTING_STATUS = PASS**

## PA-43 — RUNTIME / PRODUCTION PROOF
- [ ] Exact HEAD SHA
- [ ] Exact origin/main SHA
- [ ] Clean/known worktree state
- [ ] Runtime PID
- [ ] Runtime command
- [ ] Runtime SHA == tested SHA
- [ ] Runtime artifacts == approved generation
- [ ] Runtime DB == canonical production DB
- [ ] SPY runtime proof
- [ ] QQQ runtime proof
- [ ] IWM runtime proof
- [ ] Non-anchor ticker runtime proof
- [ ] Guest ticker runtime proof
- [ ] Ticker switching
- [ ] Expiry switching
- [ ] Stale-data behavior
- [ ] Withholding behavior
- [ ] Missing-data behavior
- [ ] Cache invalidation
- [ ] SSE
- [ ] REST
- [ ] Restart reproducibility
- [ ] Live decision fidelity
- [ ] Live operator fidelity
- [ ] **RUNTIME_PROOF_STATUS = PASS**

## PA-44 — REAL-MONEY READINESS
- [ ] Data truth complete
- [ ] Point-in-time integrity complete
- [ ] Semantic authority complete
- [ ] Universality complete
- [ ] Train parity complete
- [ ] Serve parity complete
- [ ] Replay parity complete
- [ ] Backfill parity complete
- [ ] Model correctness complete
- [ ] OOS edge complete
- [ ] Calibration complete
- [ ] Costs complete
- [ ] Slippage complete
- [ ] Risk engine complete
- [ ] Kill switches complete
- [ ] Decision replay complete
- [ ] Runtime proof complete
- [ ] Operator truth complete
- [ ] No material NOT_PROVEN
- [ ] No material open F-row
- [ ] No material open RC defect
- [ ] No material unclassified producer
- [ ] **REAL_MONEY_READY = YES**

## PA-45 — BOARD HISTORY / PRESERVATION (lightweight bookkeeping only)
- [ ] No row silently deleted
- [ ] New defect → ADD
- [ ] Status transition → STATUS_CHANGE
- [ ] Renamed/merged/superseded → RECONCILIATION
- [ ] Reopened row retains reason
- [ ] Old closure evidence preserved
- [ ] False closure explicitly backtracked
- [ ] Historical disputed rows retained until adjudicated
- [ ] Board updated immediately after material proof
- [ ] **BOARD_INTEGRITY_STATUS = PASS**

## PA-46 — CURRENT TOP ACTIVE EXECUTION QUEUE (POINTER VIEW — not independently closable)
> Pointers to canonical rows; status derives from those rows. No independent `[ ]`/`[x]` state — never counted as engineering completion.
- F10 → canonical F10 row (OPEN / host retrain)
- F15 → canonical F15 row (OPEN; fusion feature restored to close-price 12-bin; display engine unchanged; RC-330)
- F25 → canonical F25 row (OPEN)
- F31 → canonical F31 row (OPEN)
- F32 → canonical F32 row (NOT_PROVEN; RC-328)
- F39 → canonical F39 row (OPEN)
- RC-292 → canonical RC-292 row (OPEN; label/tooltip/lock @ `0e304f6`; pin_score @ `6d14ee2`; persist/migration @ `d71bb5e` + `053251e`)
- RC-282 → canonical RC-282 row
- RC-285 → canonical RC-285 row (OPEN; write-site `None` @ `1117f19`; accuracy fallback REOPENED; universality remains)
- RC-297 → canonical RC-297 row (OPEN; dormant lock REOPENED; plant-guard this branch)
- RC-301 → canonical RC-301 row (OPEN; except-literal gate @ `5d68d93`; CLASS / RC-318 remain)
- RC-318 → canonical RC-318 row (OPEN; `# absence-ok` + uncovered shapes; due 2026-08-21)
- RC-329 → canonical RC-329 row (OPEN; two-copy bind REOPENED; payload emit this branch)
- RC-330 → canonical RC-330 row (OPEN; display vs fusion-feature POC; do not unify without retrain)
- F35 broader DB-identity parent → PA-3 F35 row
- Historical/disputed F04/F16/F19/F28/F30/F37 → PA-3 gap rows
- Discovery denominator → PA-41
- Universal runtime proof → PA-43
- UX-WORLD-CLASS-CONSOLE → PA-48 (**NOT NOW.** AFTER PA-2 + PA-36 + RC-292 + F15 + LEVELS-SELF-DECLARE-TRUST)

## PA-47 — PROJECT A FINAL CLOSURE (all must be satisfied)
- [ ] All canonical F rows closed
- [ ] All disputed F rows adjudicated
- [ ] All material non-F RC defects closed
- [ ] All material NOT_PROVEN = 0
- [ ] All parent/child status contradictions eliminated
- [ ] One Faucet proven universally
- [ ] Universality proven across supported ticker paths
- [ ] Data truth proven
- [ ] Point-in-time truth proven
- [ ] Train parity proven
- [ ] Serve parity proven
- [ ] Replay parity proven
- [ ] Backfill parity proven
- [ ] Feature lineage proven
- [ ] Artifact lineage proven
- [ ] Cache correctness proven
- [ ] Model-code correctness proven
- [ ] OOS predictive edge proven
- [ ] Calibration proven
- [ ] Meta leakage eliminated
- [ ] Economic invariants proven
- [ ] Execution realism proven
- [ ] Risk engine proven
- [ ] Kill switches proven
- [ ] Decision attribution proven
- [ ] Decision replay proven
- [ ] Operator/UI truth proven
- [ ] Observability proven
- [ ] Performance proven
- [ ] Security proven
- [ ] Discovery denominator exhausted/adjudicated
- [ ] Current runtime proof complete
- [ ] Clean reproducible production state
- [ ] Real-money readiness proven
- [ ] **PROJECT A = CLOSED_WITH_EVIDENCE**

## PA-48 — LEGACY MATERIAL WORK — CANONICAL ATOMIC HOMES
> Every material work item named in the `## LEGACY / HISTORICAL MATERIAL` region above has its canonical, closable home here as one atomic requirement per checkbox. The legacy prose stays history-only; the *work* is not — it lives on this board. Closure obeys the single binding Closure rule at the top of this file (exact commit SHA / evidence, else `[ ]`). Items proven already closed/superseded are recorded with their canonical replacement rather than a new box.
- [ ] **FIND-SCHWAB-WORKER-LEAK** — explicit Schwab client close/terminate added to every scheduled entry point (scoreboard/backfill runners), and zero orphaned `multiprocess.spawn` workers observed across a full week of scheduled runs
- [ ] **FIND-LIVE-FLIP-WIDE-CHAIN** — the LIVE level compute (`compute_exposures_by_strike`) reads a wide chain (periodic wide fetch → live exposures), so the displayed Gamma Flip / walls / pin are no longer 20-strike-narrow-limited (relates to F42; maps to FIND-GAMMA-FULLCHAIN below)
- [ ] **WING-IV (RC-43 reopened)** — wide-chain flip validated against an external Barchart flip on a date with a morning wide capture; wing-IV smoothing then proven an accuracy fix (ships) or rejected — no smoothing asserted without that comparison
- [ ] **FIND-GAMMA-FULLCHAIN** — `maybe_persist_morning_full_chain` performs its OWN once-daily wide `safe_get_chain(strike_count=BIG)` independent of the 20-strike live UI fetch (UI stays 20 for latency)
- [ ] **FIND-SNAPSHOT-BAR-STAMP** — each snapshot/decision stamped with the `bar_start_ts_utc` of the minute it was computed in (poll instant floored to its 1m bar) so snapshot↔`price_bars_1m`↔outcome joins are exact by construction and the 29s join tolerance can drop to 0
- [x] **UI-01 analytics key identity** — server stamps `analytics_cache_key` on A/B/C payloads; client uses one key-builder for SSE/REST and generation-guarded adopt of server `selected_exp`. Closed @ `bc1b635`. Tests: `tests/test_ui01_analytics_cache_key.py`.
- [ ] **UI-05 guest cold-fusion SLA** — cold P50 8.79s / P95 10.21s vs 15s SLA measured @ `6a74331`, board-recorded @ `5506185` (on `main`). Remaining: RTH open-burst reproof + guest-universe repeatability + SLA regression enforcement. Do not `[x]` on the cold-SLA SHA alone.
- [ ] **AUDIT-TAPE-OVERFLOW-SHORT-VIEWPORTS** — ALERT TAPE tile no longer overflows at 1440×810 and 1366×768 (short-height media query slims padding/font or caps visible entries with a count badge)
- [ ] **OPS-PLAYWRIGHT-E2E-RERUN** — a real `npm run test:e2e` run lands (retiring the stale 2026-05-25 marker) and `tests/test_playwright_must_run.py` passes on that real run
- [ ] **GOV-REMOTE-ENFORCEMENT** — operator settings decision on `enforce_admins` recorded and executed (admin direct-push channel closed or explicitly accepted with rationale); external-boundary item until the operator acts
- [ ] **BUILD-IDENTITY `git_sha` semantics** — legacy top-level `/api/build.git_sha` flipped to process identity (startup SHA + PID), or the operator decision to keep request-time HEAD recorded on the row
- [ ] **DIR-01 directional-bias discriminator** — the facet-(g) study (net DEX sign / ΔOI asymmetry / charm-projected flow / distance-weighted mass) run under the clean protocol, placebo-controlled, and dispositioned; nothing reaches `decision_path_admissions.json` and the Chart renders no directional arrow until it clears a placebo
- [ ] **RECON-02 disk-cleanup purge** — full purge executed only after one clean trading session AND the operator's purge word; `_backup_pre_exec_identity_v1` released only after 5 clean trading days from 2026-07-26
- [x] **PHASE-4 decision-path gate** — `decision_gate.py` + empty admissions + `call_engine.compute_call` gate + `tests/test_decision_gate.py` merged to the mainline. Closed @ `e009aa2` (PR #46). Runtime: directional calls stay `WAIT — decision path not admitted` until Find & Prove earns the first admission.
- [ ] **PHASE-5 restructure** — deliberate directory reorganization for a legible repo completed after Phase 4, with no functional changes mixed in
- [ ] **FIND-LABEL-INTEGRITY-FORENSICS** — the extreme scoreboard cells ($SPX 60c 0.0% n=108, MSFT 60c 99.0% n=101, UNH 0–6.6%, QQQ 60c 72.3%) proven to be labeling/join/timestamp artifacts or genuine, before any accuracy number is trusted; `TIMESTAMP_IDENTITY_NOT_PROVEN` resolved per horizon
- [ ] **SCOREBOARD-TARGET-TRUTH — Lane A** — scoreboard schema v4 landed: trade-decision ALL card, confusion matrices, baselines, fail-closed accuracy presentation, invalid-threshold exclusion (independently falsifiable from Lane B)
- [ ] **SCOREBOARD-TARGET-TRUTH — Lane B** — identity-first outcome attachment (`calibration/backfill_outcomes.py` + tests) proven end-to-end: compound identity, production-copy reconciliation, old-vs-new weights/decisions, migration/rollback, RTH proof (currently LANE B COMMIT_READY = NO)
- [x] **UI-04 P1B — vanna honesty** — UI labels the shown value as a vega/(S·iv) proxy (not true vanna). Closed @ `29ea1e4`. Tests: `tests/test_charm_vote_gate.py`.
- [x] **UI-04 P1C — charm sign gate** — charm vote gated (`CHARM_VOTE_VALIDATION_STATUS == "UNAPPROVED"`) until analytic sign is proven. Closed @ `29ea1e4`. Tests: `tests/test_charm_vote_gate.py`. Sign proof itself is still NOT_PROVEN — the gate is the close, not a validity claim.
- [x] **UI-04 P1D — PDH prior trading day** — PDH uses previous trading day (`liquidity_value_engine.py`), fail-closed without prior RTH bars. Closed @ `8686e68`. Overnight calendar-blind residual stays in **LP-01 / F15** — do not treat this close as overnight-session proof.
- [x] **ML-META-JSON-VERIFICATION-ASYMMETRY** — `_load_lstm` verifies `lstm_*_meta.json` (presence + Item-4 manifest hash) before `lstm_model.load_lstm` reads it, matching `xgb_meta` / `transformer_meta`. Closed @ `a107412` (PR #55 merge `bc1e078`). Tests: `tests/test_model_contract_enforcement.py`. Slim-ledger cite `7ec0bf6` was the pre-rebase feature SHA and is not on `main`.
- [ ] **QUALITY_CIRCLE_SIGNAL_REFINEMENT_V1** — ENABLED / NOT_STARTED (operator 2026-07-09) — DEPENDS ON DAILY_SCOREBOARD_DENOMINATOR_FIRST_V1: input layer VALID as of `06a3f9e8e73811d61364b2829ff462d7b90474de`. Continuous signal-refinement loop consumes the denominator-first scoreboard as measurement substrate. Boundary (binding): the scoreboard identifies weak tickers/horizons/coverage gaps; it does NOT itself approve model or signal-rule changes.
- [ ] **STAGE-2 Target/label foundation** — continue `docs/stage1_target_label_foundation/` Stage 2: retire the confirmed placeholder thresholds and design the governed target so scoreboard accuracy becomes decision-valid. Preregistered protocol; no outcome mining.
- [ ] **ML-PIPE-V1 predictive-validity closeout** — operator-host shuffled-label runs on real capture data per model-family×horizon, then a clean governed retrain, then per-ticker/per-horizon validity classification. Until then the standing NOT_PROVEN verdict holds.
- [ ] **SIG-01 scoreboard/actionability accrual** — sessions 2–5 of segmented multi-day evidence toward signal-outcome validation; logger ~32 tickers, snapshot rows landing all session.
- [ ] **ECON-01 residual — calibration-version pinning** — replay/serve pins the exact calibration version used, with no silent drift. Parent denominator defect closed @ `e400570` (board `6c29a7f` on `main`); these four residuals remain.
- [ ] **ECON-01 residual — purged/embargo execution** — the purged/embargoed walk-forward is actually executed in the replay-context path, not merely specified
- [ ] **ECON-01 residual — LSTM/Transformer point-in-time windowing** — the broader sequence-model point-in-time windowing carries no lookahead across replay/backfill
- [ ] **ECON-01 residual — RTH producer-guard observation** — the RTH producer-guard observed live doing its job on the replay-context path
- [ ] **OPS-OPERABLE-SURFACE-JOB** — the daily terrain scorecard (15:30 CT) AND the recurring Collect job registered as operator-visible host tasks in `governance/host_scheduled_jobs.md`, with the durable operable-surface gate green
- [ ] **MODEL-04 stale-model serving policy** — the serve/unserve/retrain policy for pre-correctness bundles (ten tickers on 2026-04-30 vintages; guests via governed anchors) decided and recorded (operator decision, currently held)
- [ ] **UI-EXPLAIN orphan payload surfaces** — `pred_headline` rendered to the explanation rail and `reversal_risk`/`reversal_label` rendered as a paired risk chip, closing with rendered DOM + universal RTH runtime proof for every dispositioned field
- [ ] **GAMMA-INTRADAY-CADENCE** — the live intraday gamma product refreshes the WIDE chain periodically (≈5–15 min) on a separate low-priority track, decoupled from the per-cycle 20-strike UI fetch (sequenced after FP-64 proves the morning hypothesis)
- [ ] **LEVELS-SELF-DECLARE-TRUST** — every displayed level self-declares `TRUSTED` only when its finite correctness contract (sanitized greeks · single `compute_exposures_by_strike` source · canonical method · full strike coverage · near-term expiries · fresh chain) holds, else `LOW_CONFIDENCE_NARROW_CHAIN` / `STALE` / `UNSANITIZED`, surfaced in the Key Levels UI and gated by one test asserting the flag derives from input quality
- [ ] **SCOREBOARD-ECONOMIC-REWORK** — change the scoreboard metric from direction-accuracy-vs-placeholder to dollars-after-costs of the gamma-conditioned strategy, per regime (fp_levelset F2). Historical prose only until this row. Does not itself admit anything to TRADE.
- [ ] **MODEL-STACK MSD-001..005** — five CONFIRMED_DEFECT items in `reports/MODEL_STACK_IMPLEMENTATION_AND_PREDICTIVE_VALIDITY_AUDIT_V1.md` (vix_direction/vix_vs_prev parity, native vol semantics, 5c hardcoded isotonic, 5c meta bypass, net_vanna=None) each fixed or killed with a SHA + test. Report is evidence, not a second queue.
- [ ] **REAL-GATE:VOL-CTX-SINGLE-SOURCE** — cache `"vix"` + `vix_bucket` raw reads retired or governed; report claimed this row existed on OPEN_ITEMS and it did not. Home is this checkbox. Source: `reports/VOLATILITY_V1_CRASH_RECOVERY_SCOPE_RECONSTRUCTION_AND_ACCEPTANCE_REPROOF.md`.
- [ ] **CHAIN-OF-TRUST / TraceableDerivation** — 290 consumer reads without producer link (`governance/CHAIN_OF_TRUST_GAP_INTEL_290.md`) classified; every MATERIAL_TECHNICAL gap mapped here or to an existing F/RC row. Do not open a 290-box program.
- [ ] **ISSUE-19 $SPX 190-row forward-grid** — dense forward 1m at the documented hole filled or the 190 `pin_neutral` / `outcome_filled=0` rows dispositioned. Parent homes stay FIND-LABEL-INTEGRITY-FORENSICS / F25 / STAGE-2. Source: `docs/issue19_post_rehydration_eligibility_audit.md`.
- [ ] **A1/A2 residual gaps** — leftover named gaps in the A1 conformal/isotonic and A2 lifecycle contracts (calendar freshness / multi-exchange / extended hours; conformal scheduler; ml_predict↔v2 bridge) either closed with SHA or classified NOT_MATERIAL. Contracts stay contracts, not a second queue.
- [ ] **EXPOSURE-CONFLUENCE-CUBE** — one stamp, one walk: per-strike **GEX + DEX + VEX + CHEX + ΔOI + EM + value (POC/VAH/VAL)** from `compute_exposures_by_strike` / existing morning-full OI. DEX and `net_delta` already exist; ΔOI is computable from stored `openInterest` (DIR-01 b). Missing ≠ 0.0. This is Collect / one-faucet work, not a signal. Does not admit TRADE. Sequenced after PA-2’s single walk is the only live producer.
- [ ] **ΔOI-PER-STRIKE** — day-over-day open-interest change per strike from `option_chain_morning_full` (already on disk). Distinguishes a wall forming from a wall dissolving. Collect-side derivation; Chart yellow-bar meaning, not a new paint. Home for DIR-01(b) so it is not only historical prose.
- [ ] **TRUE-VANNA-VEX** — replace the labeled vega/(S·iv) proxy with true vanna / VEX on the cube, or keep the proxy forever and never call it vanna. UI-04 P1B closed the *label*; this row is the exposure. Charm vote stays UNAPPROVED until its own proof. Not TRADE.
- [ ] **EXPIRY-STACK-VIEW** — operator can read 0DTE / this week / monthly / all from the **same** cube without a second producer. AFTER EXPOSURE-CONFLUENCE-CUBE and PA-2. Do not build expiry filters on three faucets.
- [ ] **NO-OPTIONS-TAPE** — standing constraint, not a feature. Schwab carries **no options trade prints**; Alpaca IEX is equities only. Kill any HIRO / per-trade quote-rule / tape clone before it is built. Interval Δ`totalVolume` vs bid/ask at snapshot bounds is the honest weak substitute (DIR-01 c). Anyone proposing prints must name the feed first.
- [ ] **UX-WORLD-CLASS-CONSOLE** — **AFTER (all must be `[x]` or PASS):** PA-2 `ONE_FAUCET_STATUS = PASS`, PA-36 `OPERATOR_TRUTH_STATUS = PASS`, RC-292 closed, F15 closed, LEVELS-SELF-DECLARE-TRUST closed. **THEN** Chart + Console get the bells and whistles: one KEY LEVELS / exposure card (no greeks tabs), Chart PIN labeled for the bound semantic, value levels on Chart/Console (F15/LP-01), expiry stack, trust chips, GEX+DEX+VEX+CHEX+ΔOI+EM+value on one surface, six-pill lock stays (`tests/test_issue18_ui_contract.py`), no resurrected surfaces, no options tape. PHASE-5 (repo directories) is a different row and may run earlier. This row is **look-and-feel + layout only after the number is true**. Predictive validity stays NOT_PROVEN; nothing here admits TRADE.

## OPEN ROOT-CAUSE LEDGER DENOMINATOR
> Technical state preservation only — do NOT turn this into process work. `governance/root_cause_log.md` was **absent from `main`**. Restored 2026-08-13 from `a2b5112` (feature/cf-one-faucet-land-f32-rc328). Last measurable table on that blob = **64 OPEN / 229 CLOSED**. The 2026-08-12 count of **72 OPEN / 55 past due** cannot be re-verified — that file never reached `main`. Do not infer 8 closes from the difference. If an OPEN RC proves a real technical defect, fix it; if it proves already technically fixed, verify and close with evidence; if non-material/process-only, classify it and move on.
- [ ] Enumerate every currently OPEN RC row in `governance/root_cause_log.md`
- [ ] Record current measured OPEN RC denominator (= 64 as of restored `a2b5112`; prior 72 count UNVERIFIED)
- [ ] Recompute denominator when the ledger changes
- [ ] Classify each OPEN RC into exactly one category (MATERIAL_TECHNICAL, DUPLICATE_CHILD, SUPERSEDED_WITH_EVIDENCE, STALE_LEDGER_AFTER_PROVEN_FIX, PROCESS_ONLY, EXTERNAL_BOUNDARY, NOT_PROVEN)
- [ ] Every MATERIAL_TECHNICAL RC appears explicitly on this Project A master board
- [ ] Every MATERIAL_TECHNICAL RC has semantic/title recorded
- [ ] Every MATERIAL_TECHNICAL RC has live/train/serve/replay/backfill applicability recorded
- [ ] Every MATERIAL_TECHNICAL RC has decision-path impact recorded
- [ ] Every MATERIAL_TECHNICAL RC has universality status
- [ ] Every MATERIAL_TECHNICAL RC is searched
- [ ] Every MATERIAL_TECHNICAL RC is proved
- [ ] Every MATERIAL_TECHNICAL RC is fixed
- [ ] Every MATERIAL_TECHNICAL RC is tested
- [ ] Every stale OPEN RC whose code is actually fixed is reconciled with exact evidence
- [ ] No stale ledger row remains OPEN merely because no one updated the ledger
- [ ] No code-only fix is called CLOSED while the governing RC remains materially unresolved
- [ ] No parent RC closes while a material child remains open
- [ ] No material RC is hidden solely inside a summary string
- [ ] No material RC is omitted because a different F-row "sounds similar"
- [ ] No material technical defect disappears because it belongs to another historical numbering system
- [ ] OPEN material technical RC count = 0 before Project A closure

## EXISTING REPO WORK-ITEM SYSTEM RECONCILIATION
> These identifiers are DISTINCT namespaces. Do NOT conflate them with canonical Project A F01–F42. Keep this reconciliation LIGHT — no registries, crosswalk DBs, YAML/JSON mirrors, CI, parsers, or governance frameworks. A simple checklist here is enough. Namespaces: (1) unpadded **F1/F2/F3** = Find & Prove system (`reports/fp_levelset_directive_for_cursor.md`, also referenced in this OPEN_ITEMS.md); (2) hyphenated **F-01…** = Desk audit findings (`reports/cursor_desk_audit_v1.md`); (3) **RH-F1…RH-F8** = rehab facets (`governance/REHAB_PROGRAM.md`).
- [ ] Unpadded F1/F2/F3 Find & Prove items reviewed
- [ ] Hyphenated F-01… Desk audit findings reviewed
- [ ] RH-F1…RH-F8 rehab facets reviewed
- [ ] Existing OPEN_ITEMS.md Find & Prove references reviewed
- [ ] Existing OPEN_ITEMS.md GEX-F2 references reviewed
- [ ] Every unresolved MATERIAL TECHNICAL item from those systems mapped onto this Project A master board
- [ ] Original source ID preserved when mapped
- [ ] Duplicate semantic mapped without duplicating engineering work
- [ ] A closed item in another system is not assumed closed here without evidence
- [ ] An OPEN material item in another system cannot be ignored because it lacks a canonical F01–F42 ID
- [ ] No technical work remains hidden only in reports/directives/rehab files
- [ ] No numbering collision causes one item to overwrite another
- [ ] Universality requirements apply to imported material technical items
- [ ] Parent Project A cannot close while a materially applicable imported item remains unresolved

### 2026-08-13 land onto main (RECONCILIATION — not a second queue)
> Maps the competing slim `main` ledger and the 2026-08-13 KEY LEVELS paint stack onto this board. Does not create a fourth list. Does not close PA-2 / F42 / ONE_FAUCET / PA-36 / RC-292 from paint.

- **Canonical file** is this board (from `origin/cursor/project-a-board-audit` @ `0e93624`). Slim `main` `OPEN_ITEMS.md` (~63 lines, last rewritten 2026-07-16) is superseded as a competing "now."
- **`ACTIVE_PROGRAM.md`** is a pointer: now = PA-46. Charter remains `AGENTS.md`. Locks table stays.
- **Slim leftovers already on PA-48 (do not add a second row):** RECON-02, PHASE-4, PHASE-5, FIND-SCHWAB-WORKER-LEAK, FIND-LABEL-INTEGRITY-FORENSICS, SCOREBOARD-TARGET-TRUTH Lane A/B, UI-01, UI-05, UI-04 P1B/P1C, ECON-01 residuals, MODEL-04, BUILD-IDENTITY, GOV-REMOTE-ENFORCEMENT, UI-EXPLAIN, OPS-OPERABLE-SURFACE-JOB, DIR-01, GAMMA-INTRADAY-CADENCE, LEVELS-SELF-DECLARE-TRUST, FIND-LIVE-FLIP-WIDE-CHAIN / FIND-GAMMA-FULLCHAIN.
- **FIND-SCHEDULED-JOBS-VISIBILITY** — inventory already exists (`governance/host_scheduled_jobs.md`, historical close 2026-07-27). Remaining host-task registration lives under **OPS-OPERABLE-SURFACE-JOB**. Slim `main` still showed this `[ ]` because that ledger predates the inventory close. Do not add a second closable row.
- **STATUS_CHANGE this land:** UI-01 @ `bc1b635`; PHASE-4 @ `e009aa2`; UI-04 P1B + P1C @ `29ea1e4`.
- **STATUS_CHANGE 2026-08-13 RC-292 children (not the parent):** UI label + tooltip + behavioral/mutation lock @ `0e304f6`. Parent RC-292 / persisted `gamma_pin` stay `[ ]`.
- **STATUS_CHANGE 2026-08-14 RC-292 `pin_score`:** intended semantic recovered @ `6d14ee2` (`gex_at_bound_pin_strike` = `|net GEX$|`). Parent stays `[ ]`.
- **STATUS_CHANGE 2026-08-14 RC-292 persist + migration:** `d71bb5e`. Parent / universality / runtime stay `[ ]`.
- **STATUS_CHANGE 2026-08-14 RC-292 normalized stamp:** `053251e` (Issue 16: `snapshots_1m_normalized` ALTER). Parent / universality / runtime stay `[ ]`. `[x]` count unchanged.
- **STATUS_CHANGE 2026-08-14 RC-285 write sites:** `1117f19`. Five children `[x]`; parent / universality stay `[ ]`. `[x]` 12 → 17.
- **STATUS_CHANGE 2026-08-14 five-zone pass:** RC-301 except-literal @ `5d68d93`; F15 math one-producer @ `462a581`; RC-297 MEGA2 lock @ `8ca1f18`; RC-329 `kl_gamma_pin` consumer bind @ `bb85651`. Parents stay `[ ]`. `[x]` 17 → 35.
- **STATUS_CHANGE 2026-08-14 five-zone adversarial REOPEN:** operator audit @ `8ccddb17`. RC-285 Fix/Proof reopened (accuracy-as-edge). F15 "no alternate population" reopened (two input contracts). RC-297 Fix/Proof reopened (dormant guard). RC-329 Fix/Proof reopened (two-copy bind). RC-301 except-literal children stay `[x]`; uncovered shapes filed as RC-318. `[x]` 35 → 28. No new `[x]` until acceptance is measured on `origin/main`.
- **STATUS_CHANGE 2026-08-14 defect-learning class plants:** `a83219a` — uncited-instance plants now fail for hardcoded `kl_*` label, undelegated `*volume_profile*`, measurement-`*_key` literal fallback, uninventoried `*_engine.py`, and except-literal `-> float`. Charter sentence in `AGENTS.md`. No new `[x]`. Parents stay OPEN.
- **STATUS_CHANGE 2026-08-14 no example-locking:** `132c238` — detectors moved off observed tokens (`kl_` prefix, `volume_profile` name, `*_key` suffix, `*_engine.py` suffix, `return 0.0` Constant). Plants now use `structural_unlisted`, `_value_area_from_closes`, `requested`/`field`, `engine_core.py`, `return float(0)`. Version-key miss no longer substitutes `model_version`. No new `[x]`. Parents stay OPEN.
- **STATUS_CHANGE 2026-08-14 five-zone re-audit:** `c869521` — F15 fusion proxy reverted (RC-330). Checkbox `[x]` rows: origin/main 35 → this branch 28 (seven reopens, zero new checkbox closes). Raw string `[x]` rose 58 → 60 at `d3e2f51` because STATUS_CHANGE prose mentioned the token, not because boxes were checked. No new checkbox `[x]`. Pin-fix rebase remains OPEN. Parents stay OPEN.
- **ADD then STATUS_CHANGE this land:** UI-04 P1D @ `8686e68` (overnight residual stays LP-01 / F15); ML-META-JSON-VERIFICATION-ASYMMETRY @ `a107412` (PR #55; slim cite `7ec0bf6` was the pre-rebase feature SHA, not on `main`).
- **ADD this land (historical Find & Prove had them; PA-48 did not):** QUALITY_CIRCLE_SIGNAL_REFINEMENT_V1, STAGE-2, ML-PIPE-V1, SIG-01.
- **KEY LEVELS / B_light paint on `main` (PRs #53–#58 merged; #59 SUPERSEDED do-not-merge; #60 cube-honesty for charm/vanna only) does not close PA-2 / F42 / ONE_FAUCET / PA-36 / RC-292.** Paint ≠ one faucet. Charm vote stays UNAPPROVED. Predictive validity stays NOT_PROVEN.
- **`origin/feature/cf-one-faucet-land-f32-rc328`** remains the F32/RC-328 code branch. It is not this ledger PR and is not closed by KEY LEVELS paint.

### 2026-08-13 discovery — documented rehab record (RECONCILIATION)

**How to read `OPEN_ITEMS.md` (so 1125 boxes are not 1125 jobs):**

| What you are looking at | Count | What it is |
|---|---|---|
| `[ ]` checkboxes on this board | ~1125 | Mostly **parent acceptance criteria** (PA-1..PA-47). Close only with an exact SHA. |
| `[x]` on this board | 28 checkbox rows | origin/main had 35 checkbox `[x]` rows (raw string `[x]` = 58 because prose cites the token). This branch: 28 checkbox rows, 0 new checkbox closes, 7 reopens. Raw string `[x]` can rise when STATUS_CHANGE prose mentions the token — that is not a close. |
| F01–F42 labeled CLOSED_WITH_EVIDENCE but still `[ ]` | most of PA-3 | Prior program called them closed; this board's closure rule requires a SHA on the row. **Do not re-do the work from the label. Do not `[x]` without the SHA.** |
| **PA-46** | 16 pointers | **The execution queue.** Status derives from the canonical F/RC/PA rows. |
| **PA-48 still `[ ]`** | 41 | Leftover atomic work, including second-census ADDs and the 2026-08-13 product/UX rows. UX-WORLD-CLASS-CONSOLE is gated AFTER X. |
| LEGACY / HISTORICAL bullets | many | History only. Not closable. Work they name lives in PA-48 / F15 / F31. |

**Error logs / other logs in this workspace:**

- **No `*.log` files** and no `logs/` directory are tracked. Host job logs (`reports/scorecard_run.log`, stream-capture status) are gitignored; they live on the operator host.
- The defect log is `governance/root_cause_log.md` (restored; 64 OPEN). That is the "error log" the rehab program actually kept.
- `governance/audits/repo_sweep_error_propagation_v1..v3_202605*.json` — May 2026 completed silent-exception sweeps (archive; 27→0). Not a forward queue.
- `reports/ci/ci_nonblocking_failure_triage_2026-06-18.md` — June pytest-full matrix. SUPERSEDED as a queue; evidence only.
- `reports/rehab_latest.md` and `tools/rehab_daily_scan.py` — **still absent**. REHAB_PROGRAM named them as queue authority; they never landed on `main`. Do not invent them. Queue authority is PA-46.

**Source files the board cited that were missing from `main` — restored this land (SOURCE NAMESPACE banners, not a second now):**

| File | Restored from | Still applies? |
|---|---|---|
| `governance/root_cause_log.md` | `a2b5112` | **Yes** as the defect log. 64 OPEN. Material technical RCs already on PA-4 (RC-292/282/285/297/301/318/328/329). Remainder is PA-41/RC-denominator work — classify, do not start a second RC program. |
| `governance/REHAB_PROGRAM.md` | `7ab5e0c` | **Facets still apply; file is not the default program.** RH-F1 = PA-2 one faucet. RH-F2..F8 map to PA-36 / Collect / Decide / institutional lock. |
| `governance/host_scheduled_jobs.md` | `76b6c0e` | **Yes** as inventory. Last host reading on the file (2026-08-04) showed Last Result **3221225786** (terminated) on all three Ed tasks — OPS-OPERABLE-SURFACE-JOB still open. |
| `reports/fp_levelset_directive_for_cursor.md` | `f6efeeb` | **Premise still applies** (wrong objective / placeholder target). Direction-label studies stay paused. Work homes: STAGE-2, ML-PIPE-V1, FIND-LABEL-INTEGRITY, SCOREBOARD-TARGET-TRUTH. |
| `reports/cursor_desk_audit_v1.md` | `4bd9c5f` | **One 2026-08-06 report**, not a standing queue. Material leftovers (bitemporality, weekend RTH, Desk SLA) go through PA-41 if still live — do not re-open a Desk program. |
| `reports/institutional_debt_inventory.md` | `f6efeeb` | **Advisory snapshot (July 19).** Worst file still `server.py`. PHASE-5 / institutional lock. Regenerate; do not treat 2804 as current. |
| `governance/unproven_register.md` | `8f6467f` | **Yes** as the claims-about-the-world register (boundary vs root_cause). Not a defect queue. |

**Competing docs that still looked like "now" — SUPERSEDED banners added; they do not still apply as queues:**

- `docs/OPEN_ITEMS_OPERATOR_TRUST.md` + `governance/OPERATOR_TRUST_STABILIZATION_GATE.json` + June RTH runbooks — June 2026 operator-trust stack. Overlap: UI-05, PA-36, card fidelity NOT_PROVEN. Do not run the June "next step = resolve_pytest_full_failures" ladder.
- `docs/plans/TRAINING_PIPELINE_AUTOMATION_PLAN.md` — PR5–PR7 / auto-promote. Maps to PA-16 / PA-35 if still live. Do not enable `ED_SCHEDULER_AUTO_PROMOTE`.
- `docs/plans/GOVERNANCE_CONSOLIDATION_EXECUTION_PLAN.md` — claimed authority until ACTIVE_PROGRAM Phase 1a. That sentence is false as of this pointer rewrite.
- `governance/STACK_WIRING_INTEGRITY_MAP.md` — May STACK-WIRE rider. One-faucet work is PA-2 / F-series, not a wiring-map program.
- `governance/SCHWAB_DERIVED_FIELD_REPLACEMENT_REGISTER_V1.md` — May Schwab-first register. Collect law still holds; not a second remediation program.
- `governance/ACTIVE_DIRECTORY_WRITER_INVENTORY.md` / `governance/COVERAGE_JUSTIFICATION.md` — G4 / I-01..I-22. Map to PA-16 / PA-42 if material; not current queues.
- `docs/issue19_*.md` — pin_neutral / `$SPX` / bar path. Homes: FIND-LABEL-INTEGRITY-FORENSICS, F25, STAGE-2. Not a third Issue-19 program.

**PA-48 leftovers — do they still apply?**

| Still applies (do the work) | Operator-held / external (not agent-closable) | Do not treat as a second program |
|---|---|---|
| FIND-SCHWAB-WORKER-LEAK, FIND-LIVE-FLIP-WIDE-CHAIN, WING-IV, FIND-GAMMA-FULLCHAIN, FIND-SNAPSHOT-BAR-STAMP, UI-05, AUDIT-TAPE-OVERFLOW, OPS-PLAYWRIGHT-E2E-RERUN, FIND-LABEL-INTEGRITY-FORENSICS, SCOREBOARD-TARGET-TRUTH A/B, QUALITY_CIRCLE, STAGE-2, ML-PIPE-V1, SIG-01, ECON-01 residuals, OPS-OPERABLE-SURFACE-JOB, UI-EXPLAIN, GAMMA-INTRADAY-CADENCE, LEVELS-SELF-DECLARE-TRUST, PHASE-5 (after this is the only list) | GOV-REMOTE-ENFORCEMENT, BUILD-IDENTITY, RECON-02 (purge word), MODEL-04, DIR-01 (nothing to Chart until placebo) | RH-F1..F8, Desk F-01…, June operator-trust, training PR5–PR7 as a named program, STACK-WIRE, Schwab derived-field register, Issue 19 folder |

**What we do next (unchanged):** execute **PA-46**. Do not start PHASE-5 or a UI redesign in this land. Do not close PA-2 / F42 / ONE_FAUCET / PA-36 / RC-292 from paint.

### 2026-08-13 second census — not 100%, no second canonical file

> Honest limit: a full Read of every `governance/` and `reports/` file was not completed. This pass grepped the live (non-archive) set and read the files that still looked like queues. That is **not** proof that nothing else is hiding in archive, artifacts JSON, or `docs/issue19_*` bodies. PA-41 (discovery denominator) stays open for that reason.

**Do not create a second canonical file for governance/reports.** Those directories are source/evidence. Outstanding *work* lands here as ADD. Creating `GOVERNANCE_CANONICAL.md` / `REPORTS_BOARD.md` would be a fourth list.

**Completed items — proof pass (STATUS_CHANGE only where `main` has the SHA):**

| Row | Proof on `main` | Action |
|---|---|---|
| UI-01, PHASE-4, UI-04 P1B/P1C/P1D, ML-META | SHAs already on the `[x]` rows | already `[x]` |
| RC-292 UI label + tooltip + mutation lock | `0e304f6` | three children `[x]`; parent stays `[ ]` |
| RC-292 `pin_score` | `6d14ee2` | child `[x]`; parent stays `[ ]` |
| RC-292 persist + migration | `d71bb5e` + `053251e` | two children `[x]`; parent stays `[ ]` |
| RC-285 write-site fabricated zero | `1117f19` | three children `[x]` (semantic/live/root); Fix/Proof REOPENED (accuracy-as-edge) |
| RC-301 except-literal sites + gate | `5d68d93` | five children `[x]`; CLASS / parent / RC-318 stay `[ ]` |
| F15 one POC math producer | `462a581` | two children `[x]` (semantic + mutation); no-alternate REOPENED |
| RC-297 MEGA2 file-set lock | `8ca1f18` | three children `[x]` (semantic/live/root); Fix/Proof REOPENED (dormant guard) |
| RC-329 `kl_gamma_pin` consumer bind | `bb85651` | three children `[x]` (semantic/live/root); Fix/Proof REOPENED (two-copy) |
| UI-05 cold SLA | `6a74331` / `5506185` | recorded on the row; checkbox stays `[ ]` (RTH burst remains) |
| ECON-01 parent denominator | `e400570` / `6c29a7f` | recorded on the residual rows; four residuals stay `[ ]` |
| F01–F42 labeled CLOSED_WITH_EVIDENCE | **no SHA on any F-row; `git log --all --grep=RC-344` (and RC-339/342/340/343) is empty** | stay `[ ]`. The 2026-08-12 freeze unchecked 37 non-SHA `[x]`. Do not put the check back. |
| SCOREBOARD-TARGET-TRUTH Lane A | scoreboard v3 @ `06a3f9e`; no v4 close SHA found | stay `[ ]` |
| QUALITY_CIRCLE | `06a3f9e` is the *dependency*, not the refinement loop | stay `[ ]` ENABLED / NOT_STARTED |

**ADD this census (material leftovers that had no PA-48 home):** SCOREBOARD-ECONOMIC-REWORK, MODEL-STACK MSD-001..005, REAL-GATE:VOL-CTX-SINGLE-SOURCE, CHAIN-OF-TRUST / TraceableDerivation, ISSUE-19 $SPX 190-row forward-grid, A1/A2 residual gaps.

**ADD 2026-08-13 product/UX (operator: roadmap must name the later bells-and-whistles, and what data a world-class exposure console actually uses):** EXPOSURE-CONFLUENCE-CUBE, ΔOI-PER-STRIKE, TRUE-VANNA-VEX, EXPIRY-STACK-VIEW, NO-OPTIONS-TAPE, UX-WORLD-CLASS-CONSOLE. UX is **NOT NOW** — AFTER PA-2 + PA-36 + RC-292 + F15 + LEVELS-SELF-DECLARE-TRUST. Research basis (not edge claims): dealer-positioning consoles that work are GEX+DEX+VEX+CHEX plus walls/flip/pin, expiry stack, and value levels — not gamma alone (SpotGamma TRACE/HIRO/charm-delta; FlashAlpha GEX/DEX/VEX/CHEX; Gamma Sonar pressure-field stack). We already have the math for GEX/DEX/charm and morning-full OI; we do **not** have options prints. Nothing in this ADD admits TRADE.

**Not added (evidence only, or already parented):** PRODUCTION_CLAIMS_REGISTER, TRADE_IMPACTING_ROUTE_INVENTORY, PILOT_1B, FULL_PRIMARY_HORIZON audit snapshot, FIELD_SOURCE / SCHWAB normalization audits, INF-1..4 transition policy (deferred; not a new program), unproven_register individual studies (register exists), ADMIN_BYPASS June CI triage, derived-analytics scaffolds (unadmitted Decide-adjacent).
