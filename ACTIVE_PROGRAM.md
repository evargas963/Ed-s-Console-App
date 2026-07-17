# ACTIVE_PROGRAM.md — what we are doing now

**Updated:** 2026-07-16 — post-slimming reconciliation (slimming PR #44 merged @ `8f4c922`).
**Charter:** `AGENTS.md` (Collect / Find & Prove / Decide). **Ledger:** `OPEN_ITEMS.md`.

## Sequence

1. **Reconciliation (this PR)** — operator docs rebuilt against the charter; stale register pointers fixed.
2. **Quarantine purge** — after one clean trading session + operator purge word (`OPEN_ITEMS.md` RECON-02).
3. **Phase 4 — decision-path gate** — `decision_gate.py` + `governance/decision_path_admissions.json` + `tests/test_decision_gate.py`. Mechanical form of the charter's admission clause; registry starts empty, unadmitted influence → WAIT.
4. **Phase 5 — restructure** — deliberate directory reorganization; no functional changes mixed in.
5. **Find & Prove resumes** — label-integrity forensics ($SPX/UNH/60c anomalies), then Stage 2 of the target/label foundation (`docs/stage1_target_label_foundation/`). Predictive validity is **NOT_PROVEN** until a preregistered experiment says otherwise.

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
| Scoreboard denominator-first + quality-circle contract | `tests/test_calibration_daily_scoreboard.py` |

## Known risks

- `enforce_admins=false` on branch protection — admin direct-push channel open (operator settings decision; `OPEN_ITEMS.md` GOV-REMOTE-ENFORCEMENT).
- Ten guest tickers serve pre-correctness 2026-04-30 model vintages; guests route through governed anchors on the observed path (`OPEN_ITEMS.md` MODEL-04, operator decision held).
- `data/ed_console.db` is the live DB; scheduled host jobs (scoreboard 15:35) write to it — see `OPEN_ITEMS.md` FIND-SCHEDULED-JOBS-VISIBILITY.
