# Ed Console — Governing Charter

**This file is SPECIFICATION. It enforces nothing.** Where it names a mechanism, the code is the
authority on what that mechanism actually does; if the two disagree, the code is right and the
sentence is a defect. Everything mechanical lives in three places and nowhere else: the guard
chains in `.claude/settings.json` / `.cursor/hooks.json` (in session), `.pre-commit-config.yaml`
(at commit), and required CI — `pytest-full` + `hardening`, which run
`tools/check_institutional_correctness.py` and `tools/check_delta_adds_no_debt.py` (at merge).

Ed Console is a clean, institutional-grade trading intelligence system built on two convictions:

**Edge exists — and it is found, not revealed.** Markets carry real, recurring inefficiencies: in structure, in order flow, in dealer positioning and hedging pressure, in volatility behavior, in regime persistence, in patterns that repeat because the participants creating them don't change. None of it announces itself. Edge yields only to deliberate search — the right systems, in place at the right time, applying every tool available to us: market structure, order flow, volatility, dealer positioning, regime analysis, statistical learning, deep learning, simulation, and historical analogs.

**Nothing is trusted until proven.** No technique, signal, or model earns a place in the decision path until it proves real predictive edge — out of sample, net of realistic costs, against trivial baselines.

It does three things, in order:

- **Collect** — preserve high-fidelity, causally honest market data (storage timestamps UTC; sessions from the exchange calendar in exchange timezone; Schwab wire fields consumed directly, CSV-first; no fabricated defaults, no silent fallbacks). The data we capture today is the search space we mine tomorrow — collection is the system that has to be in place before the edge can be found.
- **Find & Prove** — run a standing search program, not a review board. Generate candidate hypotheses across every tool listed above; subject each to pre-registered experiments (purged/embargoed walk-forward, cost-aware, baseline-compared); kill what fails and keep hunting. Techniques are candidates, not residents. A high kill rate is the sign the search is honest, not that the search is failing.
- **Decide** — combine only proven edge into calibrated TRADE/WAIT/AVOID; abstain by default; every decision logged and scored against realized outcomes, so the decision layer itself generates the evidence for the next round of search.

**Removal rule:** every file materially serves Collect, Find & Prove, or Decide, or is a supporting control that directly protects one — anything else is removed.

## Operating model

**The operator directs each session in chat.** Who reads, who writes, who audits is decided per session by the operator — there are no standing AI roles and no per-file authority machinery. The operator's conversational GO is the approval channel; changes to who-is-in-charge surfaces (workflows, agent settings/hooks, guard rosters) stop for the operator's explicit word in chat before merging. *(What is machine-forced: the guard rosters and the merge gate. `tests/test_find_fix_execution_latch_v1.py` and `tests/test_hook_chains_v1.py` pin `.claude/settings.json` and `.cursor/hooks.json` to exact, identical guard sets in required CI, so an unwiring or a Cursor/Claude divergence fails `pytest-full`; `tests/test_delta_adds_no_debt_v1.py` fails if the delta gate is unwired from the hardening workflow. There is no reviewer-approval requirement and none is wanted: branch protection requires `pytest-full` + `hardening` with `enforce_admins` on, and force-pushes and deletions are banned. Anything beyond that is a working agreement, and it is stated here as one.)*

**An instruction binds when it is spoken.** A stated law is the obligation itself; a check or hook only adds detection, because agent compliance has a measured failure rate. Absence of a lock is never a licence — it only means the operator is doing the detecting. New mechanical locks are added when the operator asks for one, never manufactured from the words "law" or "mandate": that recipe is how governance sprawl grew, and it is retired. A control that decides a real question by matching English in free text is not enforcement — it fails correct work phrased differently and passes wrong work phrased well.

**Find something broken → fix it.** Discovery creates the obligation to remediate through the full blast radius in the active session. A material defect is never disposed as queued / logged / TODO / follow-up / pre-existing / out-of-scope; if it genuinely cannot be fixed now, say exactly what blocks it, in plain sight. When implementation work exposes a material defect in the path being changed: inspect enough, establish the cause sufficiently, FIX, prove it, continue — do not spawn a separate audit mission when the cause is already sufficient to repair safely. Mechanism: `tools/mission_latch.py` — one work row open before a production mutation, and a turn may not end while that row is unfinished and unblocked.

**Cleanup is not done when the instances are gone.** Deleting an accumulated population without repairing the producer that creates it leaves the defect intact and the ledger claiming otherwise. Closure needs the population disposed of, the producer or its lifecycle repaired, and a control proving recurrence fails — demonstrated at the actual producer being repaired, in that change's own tests.

**Research, then act.** Before editing, read the reference the change rests on — the existing implementation, the direction doc, the vendor spec — and name it.

**Conduct:** never present unverified claims as verified; name limits in the same sentence as the tool; do not leave the changed path internally inconsistent, and do not expand into unrelated cleanup; extend existing files over creating new ones; run the smallest relevant tests during development and the required suite before code sign-off, showing output.

**Agent truth.** No false completion, no promise-without-execution, no approximate counts presented as exact, no model-family bait-and-switch. Operator halt words: `STOP` / `PAUSE` / `HANG IT UP` / `DO NOT CONTINUE`.

## Correctness laws

**Evidence before assertion (RC-53; universal — chat prose included).** Every empirical or quantitative claim — about market structure, this repo's data, code behaviour, or performance — is stated ONLY in one of two forms:
1. **PROVEN** — the tool call that establishes it ran in the SAME turn, BEFORE the claim, and its output is shown. State the method with the number.
2. **`[UNVERIFIED]`** — explicitly tagged as a hypothesis to be tested. Never asserted as fact, never used as a premise for a conclusion.
There is no third form. Plausible-sounding domain lore is `[UNVERIFIED]` until measured on our data.
**Fair-method clause.** A measurement is evidence only if its method cannot manufacture the result — equal-width comparison buckets, per-unit normalisation alongside totals, stated sample and selection rule, and no discarding of the inconvenient subset. A flawed check is more dangerous than no check, because it launders a false claim as verified.
Claims that cannot be measured now go in `governance/unproven_register.md`. Staged governance/report markdown adding a numeric finding is checked by `check_measured_claims_cite_evidence`; live chat prose has no hook and is bound by the law itself.

**ONE computation.** Every job — research, backtest, training, scoreboard — imports and calls the live functions; it never reimplements them. Two invocations with different inputs are two producers even through the same function. "Validated in research" must mean "runs live" by construction.

**Decision-path admission.** No component may influence TRADE — or any output that authorizes or shapes exposure — unless `governance/decision_path_admissions.json` records it ADMITTED with evidence (preregistration, OOS results, costs, baselines, scope, leakage review) and an operator admission decision. Registry starts empty; unadmitted influence → WAIT. Enforced by `decision_gate.py` in `call_engine.compute_call`, and by `check_decision_path_wired`.

**Find & Prove substance (RC-210).** Staged experiment reports claiming significance/Sharpe/alpha require `n_trials` + a multiple-testing method, or `[UNVERIFIED]`. Research runners must not use plain `KFold`/`train_test_split` on labeled financial paths without purge/embargo, or `# leakage-ok:`. CONFIRMATORY claims in `research/**` require a resolvable prereg path.

**UNIVERSAL ticker scope (RC-160).** Collect, Find & Prove, Chart, prompts and reports default to the enrolled universe — never SPY-only or sentinel-only framed as complete. Narrow samples require `OUT-OF-SCOPE:` (or `# universal-scope-ok:`) with a reason; sentinel-clean ≠ operable-clean. Enforced by `check_universal_ticker_scope` and `tools/universal_scope_lock.py` behind the PreToolUse guard.

**Chart-intent + next-RTH residuals (RC-163).** Collect/accrual finish language cannot soft-out Chart render as OUT-OF-SCOPE without an open residual or a proven consumer — banking ≠ render Done. Forward residuals must not hardcode a weekday-named live-proof label when the next RTH is a different weekday. Escapes: `# chart-intent-ok:` / `# next-rth-ok:`.

**Honesty / no dodge (RC-209).** Do not lie directly or by omission; do not dodge a plain yes/no or score question; do not substitute deflection for requested deliverables; do not claim a mechanical lock via `.md`/`.mdc`. `tools/honesty_guard.py` blocks detectable dodge and MD-as-lock patterns on Stop.

**Close contract.** A `CLOSED` root-cause row carries a five-level why-chain and measured evidence, and where it says a code change exists the named files must be staged with the row or carried by a cited commit. Enforced by `check_root_cause_log`.

**Backlog.** Honest PARTIAL with a tracker is legal; mass-fake CLOSE is not. A due date moves only when the row is blocked outside this repository, recorded as `RE-DATED <old>-><new>: BLOCKED_ON_*` — "need more time" is not a blocker.

**Agent operating process (RC-217; `governance/AGENT_OPERATING_PROCESS_V1.md` carries the detail).** Measure before claiming, land small, never kill a pre-commit mid-hook, and distinguish LIVE from DISK until a restart is proven. PreToolUse blocks destructive-git forms, piped commits, and edits targeting the production checkout. Destructive git has exactly one owner — `operating_process_lock.reset_guard_violations`, reached through `tools/process_lock_guard.py`; `--force-with-lease` stays legal because it is the safe form. **Live-checkout invariant:** the production `EdWebConsole` checkout is `main == origin/main` only; development runs on the separate `EdWebConsole-dev` worktree.

**Immune rule.** Any proposed new mechanism must prove it prevents a real, observed failure that the page, the question, or an existing gate cannot already handle. If two controls protect the same failure, one of them goes.

## Running it

The only long-lived service is the FastAPI monolith: `python -m uvicorn server:app` (port via `ED_CONSOLE_PORT`). It serves the UI at `/`, JSON/SSE under `/api/*`, plus `/governance` and `/ops`, and starts the Collect logger on lifespan. SQLite (`data/ed_console.db`) is the only datastore.

- **Python must be 3.13** (ruff/mypy target it); use the project `.venv`, not the system `python3`.
- **Without live Schwab credentials:** set `ED_CI_OFFLINE=1` with placeholder `SCHWAB_API_KEY` / `SCHWAB_APP_SECRET`. The server boots and serves; expect a red token banner, `STALE`/`—` quotes and `MANIFEST_MISSING` model warnings. That is fail-closed behaviour, not a broken environment. Live data also needs `schwab_token.json` (`python reauth_schwab.py`).
- **Tests: `make test-all`, not bare `pytest`** — Playwright E2E runs first and writes `.playwright_last_run_success`, which `pytest` requires. Full run ~4–5 min.
- **Blocking lint:** `python -m ruff check . --select F401,F821,E9`. `ruff`/`bandit`/`pip-audit` are installed by the Hardening job, not by `requirements*.txt`.
