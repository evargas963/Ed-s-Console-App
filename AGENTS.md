# Ed Console — Governing Charter

**This file is SPECIFICATION. It enforces nothing.** Where it names a mechanism, the code is the
authority on what that mechanism actually does; if the two disagree, the code is right and the
sentence is a defect. This is the ONE declaratory engineering-law authority: no other file in the
repository carries engineering law, and every other rule surface (`CLAUDE.md`,
`.cursor/rules/00-always.mdc`) is a pointer to this one. Everything mechanical lives in three places
and nowhere else: the guard chains in `.claude/settings.json` / `.cursor/hooks.json` (in session —
action and turn-end questions those seams can answer objectively), `.pre-commit-config.yaml` (at
commit), and required CI — `pytest-full` + `hardening`, where `tools/check_delta_adds_no_debt.py`
runs the ONE institutional gate, `tools/check_institutional_correctness.py`, against the whole branch
delta (at merge). `docs/ARCHITECTURE.md` is the one architecture and location authority;
`governance/root_cause_log.md` is the one defect ledger.

Ed Console is a clean, institutional-grade trading intelligence system built on two convictions:

**Edge exists — and it is found, not revealed.** Markets carry real, recurring inefficiencies: in structure, in order flow, in dealer positioning and hedging pressure, in volatility behavior, in regime persistence, in patterns that repeat because the participants creating them don't change. None of it announces itself. Edge yields only to deliberate search — the right systems, in place at the right time, applying every tool available to us: market structure, order flow, volatility, dealer positioning, regime analysis, statistical learning, deep learning, simulation, and historical analogs.

**Nothing is trusted until proven.** No technique, signal, or model earns a place in the decision path until it proves real predictive edge — out of sample, net of realistic costs, against trivial baselines.

It does three things, in order:

- **Collect** — preserve high-fidelity, causally honest market data (storage timestamps UTC; sessions from the exchange calendar in exchange timezone; Schwab wire fields consumed directly, CSV-first; no fabricated defaults, no silent fallbacks). The data we capture today is the search space we mine tomorrow — collection is the system that has to be in place before the edge can be found.
- **Find & Prove** — run a standing search program, not a review board. Generate candidate hypotheses across every tool listed above; subject each to pre-registered experiments (purged/embargoed walk-forward, cost-aware, baseline-compared); kill what fails and keep hunting. Techniques are candidates, not residents. A high kill rate is the sign the search is honest, not that the search is failing.
- **Decide** — combine only proven edge into calibrated TRADE/WAIT/AVOID; abstain by default; every decision logged and scored against realized outcomes, so the decision layer itself generates the evidence for the next round of search.

**Removal rule:** every file materially serves Collect, Find & Prove, or Decide, or is a supporting control that directly protects one — anything else is removed.

**Placement rule:** the removal rule says what belongs in the repository; [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) says *where*. It is the canonical target architecture, and the repository is migrating toward it incrementally rather than by rewrite. Law 9 below governs movement. If the target is wrong, impossible, or materially inferior for something you encounter, raise the specific evidence-based objection *before* building a competing design. The operator decides architectural amendments; agents do not silently change the architecture.

## Institutional end-to-end execution law

These fifteen statements are the engineering law of this repository. They use MUST and MUST NOT
and contain no discretion. They apply to every implementation mission, including missions that
change governance itself.

1. EVERY implementation mission MUST correct the entire materially connected path, not only the reported symptom.
2. EVERY material defect discovered in that connected path MUST be corrected in the same mission unless an objectively external blocker makes execution impossible. The blocker MUST be named in the ledger row as `BLOCKED` with the event that clears it; preference, scope convenience and remaining runway are not blockers.
3. A material connected defect MUST NOT be classified as unrelated, pre-existing, follow-up, future work, or out-of-scope merely to permit the current mission to close. "Unrelated cleanup" means work on a path that is NOT materially connected to the change; a connected defect is never unrelated.
4. A patch, bypass, workaround, compatibility path, duplicate producer, alternate computation, silent fallback, shadow state, temporary shim, special-case branch, compensating wrapper, duplicate lifecycle owner, or parallel authority MUST NOT be introduced when the canonical or root correction can solve the problem.
5. If such non-institutional machinery already exists in the materially connected path, it MUST be deleted, consolidated, moved, or replaced as part of the repair.
6. ONE FAUCET = ONE COMPUTATION AUTHORITY. Every material semantic truth MUST have exactly one canonical computation. Any number of consumers MAY call that computation, and calling it does NOT create another computation authority. Independently implementing or reconstructing the same material semantic truth — a duplicate helper, an alternate builder, a fallback calculator, an adapter that recomputes, a SQL-derived replacement, a frontend reconstruction, a training-only or research-only reimplementation, a compatibility shim, a cached or replayed alternate formula, an inline recreation of canonical semantics — DOES create a second faucet and is forbidden. Research, backtest, training, scoreboard, replay, backfill, cache, frontend and SQL paths MUST consume the canonical computation or its produced result wherever the same semantic truth is required; they MUST NOT reimplement it. "Validated in research" MUST mean "runs live" by construction. Feeding the canonical computation a different input population and publishing the result under the same name is a second faucet too — the truth is the pair (computation, input population), and each such pair is its own field with its own name.
7. ONE responsibility MUST have ONE canonical owner.
8. Tests MUST conform to the correct architecture. Production architecture MUST NOT remain wrong merely because existing tests depend on it. A test import or reference MUST NOT be treated as a production caller or as justification for retaining a superseded implementation.
9. Materially touched misplaced responsibility MUST move toward `docs/ARCHITECTURE.md` in the same mission when it can be moved without rewriting an unrelated subsystem. If it cannot be moved because of a concrete technical dependency, the mission MUST name that exact dependency and the affected requirement remains NOT_PROVEN. "Large diff", "existing tests", "legacy location", "risk" and "time" are NOT valid exemptions. New production responsibility MUST NOT move away from the target: no new root-level production module, no structure the schematic does not name.
10. A scoped sub-proof MUST NOT close a broader mission, lane, component, or institutional requirement.
11. CI, tests, mergeability, agent claims, code-review summaries, and plausible explanations are evidence only. They MUST NOT establish PASS by themselves.
12. PASS requires direct proof of the resulting implementation across every applicable materially connected layer — backend, frontend, SQL, replay, cache, backfill, training, research and compatibility paths where they exist.
13. Any material FAIL = overall FAIL.
14. Any material requirement not directly proven = overall NOT_PROVEN.
15. No agent may weaken, reinterpret, waive, narrow, or silently create an exception to these requirements. Only the operator may explicitly authorize an exception, in chat, per case.

**Cleanup is not done when the instances are gone.** Deleting an accumulated population without repairing the producer that creates it leaves the defect intact and the ledger claiming otherwise. Closure needs the population disposed of, the producer or its lifecycle repaired, and a control proving recurrence fails — demonstrated at the actual producer being repaired, in that change's own tests.

**What is mechanically enforced, and its honest limit.** The law binds as spoken. The checks below, all inside `tools/check_institutional_correctness.py`, detect ONLY the objective classes named here, judged on the change under commit (the staged index against its base; the delta gate stages the whole branch) and never on English in prose. A green gate is one enforcement layer and evidence only; it is NOT proof that an implementation is institutionally correct, and a PASS from it MUST NOT be described as such. Every class not listed is NOT_MECHANICALLY_DETECTABLE and is enforced by the law alone.

| Check | Failure class it detects | Detection method | Known blind spot | Not a duplicate of |
|---|---|---|---|---|
| `no_superseded_path_survives` (laws 4, 5, 8) | A production definition this delta orphaned and left defined — a superseded path still callable | References bound to definitions through the import structure (local def, `from m import name`, `alias.name` through `import m`); a definition alive before the delta with no bound reference after it | A reference the import structure cannot type (`self.x`, `obj.x`, a `getattr` string, a star import) keeps every same-named definition alive; a same-name collision can hide a superseded path behind such a reference. Never a false positive. Decorated definitions and dunders are not judged. | `changed_computation_leaves_no_twin` judges bodies; this judges reachability |
| `changed_computation_leaves_no_twin` (laws 1, 5, 6, 12) | (a) an added or changed function whose body is identical to another anywhere in production; (b) a changed function whose previous body had an identical copy that stayed behind; (c) a changed declared producer of a registered field while another site — Python, JavaScript, inline script or SQL — still computes that field | Position-free AST identity of bodies with six or more statements; for (c) the registry's `computation_inputs` joined arithmetically in a Python function, or its `surface_inputs` joined arithmetically inside one JS / HTML / SQL statement | A reimplementation that is neither byte-identical nor a registered field; a frontend or SQL reimplementation of a truth the registry does not enumerate, or one whose inputs are not joined in a single statement | `one_producer` counts sites whole-tree and tolerates standing debt at the delta gate; (c) fires on the change of a producer while a site remains |
| `one_producer` (law 6) | A registered field computed at two or more sites, whole tree, on any surface | Arithmetic join of declared inputs per Python function; per JS / HTML / SQL statement | Unregistered fields (reported as NOT_PROVEN, never passed silently) | Delta-scoped clause (c) above |
| `domain_faucet_registry` (law 6) | A new level-domain producer route, or a d1-style greek formula added outside `math_levels.py`, in Python or in the frontend | Staged added text: route decorator vocabulary; `log(spot/…)` with `sqrt` in reach | Any greek formula written in another shape | Formula-shape, not field identity |
| `no_new_root_production_module` (law 9) | A Python module added or moved to the repository root | Staged name-status | Misplacement inside packages | — |
| `institutional_closure_ledger` (laws 10, 11, 14) | A parent lane CLOSED over a blocked dimension, over unresolved limitations, without a SHA, or citing a mechanism or evidence path that does not exist; a RETIRED lane still carrying current-authority fields | Ledger validation plus file existence for every cited path | Prose claims that name no path | `authority_docs_cite_existing_mechanisms` reads the documents, this reads the ledger |
| `authority_docs_cite_existing_mechanisms` | This file, the process documents, the hook rosters or the pre-commit config naming a tool that is not on the tree | Path grammar plus file existence | A stale claim that names no path | — |

Controls: every row above has negative controls (the attack fails for the stated reason) and positive controls (the legitimate change passes) in `tests/test_institutional_e2e_enforcement_v1.py`, `tests/test_one_producer_gate_v1.py`, `tests/test_institutional_closure_gate.py` and `tests/test_ui_mockup_lock_v1.py`, and the executable boundary (candidate index → `tools/check_delta_adds_no_debt.py` → the gate → process exit status) is attacked by `tests/institutional_e2e_boundary_campaign.py`, an operator-run campaign whose results are recorded on the ledger row. `tools/mission_latch.py` requires one open ledger row before a production mutation and refuses a turn end while that row is unfinished and unblocked.

## Operating model

**The operator directs each session in chat.** Who reads, who writes, who audits is decided per session by the operator — there are no standing AI roles and no per-file authority machinery. The operator's conversational GO is the approval channel; changes to who-is-in-charge surfaces (workflows, agent settings/hooks, guard rosters) stop for the operator's explicit word in chat before merging. *(No mechanism enforces that last sentence — there is no CODEOWNERS file. It is a working agreement, and it is stated here as one.)*

**An instruction binds when it is spoken.** A stated law is the obligation itself; a check or hook only adds detection, because agent compliance has a measured failure rate. Absence of a lock is never a licence — it only means the operator is doing the detecting. New mechanical locks are added when the operator asks for one, never manufactured from the words "law" or "mandate": that recipe is how governance sprawl grew, and it is retired. A control that decides a real question by matching English in free text is not enforcement — it fails correct work phrased differently and passes wrong work phrased well.

**Research, then act.** Before editing, read the reference the change rests on — the existing implementation, the direction doc, the vendor spec — and name it.

**Conduct:** never present unverified claims as verified; name limits in the same sentence as the tool; do not leave the changed path internally inconsistent; extend existing files over creating new ones; show the output of every verification you cite.

**Verification discipline (RC-517).** Obtaining evidence has a cost, and the cost is governed as strictly as the claim. These statements use MUST; `governance/AGENT_OPERATING_PROCESS_V1.md` section 8 carries the procedure and the thresholds.
- **Targeted before expensive.** The agent MUST run the smallest materially sufficient targeted tests first. A known targeted failure, harness defect, environment defect or candidate instability MUST be corrected before pytest-full, full E2E, the delta gate, the whole institutional catalog or an equivalently expensive wave is launched, unless that expensive run is itself the only way to diagnose the defect. The required final suites run once, after targeted verification is green and the candidate is stable.
- **Preflight before expensive.** Before an expensive operation the agent MUST verify the prerequisites that decide its validity: the intended interpreter and dependencies, the intended environment variables (including explicit offline mode or real credentials, never inherited placeholders behind a live claim), isolated test and runtime paths, no production-state contamination, no conflicting heavy workload, and the intended worktree, index and tree identity. An expensive operation whose previous failure came from an unresolved environment or harness defect MUST NOT be rerun until that defect is fixed.
- **Observability.** A long-running operation MUST expose its command, start time, process identity, current phase and last observable progress, and MUST persist completed results as they finish. "Still running" without that evidence is not a status.
- **Anomaly trigger.** When an operation exceeds its expected duration materially, or shows no observable progress for an abnormal interval, the agent MUST investigate before waiting further: process alive, CPU and I/O, child state, output growth, blocking or external wait, contention, environment failure, unexpectedly serial work, repeated work that could reuse identical evidence. Healthy: continue and state the proof. Unhealthy: stop and root-fix. Slow by design: fix the design before repeating it. There is no universal kill timeout.
- **Safe parallelism.** Independent expensive cases SHOULD run in parallel only with genuinely isolated state (separate worktrees, indexes, temporary state, no shared mutable cache) and only when contention will not make the result slower or unsafe. Shared mutable worktree, index or runtime state MUST NOT be parallelised for speed.
- **Proof reuse.** Completed valid proof MUST be preserved and reused while its evidence identity is unchanged: code SHA, gate and check implementation, base SHA, enforced roster, environment semantics. A material change to any of these invalidates the affected proof and only that proof.
- **Selective rerun.** After a failure the agent MUST classify it, fix its root cause and rerun the smallest affected proof. A later failure MUST NOT trigger an automatic rerun of every expensive suite or a restart of a campaign whose independent results already exist.
- **No competing waves.** Two CPU-heavy verification waves MUST NOT run on one host at once. Mechanically enforced: `tools/process_lock_guard.py` blocks a heavy launch while `tools/operating_process_lock.py --heavy-jobs` shows one alive; parallelism that has been proven isolated lives inside the owner that proved it.

**Agent truth.** No false completion, no promise-without-execution (a stated next action is performed before the turn ends, or its external blocker is named), no approximate counts presented as exact (`COUNT(*)` is exact; a sample, a `MAX(rowid)` or a recycled figure is prefixed `APPROX:` in the same sentence), no model-family bait-and-switch (name the exact object scored). Operator halt words: `STOP` / `PAUSE` / `HANG IT UP` / `DO NOT CONTINUE`.

## Correctness laws

**Evidence before assertion (RC-53; universal — chat prose included).** Every empirical or quantitative claim — about market structure, this repo's data, code behaviour, or performance — is stated ONLY in one of two forms:
1. **PROVEN** — the tool call that establishes it ran in the SAME turn, BEFORE the claim, and its output is shown. State the method with the number.
2. **`[UNVERIFIED]`** — explicitly tagged as a hypothesis to be tested. Never asserted as fact, never used as a premise for a conclusion.
There is no third form. Plausible-sounding domain lore is `[UNVERIFIED]` until measured on our data.
**Fair-method clause.** A measurement is evidence only if its method cannot manufacture the result — equal-width comparison buckets, per-unit normalisation alongside totals, stated sample and selection rule, and no discarding of the inconvenient subset. A flawed check is more dangerous than no check, because it launders a false claim as verified.
Claims that cannot be measured now go in `governance/unproven_register.md`. Staged governance/report markdown adding a numeric finding is checked by `check_measured_claims_cite_evidence`; live chat prose has no hook and is bound by the law itself.

**Decision-path admission.** No component may influence TRADE — or any output that authorizes or shapes exposure — unless `config/decision_path_admissions.json` records it ADMITTED with evidence (preregistration, OOS results, costs, baselines, scope, leakage review) and an operator admission decision. Registry starts empty; unadmitted influence → WAIT. Enforced by `decision_gate.py` in `call_engine.compute_call`, and by `check_decision_path_wired`.

**Find & Prove substance (RC-210).** Staged experiment reports claiming significance/Sharpe/alpha require `n_trials` + a multiple-testing method, or `[UNVERIFIED]`. Research runners must not use plain `KFold`/`train_test_split` on labeled financial paths without purge/embargo, or `# leakage-ok:`. CONFIRMATORY claims in `research/**` require a resolvable prereg path.

**UNIVERSAL ticker scope (RC-160).** Collect, Find & Prove, Chart, prompts and reports default to the enrolled universe — never SPY-only or sentinel-only framed as complete. Narrow samples require `OUT-OF-SCOPE:` (or `# universal-scope-ok:`) with a reason; sentinel-clean ≠ operable-clean, and a sentinel-only clean claim is named `SENTINEL_*`, never `OPERABLE_SURFACE_CLEAN`. Enforced by `check_universal_ticker_scope` and `tools/universal_scope_lock.py` behind the PreToolUse guard.

**Chart-intent + next-RTH residuals (RC-163).** Collect/accrual finish language cannot soft-out Chart render as OUT-OF-SCOPE without an open residual or a proven consumer — banking ≠ render Done. Forward residuals must not hardcode a weekday-named live-proof label when the next RTH is a different weekday; compute it with `time_et.is_trading_day_et` and state the ISO date with the weekday. Escapes: `# chart-intent-ok:` / `# next-rth-ok:`. Enforced by `check_chart_intent_and_next_rth` and `tools/chart_intent_lock.py` behind the PreToolUse guard.

**Honesty / no dodge (RC-209).** Do not lie directly or by omission; do not dodge a plain yes/no or score question; do not substitute deflection for requested deliverables; do not claim a mechanical lock via `.md`/`.mdc`. `tools/honesty_guard.py` blocks detectable dodge and MD-as-lock patterns on Stop.

**Close contract.** A `CLOSED` root-cause row carries a five-level why-chain and measured evidence, and where it says a code change exists the named files must be staged with the row or carried by a cited commit. Enforced by `check_root_cause_log`.

**Backlog.** Honest PARTIAL with a tracker is legal; mass-fake CLOSE is not. A due date moves only when the row is blocked outside this repository, recorded as `RE-DATED <old>-><new>: BLOCKED_ON_*` — "need more time" is not a blocker.

**Agent operating process (RC-217; `governance/AGENT_OPERATING_PROCESS_V1.md` carries the detail).** Measure before claiming, land small, never kill a pre-commit mid-hook, and distinguish LIVE from DISK until a restart is proven. PreToolUse blocks destructive-git forms, piped commits, and edits targeting the production checkout. **Live-checkout invariant:** the production `EdWebConsole` checkout is `main == origin/main` only; development runs on the separate `EdWebConsole-dev` worktree. **Debt:** no new or worsened enforced debt, and every material defect in the connected mission path is fixed end to end (law 2); `tools/check_delta_adds_no_debt.py` is the floor and there is no retirement ratio.

**Immune rule.** Any proposed new mechanism must prove it prevents a real, observed failure that the page, the question, or an existing gate cannot already handle. If two controls protect the same failure, one of them goes. Retiring an enforced check is the two-step contract in `governance/retired_checks.md`.

**Self-healing rule (RC-517).** When an observed agent failure reveals that a governing process was ambiguous, incomplete or mechanically bypassable, the EXISTING authority MUST be inspected and root-corrected in place — this file, the operating process, or the owner that already holds the seam. When the existing rule was already explicit, declaratory, unambiguous and adequately enforced, no governance is added: the event is classified as an execution failure and the existing rule is applied. Every requirement is classified as mechanically enforceable by an existing owner, declarative only, or not reliably detectable; a detection that would rest on matching prose is not built.

## Running it

The only long-lived service is the FastAPI monolith: `python -m uvicorn server:app` (port via `ED_CONSOLE_PORT`). It serves the UI at `/`, JSON/SSE under `/api/*`, plus `/governance` and `/ops`, and starts the Collect logger on lifespan. SQLite (`data/ed_console.db`) is the only datastore.

- **Python must be 3.13** (ruff/mypy target it); use the project `.venv`, not the system `python3`.
- **Without live Schwab credentials:** set `ED_CI_OFFLINE=1` with placeholder `SCHWAB_API_KEY` / `SCHWAB_APP_SECRET`. The server boots and serves; expect a red token banner, `STALE`/`—` quotes and `MANIFEST_MISSING` model warnings. That is fail-closed behaviour, not a broken environment. Live data also needs `schwab_token.json` (`python reauth_schwab.py`).
- **Tests: `make test-all`, not bare `pytest`** — Playwright E2E runs first and writes `.playwright_last_run_success`, which `pytest` requires. Full run ~4–5 min.
- **Blocking lint:** `python -m ruff check . --select F401,F821,E9`. `ruff`/`bandit`/`pip-audit` are installed by the Hardening job, not by `requirements*.txt`.
