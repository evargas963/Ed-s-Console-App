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

**Enforcement is operator review — PLUS the mechanical locks below, which are not optional.**

**MANDATE-TO-MECHANISM LAW (operator 2026-07-26, RC-66; the meta-law that governs every other law).**
When the operator says **law**, **mandate**, **non-negotiable**, or **must never happen again**, the
agent has **no compliance choice to make**. There is nothing to evaluate, scope, defer, or "apply
going forward". In the SAME TURN, before other work:
1. Encode it as a **mechanical lock**, not a note — a check in `tools/check_institutional_correctness.py`
   and, when it must bind at the moment of action rather than at commit, a **PreToolUse hook** in
   `.claude/settings.json` (`tools/pretooluse_guard.py`).
2. Enforce it across the **whole continuum** — backend `.py`, frontend `.html/.js/.css/.ts`, SQL,
   config, governance. Never narrowed to the subsystem where it was noticed.
3. Ship the lock with a test that proves it BLOCKS, and record the RC row.

**Front end AND back end.** A commit-time check alone does NOT satisfy a mandate: by then the wrong
change is already written. If the law governs *how work is done*, it must fire *before the tool
runs*. WHY THIS EXISTS: on 2026-07-26 the operator ruled the recursive-5-why law "lives on the front
end"; a commit-time check was built instead, `.claude/settings.json` sat at `"hooks": {}`, and hours
later a CSS patch landed on `static/index.html` with no root-cause row and no analysis — the patch
did not even work, and only the operator caught it. Saying "I should have" is not a control.

**Never call an operator law "goodwill". [SOFT — no machine detects this; the operator is the detector.]** The law is the obligation the moment it is spoken; a lock
only adds DETECTION, because agent compliance has a measured failure rate. Absence of a lock is
never a licence — it only means the operator is doing the detecting, which is the thing being fixed.

**Conduct:** never present unverified claims as verified; name limits in the same sentence as the tool; do not leave the changed path internally inconsistent, and do not expand into unrelated cleanup; extend existing files over creating new ones; run the smallest relevant tests during development and the required suite before code sign-off, showing output.

**Evidence-before-assertion law (operator 2026-07-26, RC-53; UNIVERSAL — chat prose included, not just committed artifacts).**
Every empirical or quantitative claim — about market structure, this repo's data, code behaviour, or performance — is stated ONLY in one of two forms:
1. **PROVEN** — the tool call that establishes it ran in the SAME turn, BEFORE the claim, and its output is shown. State the method with the number.
2. **`[UNVERIFIED]`** — explicitly tagged as a hypothesis to be tested. Never asserted as fact, never used as a premise for a conclusion.
There is no third form. Plausible-sounding domain lore ("far-OTM strikes carry large OI") is `[UNVERIFIED]` until measured on our data.
**Fair-method clause (the lazy-verification trap). [SOFT — a method that manufactures its own result is judgement, not a detectable artifact; operator review is the detector.]** a measurement is evidence only if its method cannot manufacture the result — equal-width comparison buckets (never compare a wide bucket's SUM against a narrow one's), per-unit normalisation alongside totals, stated sample and selection rule, and no discarding of the inconvenient subset. A flawed check is more dangerous than no check, because it launders a false claim as verified. OBSERVED: RC-53 — an unproven "wings hold most OI" claim was then "confirmed" by summing a >3% bucket spanning ~75,000 strikes against a <1% bucket of ~10,000; per-strike, OI is HIGHEST near ATM (1,456) and DECLINES to the wings (877), the opposite of the claim.
**A declared law IS the obligation — never call it "goodwill" (operator 2026-07-26, RC-56).** "When I say law it is codified, it must be done." Obligation and detection are different things: the law binds absolutely the moment it is declared; a gate check only adds DETECTION, and exists solely because agent compliance has a measured failure rate — so a breach is caught by the machine at commit rather than by the operator after the damage. Describing an unchecked law as "only goodwill" mislabels agent unreliability as a deficiency in the law and pre-excuses the next violation. Absence of a check is NEVER a licence; it only means the operator is the detector.

Enforcement: this law binds unconditionally, plus `governance/unproven_register.md` for claims that cannot be measured now. Committed artifacts are additionally machine-detected — `measured_claims_cite_evidence` (any staged governance/reports .md adding a numeric finding must carry a reproduce command or an [UNVERIFIED] tag), `rc_numeric_claims_cite_a_command` (RC rows), `rth_only_market_measurement` (session scoping), `unproven_register`. Live chat prose has no hook; it is bound by the law itself and operator review.

**Agent truth lock (mechanical, lean). [SOFT here by design — rule 01 explicitly forbids growing gate scripts for it; enforcement is the Cursor rule plus operator review.]** `.cursor/rules/01-find-prove-no-soft-stop.mdc` + `ACTIVE_PROGRAM.md` queue. No false completion, no promise-without-execution, no approximate counts presented as exact, no model-family bait-and-switch. Do not grow extra gate scripts for this. Operator halt words: `STOP` / `PAUSE` / `HANG IT UP` / `DO NOT CONTINUE`.

**Decision-path admission (mechanical):** no component may influence TRADE — or any output that authorizes or shapes exposure — unless `governance/decision_path_admissions.json` records it ADMITTED with evidence (preregistration, OOS results, costs, baselines, scope, leakage review) and an operator admission decision. Registry starts empty; unadmitted influence → WAIT.

**Immune rule. [SOFT — whether a new mechanism protects a REAL failure is a judgement call the operator makes.]** any proposed new mechanism must prove it protects a real trading-system failure the page, the question, or the gate cannot already handle.
