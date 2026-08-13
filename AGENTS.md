# Ed Console — Governing Charter

Ed Console is a clean, institutional-grade trading intelligence system built on two convictions:

**Edge exists — and it is found, not revealed.** Markets carry real, recurring inefficiencies: in structure, in order flow, in dealer positioning and hedging pressure, in volatility behavior, in regime persistence, in patterns that repeat because the participants creating them don't change. None of it announces itself. Edge yields only to deliberate search — the right systems, in place at the right time, applying every tool available to us: market structure, order flow, volatility, dealer positioning, regime analysis, statistical learning, deep learning, simulation, and historical analogs.

**Nothing is trusted until proven.** No technique, signal, or model earns a place in the decision path until it proves real predictive edge — out of sample, net of realistic costs, against trivial baselines.

It does three things, in order:

- **Collect** — preserve high-fidelity, causally honest market data (storage timestamps UTC; sessions from the exchange calendar in exchange timezone; Schwab wire fields consumed directly, CSV-first; no fabricated defaults, no silent fallbacks). The data we capture today is the search space we mine tomorrow — collection is the system that has to be in place before the edge can be found.
- **Find & Prove** — run a standing search program, not a review board. Generate candidate hypotheses across every tool listed above; subject each to pre-registered experiments (purged/embargoed walk-forward, cost-aware, baseline-compared); kill what fails and keep hunting. Techniques are candidates, not residents. A high kill rate is the sign the search is honest, not that the search is failing.
- **Decide** — combine only proven edge into calibrated TRADE/WAIT/AVOID; abstain by default; every decision logged and scored against realized outcomes, so the decision layer itself generates the evidence for the next round of search.

**Removal rule:** every file materially serves Collect, Find & Prove, or Decide, or is a supporting control that directly protects one — anything else is removed.

**Before any work, answer in chat:** MISSION_CLASS / GAP / SMALLEST_COMPLETE_CHANGE / MINIMUM_SUFFICIENT_EVIDENCE / DECISION_PATH_EFFECT / WHY_NOW / TASK_ADMISSION.

**Enforcement is operator review.**

**Conduct:** never present unverified claims as verified; name limits in the same sentence as the tool; do not leave the changed path internally inconsistent, and do not expand into unrelated cleanup; extend existing files over creating new ones; run the smallest relevant tests during development and the required suite before code sign-off, showing output.

**Three-role loop (operator 2026-08-13):** one agent is coder, auditor, and PM. Do not split those roles to another model as the standing method. After implementation and before any "done" / complete / verified claim: (1) **Audit** — is the claim true on `origin/main`? Would an auditor reject this as unfinished? Run the drift-audit skill before MET/clean/verified. Spawn a read-only audit subagent when the change is material. Material by definition: any edit to `AGENTS.md`, `ACTIVE_PROGRAM.md`, `OPEN_ITEMS.md`, or `.cursor/rules/`. (2) **Land** — if the claim is system-of-record (the board, the pointer, a closure, a charter/rule change, a restored source file), the SHA must be on `main`. A PR is not the board. A feature-branch file that never reaches `main` is lost. (3) **PM** — next work is the next row in `ACTIVE_PROGRAM.md` Sequence (currently the next PA-46 child). Pure fix. No paint. No UX before its AFTER gate. Do not stop at the PR.

**Decision-path admission (mechanical):** no component may influence TRADE — or any output that authorizes or shapes exposure — unless `governance/decision_path_admissions.json` records it ADMITTED with evidence (preregistration, OOS results, costs, baselines, scope, leakage review) and an operator admission decision. Registry starts empty; unadmitted influence → WAIT.

**Immune rule:** any proposed new mechanism must prove it protects a real trading-system failure the page, the question, or the gate cannot already handle.
