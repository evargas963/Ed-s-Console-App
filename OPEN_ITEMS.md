# Open items

Open-work ledger for the charter phases (Collect / Find & Prove / Decide). Rows close only with a
commit SHA (and test cite where code changed). History lives in git — closed and superseded rows
are removed, not accumulated; the pre-slimming ledger is preserved at tag-time in history
(`git log --follow OPEN_ITEMS.md`).

**Last rewritten:** 2026-07-16 — post-slimming reconciliation (PR #44 merged @ `8f4c922`).

---

## Standing truths (change these only with evidence)

| Fact | Status |
|---|---|
| Predictive validity (any horizon beats chance, OOS, net of costs) | **NOT_PROVEN** — 2026-06-01 gate verdict stands |
| Real-money readiness | **NOT_APPROVED** |
| Decision-path admission registry (`governance/decision_path_admissions.json`) | **BUILT_EMPTY** — gate live in `call_engine.compute_call` via `decision_gate.py`; nothing admitted; directional calls force WAIT (running server picks this up on its next restart) |
| Card fidelity overall / universal runtime live proof | **NOT_PROVEN** |

---

## Now — post-slimming sequence

- [x] **RECON-01 Operator-doc reconciliation** — `OPEN_ITEMS.md` + `ACTIVE_PROGRAM.md` rebuilt against the charter; stale pointers in `governance/OPERATOR_DECISION_REGISTER.md` fixed. Closed @ `5c5f239` (PR #45).
- [ ] **RECON-02 Disk-cleanup purge** — ~53.3 GB quarantined (moved, not deleted) 2026-07-15/16. Purge only after one clean trading session AND the operator gives the purge word. Separately: `_backup_pre_exec_identity_v1_20260713.db` (18.4 GB) holds until ~5 clean trading days after the slimming merge.
- [x] **PHASE-4 Decision-path gate (mechanical)** — `decision_gate.py` (fail-closed admission verdict) + empty `governance/decision_path_admissions.json` + gate block in `call_engine.compute_call` (last directional authority; would-be direction preserved in `wait_blocker.gated_signal` for the scoring loop) + `tests/test_decision_gate.py`. Merged PR #46. Closed @ `e009aa2`. Runtime: directional calls stay `WAIT — decision path not admitted` until Find & Prove earns the first admission.
- [ ] **PHASE-5 Restructure** — deliberate directory reorganization for a legible repo. After Phase 4; no functional changes mixed in.

## Post-slimming FINDs (host + ops)

- [ ] **FIND-SCHWAB-WORKER-LEAK** — `schwab-py` (via `multiprocess`) leaks spawn workers: 15 orphaned Python processes accumulated from scheduled runs before the 2026-07-16 kill. Root cause: Schwab client processes not shut down cleanly at end of scheduled jobs. Fix direction: explicit client close/terminate in the scheduled entry points (scoreboard/backfill runners), then observe zero orphans across a week of scheduled runs.
- [ ] **FIND-SCHEDULED-JOBS-VISIBILITY** — agent-registered Windows Scheduled Tasks (e.g. daily 15:35 scoreboard) run outside any app surface; the operator discovered them by accident. Fix direction: a single documented inventory of host scheduled jobs (name, schedule, command, log path) plus an ops-surface note; creating/removing scheduled tasks requires an explicit operator-visible record.

## Find & Prove queue

- [ ] **FIND-LABEL-INTEGRITY-FORENSICS** — 2026-07-16 scoreboard shows cells too extreme in both directions to be noise: `$SPX` 60c **0.0% on n=108** (0/61 directional), `UNH` 0–6.6% across all horizons (n=244), `MSFT` 60c directional 99.0% (n=101), QQQ 60c 72.3%. Extreme-both-ways is the signature of a labeling/join artifact (inverted labels, timestamp misalignment, broken outcome join), not model quality; every horizon carries `TIMESTAMP_IDENTITY_NOT_PROVEN`. Resolve whether these cells are artifacts before trusting any accuracy number. First Find & Prove work item post-merge; feeds the target-truth lane below.
- [ ] **SCOREBOARD-TARGET-TRUTH SCOREBOARD_SEMANTICS_TARGET_TRUTH_AND_60C_ROOT_CAUSE_FORENSIC_V1** — two separate lanes (branch `scoreboard-target-truth-60c-forensic-v1`). Lane A (scoreboard schema v4, operator-semantic safety: trade-decision ALL card, confusion matrices, baselines, fail-closed accuracy presentation, invalid-threshold exclusion) contains HEAD backfill behavior only — no identity-first attachment code is part of the Lane-A package. Lane B (identity-first outcome attachment, `calibration/backfill_outcomes.py` + tests) is NOT in the Lane-A patch — it exists only as uncommitted worktree design; LANE B COMMIT_READY = NO (requires the separate data-impact mission: compound identity, production-copy reconciliation, old-vs-new weights/decisions, migration/rollback, RTH proof). Forensic packet: `reports/scoreboard_forensic/july13_2026_target_truth_forensic.json` — LEGACY_PLACEHOLDER_THRESHOLD CONFIRMED (100% of labeled July-13 rows; 60c threshold spans 0.86–416 bps of spot); target redesign OPEN via the preregistered research protocol.
- [ ] **QUALITY_CIRCLE_SIGNAL_REFINEMENT_V1** — ENABLED / NOT_STARTED (operator 2026-07-09) — DEPENDS ON DAILY_SCOREBOARD_DENOMINATOR_FIRST_V1: input layer VALID as of `06a3f9e8e73811d61364b2829ff462d7b90474de`. The continuous signal-refinement loop consumes the denominator-first scoreboard (eligible grid + quality_circle section) as its measurement substrate. Boundary (binding): the scoreboard identifies weak tickers/horizons/coverage gaps; it does NOT itself approve model or signal-rule changes — any refinement requires a separate audited lane.
- [ ] **STAGE-2 Target/label foundation** — continue `docs/stage1_target_label_foundation/` Stage 2: retire the confirmed placeholder thresholds and design the governed target so scoreboard accuracy becomes decision-valid. Preregistered protocol; no outcome mining.
- [ ] **ML-PIPE-V1 predictive-validity closeout** — remaining from the correctness program: operator-host shuffled-label runs on real capture data per model-family×horizon, then a clean governed retrain, then per-ticker/per-horizon validity classification. Until then the standing NOT_PROVEN verdict holds.
- [ ] **SIG-01 scoreboard/actionability accrual** — sessions 2–5 of segmented multi-day evidence toward signal-outcome validation; logger ~32 tickers, snapshot rows landing all session.

## Defects and held decisions

- [ ] **ML-META-JSON-VERIFICATION-ASYMMETRY** — `_load_lstm` verifies only the `.pt` checkpoint; its `lstm_*_meta.json` is consumed inside `lstm_model.load_lstm` without the Item-4 pre-deserialization verification that xgb/transformer metas get. Found 2026-07-16 while fixing the meta-stack role regression. Fix direction: verify `lstm_meta` in `_load_lstm` before `load_lstm` reads it (same pattern as `transformer_meta` at `ml_predict.py::_load_transformer`).

- [x] **UI-01 analytics key identity** — server stamps `analytics_cache_key` on A/B/C payloads; client uses one key-builder for SSE/REST and generation-guarded adopt of server `selected_exp` (no silent SSE drop on auto-scope). Tests: `tests/test_ui01_analytics_cache_key.py`. Closed @ `bc1b635`.
- [x] **UI-04 key-levels display honesty** — P1B vanna proxy labeled in UI; P1C charm vote gated (`CHARM_VOTE_VALIDATION_STATUS == "UNAPPROVED"`); P1D PDH uses previous trading day (`liquidity_value_engine.py`). Tests: `tests/test_charm_vote_gate.py`. Closed @ `29ea1e4` (P1B/P1C) + `8686e68` (P1D).
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
