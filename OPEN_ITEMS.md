# Open items — ACCEPTANCE SPECIFICATION (what "done" means), nothing else

**This file owns ONE responsibility: the product/engineering acceptance specification** — the
top-level acceptance verdicts, the still-unmet acceptance items, the candidate product directions
under discussion, the validity protocol studies must pass, and the PA-1..PA-47 acceptance board.
Its checkboxes define done; nothing mechanical schedules from them and no agent self-assigns from
them (RC-520 authority collapse, 2026-09-05).

**Where the other responsibilities live (each has exactly one owner):** engineering law →
`AGENTS.md`; target architecture → `docs/ARCHITECTURE.md`; current operator-directed work →
`ACTIVE_PROGRAM.md`; defects being driven to root, with clocks → `governance/root_cause_log.md`;
claims about the world → `governance/unproven_register.md`; operator decisions production
consumes → `governance/OPERATOR_DECISION_REGISTER.md`; parent/sub-lane closure integrity →
`governance/INSTITUTIONAL_CLOSURE_SCHEMA.json`; agent procedure →
`governance/AGENT_OPERATING_PROCESS_V1.md`. An unmet item below that is a DEFECT under active
repair also has a ledger row; the criterion here says what must hold, the row says how it is being
fixed. History lives in git.

---

## Top-level acceptance verdicts (change these only with evidence)

| Fact | Status |
|---|---|
| Predictive validity (any horizon beats chance, OOS, net of costs) | **NOT_PROVEN** — 2026-06-01 gate verdict stands |
| Real-money readiness | **NOT_APPROVED** |
| Decision-path admission registry (`config/decision_path_admissions.json`) | **BUILT_EMPTY** — gate live in `call_engine.compute_call` via `decision_gate.py`; nothing admitted; directional calls force WAIT (running server picks this up on its next restart) |
| Card fidelity overall / universal runtime live proof | **NOT_PROVEN** |
| FP-03..FP-25 battery + LP-01 levels verdicts (kills AND signals) | **ERA-CONTAMINATED — not citable either direction until re-run under the clean protocol (operator 2026-08-01; see Validity notes below)** |


---

## Open acceptance items (unmet; each survives exactly once, here)

Rows moved from the former Now / FINDs / queue / audit-remainder / defects sections on 2026-09-05;
closed rows were removed (git history). A row that is pure WORK moved to `ACTIVE_PROGRAM.md`.

- [ ] **FIND-SCHWAB-WORKER-LEAK** — `schwab-py` (via `multiprocess`) leaks spawn workers: 15 orphaned Python processes accumulated from scheduled runs before the 2026-07-16 kill; RE-OBSERVED 2026-07-20 — 13 live `multiprocess.spawn` zombies from Jul 17–18 (~39 CPU-s each, PIDs in Cursor's audit); kill after confirming no parent trainer, then the root fix below. Root cause: Schwab client processes not shut down cleanly at end of scheduled jobs. Fix direction: explicit client close/terminate in the scheduled entry points (scoreboard/backfill runners), then observe zero orphans across a week of scheduled runs.
- [ ] **GAMMA-INTRADAY-CADENCE-V1** (product-stage, NOT for the morning-regime screen) — gamma levels (flip/pin/walls/net_gamma) change intraday as spot moves, 0DTE decays, and OI shifts. The once-daily `option_chain_morning_full` capture is correct for the GEX-R1 morning-regime hypothesis (set stance at open), but a live intraday gamma product needs the WIDE chain refreshed periodically (e.g. every 5–15 min) on a separate low-priority track, decoupled from the per-cycle 20-strike UI fetch. Note: the app ALREADY computes per-snapshot narrow-chain levels every cycle — so intraday levels exist but are narrow/untrustworthy until FIND-GAMMA-FULLCHAIN-STRIKES + sanitization + flip-method land. Sequence AFTER FP-64 proves the morning hypothesis pays; do not scope into tonight.
- [ ] **FIND-LIVE-FLIP-WIDE-CHAIN-V1** (the UI flip is still wrong even after Fix 3) — verified 2026-07-17: `option_chain_morning_full` (wide capture) is **write-only research** — nothing reads it — and the LIVE level compute (`compute_exposures_by_strike`) still runs on the per-cycle 20-strike chain. So the Gamma Flip (and walls/pin) shown ON THE UI stay narrow-limited even after the wide morning capture works. To make the DISPLAYED flip correct, a wide chain must feed the live level compute (periodic wide fetch → live exposures), overlapping GAMMA-INTRADAY-CADENCE-V1. Until then: research/backtest flip can be correct (from the wide table) while the UI flip is not. **ALSO IN SCOPE (2026-07-26, RC-43 reopened): WING-IV TREATMENT.** MEASURED (`python tools/flip_iv_sensitivity_v1.py`, 173 wide chains): the flip's IV sensitivity is almost entirely in the wings — flattening only |moneyness|>3% moves the flip a median **0.3627% of spot** (max 3.80) vs **0.0144%** for near-ATM-only (93.6% within 0.1%). Raw vendor IV is least reliable exactly there, so a wide-chain flip inherits wing-IV noise. Sequenced, NOT a now-task: first validate against an EXTERNAL flip (operator has Barchart access) on a date with a morning wide capture; if a smoothed-wing flip lands closer to Barchart than raw per-strike, wing smoothing is a proven accuracy fix and ships with the wide-chain live compute. Bounding caveat: the measured figures come from aggressive FLATTENINGS, which over-state a real smoothed-surface difference.
- [ ] **CHECK: levels self-declare trust** (a check registered under the ONE Institutional Correctness gate — NOT its own lock). The finite correctness contract every level must meet: (1) sanitized greeks [DONE], (2) single source of truth = one `compute_exposures_by_strike` [TRUE, verified server.py:6083 — all of flip/pin/walls/HVL/max_pain/net_gex/voids derive from it; EM is a separate IV band by design], (3) canonical methods [flip cumulative DONE], (4) full strike coverage to negligible OI/gamma [research Fix 3; live pending FIND-LIVE-FLIP-WIDE-CHAIN], (5) near-term expiries [≤37d], (6) chain fresh. Mechanical lock: each level self-declares `TRUSTED` only if 1–6 hold, else `LOW_CONFIDENCE_NARROW_CHAIN` / `STALE` / `UNSANITIZED`, surfaced in the Key Levels UI (dim/badge) and gated by ONE test asserting the flag derives from input quality. Flip self-declares LOW_CONFIDENCE until FIND-LIVE-FLIP-WIDE-CHAIN lands. This benchmark IS the anti-churn: a bounded checklist, not open-ended.
- [ ] **SCOREBOARD-TARGET-TRUTH SCOREBOARD_SEMANTICS_TARGET_TRUTH_AND_60C_ROOT_CAUSE_FORENSIC_V1** — two separate lanes (branch `scoreboard-target-truth-60c-forensic-v1`). Lane A (scoreboard schema v4, operator-semantic safety: trade-decision ALL card, confusion matrices, baselines, fail-closed accuracy presentation, invalid-threshold exclusion) contains HEAD backfill behavior only — no identity-first attachment code is part of the Lane-A package. Lane B (identity-first outcome attachment, `calibration/backfill_outcomes.py` + tests) is NOT in the Lane-A patch — it exists only as uncommitted worktree design; LANE B COMMIT_READY = NO (requires the separate data-impact mission: compound identity, production-copy reconciliation, old-vs-new weights/decisions, migration/rollback, RTH proof). Forensic packet: `reports/scoreboard_forensic/july13_2026_target_truth_forensic.json` — LEGACY_PLACEHOLDER_THRESHOLD CONFIRMED (100% of labeled July-13 rows; 60c threshold spans 0.86–416 bps of spot); target redesign OPEN via the preregistered research protocol.
- [ ] **QUALITY_CIRCLE_SIGNAL_REFINEMENT_V1** — ENABLED / NOT_STARTED (operator 2026-07-09) — DEPENDS ON DAILY_SCOREBOARD_DENOMINATOR_FIRST_V1: input layer VALID as of `06a3f9e8e73811d61364b2829ff462d7b90474de`. The continuous signal-refinement loop consumes the denominator-first scoreboard (eligible grid + quality_circle section) as its measurement substrate. Boundary (binding): the scoreboard identifies weak tickers/horizons/coverage gaps; it does NOT itself approve model or signal-rule changes — any refinement requires a separate audited lane.
- [ ] **AUDIT-TAPE-OVERFLOW-SHORT-VIEWPORTS** — at 1440×810 the ALERT TAPE tile overflows 30px and at 1366×768 44px (scrollable, not clipped-blind, but the operator wants visible data); radar rail scrolling is intended-by-design and stays. Fix: short-height media query slims tape row padding/font or caps visible entries with a count badge.
- [ ] **AUDIT-CEILING-NARROW-VERDICT-UNOBSERVED** — a ticker needing >TERRAIN_STRIKE_COUNT_MAX(=100) strikes must fetch the ceiling and report LOW_CONFIDENCE_NARROW_CHAIN. UNOBSERVED: $SPX, the only current >100-need ticker, is UNAVAILABLE via empty profile (RC-11 — no contract with OI+plausible gamma) so it never reaches the span verdict. Closes when a >100-need ticker WITH usable greeks is observed reporting NARROW off a live cycle, or a governed synthetic-free test drives the endpoint with a real wide chain truncated to 100.
- [ ] **HELD-RECONCILE-MULTICROSS** — `edReconcileRegime` is exact only for the served (nearest-spot) flip; on multi-crossing profiles a live spot crossing a DIFFERENT boundary shows the old regime for ≤5s until the poll re-anchors. ACCEPTED-DESIGN (operator may overrule): closing it means shipping the 241-point profile to the browser per poll to close a ≤5s cosmetic window; the server recomputes exactly every poll. Revisit only if a real mis-display is observed live.
- [ ] **ML-META-OFFLINE-PARSERS** — Cursor drift-audit F2, recorded threat-model row (train/offline, NOT the serve or display path): `ml_scheduler` calls `load_lstm` directly and `arch_competition/ablation_bundle_inference.py:271` parses LSTM meta offline (Transformer offline does the same) without the Item-4 verify. Held as a deliberate scope line: offline/train parsers get this explicit row rather than a silent exemption (RC-377 root); closes if the Item-4 boundary is extended to the train/offline surfaces or the operator rules the threat model out of scope. (F3 legacy absent-manifest allowance stays carried by MODEL-04/Item-4 policy — strict only under `ED_ARTIFACT_INTEGRITY_STRICT=1`.)
- [ ] **UI-01 analytics key identity** — CLOSED-ON-OLD-LINE @ `bc1b635`, NOT IN LIVE TREE (RC-364): `analytics_cache_key` and `tests/test_ui01_analytics_cache_key.py` absent from the canonical tree after the RC-350 cutover. PORT NEEDED: server-resolved `selected_exp` (generation-guarded), single client key-builder, `analytics_cache_key` payload echo — the old-line commit is the reference implementation.
- [ ] **UI-05 guest cold-fusion SLA at the open burst** — mechanism fixes landed (priority pools, chain gate, mkt-ctx single-flight); remaining: RTH open-burst reproof, guest-universe repeatability, SLA regression enforcement.
- [ ] **ECON-01 replay-context residuals** — denominator defect fixed and locked; parent stays open on calibration-version pinning, purged/embargo execution, broader LSTM/Transformer point-in-time windowing, RTH producer-guard observation.
- [ ] **MODEL-04 stale-model serving policy** — evidence delivered (per-ticker vintage table 2026-07-10; ten tickers on pre-correctness 2026-04-30 bundles; guests route through governed anchors). Serve/unserve/retrain policy = operator decision, held.
- [ ] **BUILD-IDENTITY git_sha semantics** — `/api/build.git_sha` reads repo HEAD at request time, not the running process. `process_identity` block (startup SHA + PID) is the working method. Remaining: flip legacy top-level `git_sha` to process identity — operator call.
- [ ] **UI-EXPLAIN orphan payload surfaces** — design approved, not rendered: `pred_headline` → explanation rail; `reversal_risk`/`reversal_label` → paired risk chip; closes with rendered DOM + RTH proof for all dispositioned fields. Universal RTH runtime proof (all enrolled tickers, browser DOM, live transport) remains open behind an RTH session window.

## Candidate product directions (chase to see if they earn their place; sequence after FP-64 proves harvest)

- [ ] **GAMMA-SCANNER-RADAR** — background scanner computing the gamma regime + a "popping" flag (unusual move/vol/short-gamma) across ALL ~32 collected tickers, alerting the operator regardless of which ticker the UI shows. Best-fit monitoring product; TOS scanners can't compute our gamma-regime signal. Operator-requested 2026-07-17.
- [ ] **GAMMA-STRIKE-PICKER** — trade-construction helper: given operator intent (fast day-trade → max gamma near ATM; higher-probability → target-delta ITM), suggest the strike. Separate from the regime signal; a helper, not the edge.
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

- [ ] **DIR-01 (ONE open item — sub-points a–g are facets of it, deliberately not separate rows).**

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
  that excludes zero. Until it passes, nothing here may reach `config/decision_path_admissions.json`
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

**Unapproved inventory (probed 2026-08-01 — a dated snapshot; every per-row status has since
moved, so read live status in each home, never this paragraph):** register
`governance/unproven_register.md` · root-cause log `governance/root_cause_log.md` (PARTIAL is no
longer a ledger status) · charm rows in the same ledger. The charm-VOTE approval question remains
the operator's.

---

*Everything not listed here was either closed with evidence (see git history), superseded by the
2026-07 slimming (retired programs: Schwab V4 register, ablation grid law, governance stage plans,
mega walks), or is intentionally not tracked. If a removed concern turns out to be live, it comes
back as a new row with fresh evidence.*

---

# PROJECT A — INSTITUTIONAL REPO REHABILITATION MASTER BOARD

> **Added 2026-08-12 (operator-authorized documentation-preservation write).** This is the durable
> Project A master checklist. It is deliberately expansive and must not be shrunk. Rows are never
> silently deleted — future changes use ADD / STATUS_CHANGE / RECONCILIATION. Checkbox rule:
> `[x]` ONLY for CLOSED_WITH_EVIDENCE (or a proven PASS); `[ ]` for everything else
> (OPEN / FAIL / BLOCKED / NOT_PROVEN / HISTORICAL / GAP / unproven acceptance target).
>
> **Governing mission:** SEARCH → FIND → PROVE → FIX → TEST → IMPROVE → NEXT. Work the repo, not the
> board. The board is durable memory of everything that still needs technical proof — statuses here
> are record; the operator directs each session (AGENTS.md Operating model). Retention scoping: the
> top-of-file ledger removes closed rows (history in git); THIS Project A board is append-only
> durable record. This is NOT a governance project; parent closure requires every material child
> closed. SPY/QQQ/IWM are anchors, not scope boundaries — all fixes repo-wide and ticker-universal
> unless a proven economic reason requires otherwise.

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
- [x] **F01** — Model denominator / XGB engineered-row parity — CLOSED_WITH_EVIDENCE (RC-344/RC-339; broader universality reproof remains part of parent)
- [x] **F02** — Net GEX at spot (vendor aggregate vs repriced; distinct books, consumers separated) — CLOSED_WITH_EVIDENCE
- [x] **F03** — Gamma profile (one formula authority; terrain materializes once; one pinned `now`) — CLOSED_WITH_EVIDENCE
- [ ] **F04** — Reserved/disputed historical slot (gamma/delta walls & pin) — HISTORICAL / NOT_PROVEN (literal ID not repo-tracked; RC-292 overlap; semantic live)
- [x] **F05** — Trade actionability (one authority; frontend carries; mirror-absent withholds; reopen relocked) — CLOSED_WITH_EVIDENCE
- [x] **F06** — Expected move semantics (distinct methodologies, source-tagged) — CLOSED_WITH_EVIDENCE
- [x] **F07** — Gamma regime (one backend sign classifier; client does not reconstruct/write) — CLOSED_WITH_EVIDENCE
- [x] **F08** — ATR (standard TR+SMA authority; feature variant distinct; Wilder quarantined) — CLOSED_WITH_EVIDENCE
- [x] **F09** — RTH/session (clock boundary centralized; clock vs calendar distinguished) — PARTIAL / REOPENED (RC-411): repo-wide sweep (not #139 closure) collapses frontend/research/tools/training/A2/polling onto `time_et`. `GET /static/rth_clock_authority.js` is a request-time projection of `time_et.rth_clock_js_source` (route before StaticFiles; no committed JS blob; projection failure is 5xx, not a stale file). Not CLOSED_WITH_EVIDENCE until a Schwab desk restart is proven.
- [ ] **F10** — Candle direction — OPEN / WAITING_FOR_HOST_RETRAIN
  - [x] One dead-band authority; live producer count = 1; server + normalization delegate
  - [ ] Historical normalized rows rebuilt under dead-band; production training population corrected
  - [ ] SPY/QQQ/IWM retrained; non-anchor/universal retrain routing proven; force-retrain/cache-bypass proven
  - [ ] PREPROCESSING_VERSION bumped atomically; compatible artifacts; governed eval; calibration compatibility
  - [ ] Atomic promotion; runtime restarted on compatible generation; runtime train/serve parity; replay/backfill compatibility; universality
- [x] **F11** — Flow imbalance (one persisted authority; source travels; kwargs contract locked) — PARTIAL / REOPENED (RC-411): #139 collapsed live label onto the wrapper number. SYNTHETIC_WIRE `/api/state` volume-fallback triple is locked (empty ATM book + call 80 / put 20). A Schwab-desk vendor tick after restart remains NEXT-DEPTH. Not CLOSED_WITH_EVIDENCE.
- [x] **F12** — Relative volume variants (distinct RVOL quantities; consumers mapped) — CLOSED_WITH_EVIDENCE
- [x] **F13** — Black-Scholes valuation T (one `time_to_expiry_years`; expired fail closed) — CLOSED_WITH_EVIDENCE
- [x] **F14** — VWAP bands (one canonical producer; frontend carries; signal-layer named distinct) — CLOSED_WITH_EVIDENCE
- [ ] **F15** — POC/VAH/VAL — OPEN (Phase 2A / liquidity_value_engine)
  - [ ] Exact semantic contract; one canonical population; no alternate population masquerading; session/as-of; live/replay/backfill/frontend paths; fallback + missingness; mutation proof; universality; runtime proof
  - [x] Exact semantic contract defined for POC/VAH/VAL — Closed @ `462a581` (old line); live tree carries its own engine, `tests/test_liquidity_engine.py` green on the canonical tree (59 passed, RC-364 tree-verified). Typical-price bin, 70% VA, engine 4dp.
  - [ ] Live path populates from the canonical producer — CLOSED-ON-OLD-LINE @ `45b28c33...` (#82), NOT IN LIVE TREE (RC-364). **Landed this turn (stamp+bind, runtime still pending):** `/api/state` stamps `today_poc/vah/val` (and the rest of the snapshot family already on `PriceLevels`: pd_poc, overnight, orb_midpoint, VWAP σ) via `_raw_level` from the same carry as PDH/VWAP/ORB; console `#dr-lvl-poc`/`#exec-poc` (and VAH/VAL) bind `d.today_*`. Chart `/api/levels` TODAY_POC consumer was already live. Snapshot-table persist still has no `today_poc` column. F15 parent stays OPEN until runtime proof.
  - [x] Mutation proof (changed inputs change outputs) — Closed @ `462a581` (old line); `tests/test_liquidity_engine.py` green on the canonical tree (RC-364 tree-verified).
- [x] **F17** — Realized volatility cadence (`bar_minutes` required; no silent default) — CLOSED_WITH_EVIDENCE
- [x] **F18** — Charm drift target (not substituted with pin/net-GEX; governed absence; real UI path fixed) — CLOSED_WITH_EVIDENCE
- [ ] **F16** — Reserved/disputed VIX-regime row — HISTORICAL / NOT_PROVEN (identity reconciled; producer `vix_bucket`/`vix_level`; consumers/missingness/fallback/universality/defect-status unproven)
- [ ] **F19** — Reserved/disputed freshness/actionability row — HISTORICAL / NOT_PROVEN (actionability F05 closed; freshness — state: root_cause_log RC-282)
- [x] **F20** — Pin width (one authority; market_state + server delegate) — CLOSED_WITH_EVIDENCE
- [x] **F21** — VWAP side (one `derive_vwap_side`; consumers delegate) — CLOSED_WITH_EVIDENCE
- [x] **F22** — Dominant direction (one triplet authority; DB+UI delegate; missing guarded) — CLOSED_WITH_EVIDENCE, latent hardening verification retained
- [x] **F23** — Crossed spread (withheld at source; dead helper retired) — CLOSED_WITH_EVIDENCE
- [x] **F24** — VWAP distance (signed `spot - vwap`; train/serve parity) — CLOSED_WITH_EVIDENCE
- [ ] **F25** — Canonical ticker storage and artifact identity — OPEN / BLOCKED / PRIOR CLOSURES PREMATURE
  - [x] `ticker_storage_key` authority; SPX/`$SPX` adjudicated; readers/writers/logging-universe normalized; train-write/resume/cache/artifact-dir/arch-eval/guest-anchor/DB-key/replay canonical; focused tests pass
  - [ ] Entire-repo denominator reverified (remaining identity faucets = 0); non-anchor/universal proven; clean scoped commit lands + exact SHA; integrated into production line; runtime loaded on F25 code + runtime identity proof; parent RC-345/F25 closure
- [x] **F26** — Empirical horizon probability (one authority; UI withholds; no client argmax) — CLOSED_WITH_EVIDENCE
- [x] **F27** — Higher-timeframe OHLC (one batch synthesizer; live accumulator distinct) — CLOSED_WITH_EVIDENCE
- [ ] **F28** — Reserved/disputed absorption score — HISTORICAL / NOT_PROVEN (producer `liquidity.absorption_score`; consumers/missingness/fallback/dup-search/universality/defect unproven)
- [x] **F29** — Movement-target threshold (one per-horizon selector; no local reconstruction) — CLOSED_WITH_EVIDENCE
- [ ] **F30** — Reserved/disputed current spot — HISTORICAL / NOT_PROVEN (live spot authority / fast quote / candle-mark-last / train-serve-replay sources / fallbacks / staleness / universality unproven)
- [ ] **F31** — Price-level snapshot fallback — OPEN (Phase 2A)
  - [ ] Canonical population + producer; pre-open/RTH/replay semantics; stale-cache; input fingerprint; mutual exclusion; governed fallback; no second truth; universality; runtime proof
  - [ ] Collect-display fail-closed (bound DOM consumers) — CLOSED-ON-OLD-LINE @ `16faa71...` (#83) + pdc @ `2a1e496...` (#84), MECHANISM NOT IN LIVE TREE (RC-364): `stamp_price_level_fields` / `F31_LEVEL_KEYS` / `fail_closed_price_levels` absent from the canonical tree; live carries its own Phase 2A canonical `PriceLevelSnapshot` (RC-322/RC-323, `tests/test_phase2a_price_level_snapshot_v1.py`). Do NOT port the old mechanism — re-verify the fail-closed display property against the Phase 2A path and close on that evidence. Old-line residuals to carry: pdc consumer semantics; `PRICE_LEVELS_CACHE_SEC` stale-cache question stays with RC-282.
- [ ] **F32** — Confluence `cf_*` authority — NOT_PROVEN (state: root_cause_log RC-328; board acceptance children below)
  - [x] Canonical `confluence_features_for_bar` exists; current code routes train/serve through it; wall-clock windows
  - [ ] RC-328 ledger reconciliation (state: root_cause_log); train+serve population parity proven; caller fallback semantics; universality; ledger contradiction eliminated
- [x] **F33** — `net_gamma_prev` (raw prior 1m; batch+serve unified; inline producer removed) — CLOSED_WITH_EVIDENCE (RC-342)
- [x] **F34** — XGB pre-engineering enrichment (five scheduler routes use canonical preparer) — CLOSED_WITH_EVIDENCE (RC-340)
- [ ] **F35** — Training/serving DB identity — children CLOSED_WITH_EVIDENCE; broader DB-authority parent NOT_PROVEN
  - [x] `train_ticker` forwards `db_path`; confluence cache carries DB identity; six callers wired
  - [ ] Repo-wide parent DB-identity universality audit; every DB-reading lane binds intended DB; no default DB silently replaces caller DB; sandbox cannot become production authority; replay/backfill/artifact-lineage DB identity; universal ticker/data-source proof
- [x] **F36** — Signal-layer VWAP anchor (source-tagged session preferred; rolling labeled) — CLOSED_WITH_EVIDENCE
- [ ] **F37** — Reserved parent slot — GAP / NOT_PROVEN (parent semantic unproven; F37b exists)
- [x] **F37b** — LSTM zone encoding (shared `encode_zone`; both sites delegate) — CLOSED_WITH_EVIDENCE (RC-343)
- [x] **F38** — Training tensor cache identity (content hash; changed labels ⇒ miss; negative control) — CLOSED_WITH_EVIDENCE (universal cache-key inventory remains part of parent)
- [ ] **F39** — Confluence missingness — OPEN (explicitly OPEN despite omission from a shorter RC-345 master-open summary)
  - [ ] Measured-neutral separated from unavailable / missing-history / missing-clock / missing-input; caller fallback cannot collapse absence
  - [ ] Train/serve/replay/backfill encoding explicit; active artifact impact measured; retrain requirement proven; root code fix; version change if required; retrain if required; calibration compatibility; runtime proof; universality
- [x] **F40** — MC/GARCH sigma cadence (MC own `BAR_MINUTES`; 5m hardcode removed; live reproof) — CLOSED_WITH_EVIDENCE
- [x] **F41** — Selected DTE / expiry (selectors require expiry; empty fails closed; no search-all) — CLOSED_WITH_EVIDENCE
- [x] **F42** — GEX dollars (`gex_dollars_per_1pct_at_strike`; one `compute_exposures_by_strike`; γ×OI×mult×spot²×0.01; one-producer lock) — CLOSED_WITH_EVIDENCE

## PA-4 — MATERIAL NON-F / RC DEFECT BOARD (acceptance criteria for closing named defects)
> Defect STATUS has one home, `governance/root_cause_log.md` (RC-520, 2026-09-05): a row here never asserts
> OPEN/CLOSED — it lists what this board requires before it accepts the closure. A defect with no
> criterion of its own is a pointer. Rows that were fully accepted (RC-285, RC-291) left the board (git).
- **RC-282** (freshness / stale actionability) — no board criterion beyond the ledger row; accepted when the ledger row closes with a live-UI proof.
- **RC-297** (derivation inventory drift) — ledger row closed; the board accepts it on the standing lock `tests/test_mega2_traceable_audit.py` (tree-fed `uninventoried_engine_modules`).
- **RC-301** (absence-coerced-to-a-value) — ledger row closed for the two measured sites; the CLASS is held by the enforced `absence_has_a_type` gate, not by this board.
- **RC-328** (confluence train/serve population) — criteria are the F32 / RC-328 section below.
- [ ] **RC-292** — Gamma-pin semantic collision — OPEN (product-decision bedrock; do NOT resolve during a board-write). **Cursor-verified collision (2026-08-12):** (1) terrain `kl_gamma_pin` = total-gamma pin, correctly labeled; (2) analytics `consensus_summary.gamma_pin` = net-GEX absolute peak; (3) `pin_score` currently uses the analytics/net-GEX peak; (4) persisted `gamma_pin` receives the analytics/net-GEX peak; (5) `static/index.html` ladder row labeled "GAMMA PIN" binds `d.gamma_pin`/analytics net-GEX peak while its tooltip describes total-gamma semantics; (6) Key Levels `kl_gamma_pin` = total-gamma, correctly labeled; (7) `chart.html` PIN = terrain total-gamma and chart has a SEPARATE "NET Γ PEAK" row. **CORRECTION:** `chart.html` PIN is NOT mislabeled (Cursor disproved that). Remaining live collision (pre-fix): index-ladder GAMMA PIN + pin_score + persisted gamma_pin (net-GEX peak) vs terrain/`kl_gamma_pin` total-gamma. **Landed this turn:** ladder binds `d.kl_gamma_pin`; overlay stamps payload `gamma_pin` to the same value; pin_score and snapshot persist read terrain cache `gamma_pin` (stale/absent → None). ExposureRow.gamma_pin remains the analytics net peak (distinct table field). Schema `gamma_pin_semantic` column still absent. Sub-items: pin_score intended semantic recovered; UI-label/tooltip/persistence made consistent; backward-safe migration; behavioral+mutation lock; universality; runtime.
  - [x] `pin_score` intended semantic recovered — analysis close @ `6d14ee2` (old line); the recovered semantic is recorded in the parent row and is lineage-independent (RC-364 disposition).
  - [ ] UI label made consistent with the bound semantic — CLOSED-ON-OLD-LINE @ `0e304f6`, NOT TREE-VERIFIED (RC-364): live's `tests/test_institutional_key_levels.py` locks pin/net-GEX-peak engine semantics but does not test the index-ladder label binding. Re-verify on live (RC-352/353 renames may already satisfy it) and close on live evidence.
  - [ ] Tooltip made consistent with the bound semantic — CLOSED-ON-OLD-LINE @ `0e304f6`, NOT TREE-VERIFIED (RC-364). Same re-verify path as the label child.
  - [ ] Persisted `gamma_pin` made consistent with the bound semantic — CLOSED-ON-OLD-LINE @ `d71bb5e`, NOT IN LIVE TREE (RC-364): no `gamma_pin_semantic` marker exists in the canonical tree; `db.py` still carries `pin_score`/`gamma_pin` columns without the semantic column.
  - [ ] Backward-safe migration for persisted values — CLOSED-ON-OLD-LINE @ `d71bb5e` + `053251e`, NOT IN LIVE TREE (RC-364): the `gamma_pin_semantic=net_gex_peak` ALTER is absent from the canonical tree. PORT NEEDED if the persisted-semantic split still matters on live.
  - [ ] Behavioral + mutation lock in place — CLOSED-ON-OLD-LINE @ `0e304f6`, NOT TREE-VERIFIED (RC-364): live locks engine semantics only.
- [ ] **RC-329** — one-producer gate blind to consumer-name→semantic (semantic; live path; root; fix; proof; universality) — OPEN / NOT_PROVEN DETAILS
  - [x] Semantic of the gate blindness defect defined — Closed @ `bb85651`. One writer per name ≠ one (definition, scope). (Board-reconciled 2026-08-16.)
  - [x] Live path characterized — Closed @ `bb85651`. Console KEY LEVELS `kl_gamma_pin` row.
  - [x] Root cause identified — Closed @ `bb85651`. No registry linking payload key to semantic.
  - [ ] Fix landed — CLOSED-ON-OLD-LINE @ `1e09445...`, NOT IN LIVE TREE (RC-364): `KEY_LEVEL_CONSUMER_REGISTRY` / `hardcoded_kl_row_labels` absent; live carries its own KL row tables (`KL_PRIMARY`/`KL_CONDITIONAL`/`KL_REFERENCE` in `static/index.html`, institutional names per RC-352/353). Re-verify the defect (payload-key→semantic binding) against live's mechanism; port the registry idea only if live's tables leave the gap open.
  - [ ] Proof recorded — reopened with the fix child (RC-364); old-line proof does not transfer across mechanisms.

### RC-324 — Price-Level Snapshot Identity / Atomic Materialization
> CODE_APPEARS_FIXED != CLOSED_WITH_EVIDENCE — the ledger closed RC-324 on 2026-08-09 (state: root_cause_log RC-324); the unchecked acceptance children below are this BOARD's own outstanding proof asks, not a ledger status claim.
- [ ] RC-324 formally CLOSED_WITH_EVIDENCE
- [x] Snapshot input fingerprint includes full material OHLCV/time content
- [x] Interior bar-data changes alter the fingerprint
- [x] Read → decide → build → write is protected by `_MATERIALIZE_LOCK`
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

## PA-46 — Open technical parents (board index — no priority or execution claim; the operator directs each session)
- [ ] F10 — candle-direction host retrain
- [ ] F15 — POC/VAH/VAL
- [ ] F25 — ticker/artifact identity
- [ ] F31 — price-level snapshot
- [ ] F32 — cf_* conflict (RC-328)
- [ ] F39 — missingness zero-collapse
- [ ] RC-292 — gamma-pin semantics
- [ ] RC-282
- [ ] RC-285
- [ ] RC-297
- [ ] RC-301
- [ ] RC-329
- [ ] F35 broader DB identity parent
- [ ] Historical/disputed F04/F16/F19/F28/F30/F37
- [ ] Discovery denominator
- [ ] Universal runtime proof

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

