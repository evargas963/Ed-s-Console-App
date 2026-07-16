# Ed Console — Governing Charter

Ed Console is a clean, institutional-grade trading intelligence system built on one governing rule: **nothing earns a place in the decision path until it proves real predictive edge — out of sample, net of realistic costs, against trivial baselines.**

It does three things, in order:

- **Collect** — preserve high-fidelity, causally honest market data (storage timestamps UTC; sessions from the exchange calendar in exchange timezone; Schwab wire fields consumed directly, CSV-first; no fabricated defaults, no silent fallbacks).
- **Prove** — pre-registered experiments (purged/embargoed walk-forward, cost-aware, baseline-compared); techniques are candidates, not residents; failed candidates are removed.
- **Decide** — combine only admitted edge into calibrated TRADE/WAIT/AVOID; abstain by default; every decision logged and scored against realized outcomes.

**Removal rule:** every file materially serves Collect, Prove, or Decide, or is a supporting control that directly protects one — anything else is removed.

**Before any work, answer in chat:** MISSION_CLASS / GAP / SMALLEST_COMPLETE_CHANGE / MINIMUM_SUFFICIENT_EVIDENCE / DECISION_PATH_EFFECT / WHY_NOW / TASK_ADMISSION.

**Enforcement is operator review.**

**Conduct:** never present unverified claims as verified; name limits in the same sentence as the tool; do not leave the changed path internally inconsistent, and do not expand into unrelated cleanup; extend existing files over creating new ones; run the smallest relevant tests during development and the required suite before code sign-off, showing output.

**Decision-path admission (mechanical):** no component may influence TRADE — or any output that authorizes or shapes exposure — unless `governance/decision_path_admissions.json` records it ADMITTED with evidence (preregistration, OOS results, costs, baselines, scope, leakage review) and an operator admission decision. Registry starts empty; unadmitted influence → WAIT.

**Immune rule:** any proposed new mechanism must prove it protects a real trading-system failure the page, the question, or the gate cannot already handle.
