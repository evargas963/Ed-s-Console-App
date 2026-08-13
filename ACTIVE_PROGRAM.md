# ACTIVE_PROGRAM.md — what we are doing now

**Updated:** 2026-08-13 — pointer rewrite. This file is not a second ledger.
**Charter:** `AGENTS.md` (Collect / Find & Prove / Decide).
**Ledger:** `OPEN_ITEMS.md` — Project A master board (single structural denominator).
**Now:** **PA-46** (pointer view on that board). Status derives from the canonical F/RC/PA rows it names. Do not invent a parallel queue here.

## How we stick

1. Read `OPEN_ITEMS.md` H1 + **PA-46** before starting work.
2. New work is a child of an existing PA / F / RC / PA-48 row, or it does not start.
3. Feature-branch docs that never open a PR to `main` are lost. Land the board change on `main` in the same program as the work, or the list splits again.
4. Close a checkbox only with an exact commit SHA (and test cite where code changed). Paint does not close one-faucet / identity / operator-truth rows.
5. Do not start **PHASE-5** (repo layout) while a second ledger still exists. After this pointer lands, PHASE-5 is its own PA-48 slice — no functional changes mixed in.
6. **UX-WORLD-CLASS-CONSOLE is not now.** It fires only AFTER PA-2 + PA-36 + RC-292 + F15 + LEVELS-SELF-DECLARE-TRUST. Until then: no bells-and-whistles redesign, no KEY LEVELS tabs, no options tape (Schwab has no prints). Exposures, not raw greeks. F15 / LP-01 / EXPOSURE-CONFLUENCE-CUBE are the data queue.
7. **Three-role loop** — see `AGENTS.md`. After code: audit → land on `main` when the claim is system-of-record → next row in Sequence above. A PR is not done. Finish = SHA on `origin/main`. On any issue: five Whys to a mechanism, then a prevention, before repeating the class. Subagents are a second-pass audit, not a second owner.

## Sequence (derived from PA-46 — not a competing now)

1. **This land** — one board on `main`; this file is a pointer.
2. **PA-46 execution** — fidelity first: one faucet (PA-2), identity (F25 / F32 / RC-328), pin semantic (RC-292), POC/VAH/VAL (F15), snapshot fallback (F31), candle direction host retrain (F10), confluence missingness (F39).
3. **PHASE-5** — directory reorganization for a legible repo; no functional changes mixed in. Worst institutional-debt file is `server.py`. Own PA-48 slice after the board is the only list.
4. **UX-WORLD-CLASS-CONSOLE** — **not now.** AFTER PA-2 + PA-36 + RC-292 + F15 + LEVELS-SELF-DECLARE-TRUST. Then Chart + Console layout, expiry stack, trust chips, GEX+DEX+VEX+CHEX+ΔOI+EM+value on one surface. Six-pill lock stays. No options tape.
5. **Find & Prove** — PA-48 homes: FIND-LABEL-INTEGRITY-FORENSICS, SCOREBOARD-TARGET-TRUTH Lane A/B, QUALITY_CIRCLE_SIGNAL_REFINEMENT_V1, STAGE-2, ML-PIPE-V1, SIG-01. Predictive validity is **NOT_PROVEN** until a preregistered experiment says otherwise.

Competing code that is **not** this pointer and is **not** closed by KEY LEVELS paint: `origin/feature/cf-one-faucet-land-f32-rc328` (F32 / RC-328). PR #59 is SUPERSEDED — do not merge. PR #60 is cube honesty for charm/vanna, not "KEY LEVELS done."

## Source files (not a second now)

These were **missing from `main`**. Restored on the ledger branch with SOURCE NAMESPACE banners. Read them as record, not as a parallel queue.

- `governance/root_cause_log.md` — defect log (64 OPEN @ `a2b5112`)
- `governance/REHAB_PROGRAM.md` — RH-F1..RH-F8 facets (= PA-2 spine)
- `governance/host_scheduled_jobs.md` — host-task inventory
- `governance/unproven_register.md` — claims-about-the-world (not defects)
- `reports/fp_levelset_directive_for_cursor.md` — Find & Prove premise
- `reports/cursor_desk_audit_v1.md` — one Desk report
- `reports/institutional_debt_inventory.md` — July advisory snapshot

No tracked `*.log` files. Host logs are on the operator machine. `reports/rehab_latest.md` / `tools/rehab_daily_scan.py` are still absent — do not invent them.

Do **not** create a second canonical file for `governance/` or `reports/`. Those directories are source/evidence. Outstanding work is ADDed to `OPEN_ITEMS.md` PA-48. F-rows labeled CLOSED_WITH_EVIDENCE stay `[ ]` until an exact SHA is on the row — `git log --all` has no RC-344/339/342/340/343 close commits.

## Standing runtime law (mechanically enforced — do not restate, just don't break)

### Feature placement matrix

Survivor placement resolves per `(model, horizon)` from ablation output only; nothing pre-routes
features. The survivor pre-train gate runs in order: **stack refit backtest**
(`run_survivor_stack_refit_backtest`) → edge probe → validation run, before scheduler train.
Lock: `tools/check_ml_pipeline_efficiency.py` via `tests/test_ml_feature_schema_parity.py`.

### Other locks in force

| Law | Lock |
|---|---|
| Training anchors SPY/QQQ/IWM only (`resolve_ml_training_roster`) | `tests/test_scheduler_user_tickers_return_type.py` |
| Fusion-only horizon cards; six-pill UI design lock (removed surfaces stay removed) | `tests/test_issue18_ui_contract.py` |
| Money-path correctness gate | `tools/check_market_correctness.py` (pre-commit) |
| Decision-path admission — unadmitted influence → WAIT (`decision_gate.py`) | `tests/test_decision_gate.py` |
| Scoreboard denominator-first + quality-circle contract | `tests/test_calibration_daily_scoreboard.py` |
| Institutional correctness (one lock; new requirements are checks inside it) | `tools/check_institutional_correctness.py` |

## Known risks

- `enforce_admins=false` on branch protection — admin direct-push channel open (operator settings decision; `OPEN_ITEMS.md` PA-48 GOV-REMOTE-ENFORCEMENT).
- Ten guest tickers serve pre-correctness 2026-04-30 model vintages; guests route through governed anchors on the observed path (`OPEN_ITEMS.md` PA-48 MODEL-04, operator decision held).
- `data/ed_console.db` is the live DB; scheduled host jobs write to it — inventory in `governance/host_scheduled_jobs.md`; remaining registration under PA-48 OPS-OPERABLE-SURFACE-JOB.
- Standing truths unchanged: predictive validity **NOT_PROVEN**; real-money **NOT_APPROVED**; admissions **BUILT_EMPTY** → WAIT; card fidelity **NOT_PROVEN**.
