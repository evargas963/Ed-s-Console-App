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

**Decision-path admission (mechanical):** no component may influence TRADE — or any output that authorizes or shapes exposure — unless `governance/decision_path_admissions.json` records it ADMITTED with evidence (preregistration, OOS results, costs, baselines, scope, leakage review) and an operator admission decision. Registry starts empty; unadmitted influence → WAIT.

**Immune rule:** any proposed new mechanism must prove it protects a real trading-system failure the page, the question, or the gate cannot already handle.

## Cursor Cloud specific instructions

Environment provisioning (Python 3.13 via `uv`, the `.venv`, `node_modules`, Playwright's Chromium) is handled by the startup update script; the notes below are the non-obvious runtime caveats.

- **Python must be 3.13.** CI and `pyproject.toml` (ruff/mypy `target-version = "py313"`) target 3.13; the VM's system `python3` is 3.12. Use the project virtualenv at `.venv` (created with `uv`, Python 3.13). Activate with `source .venv/bin/activate` (or call `.venv/bin/python`) — `uv` lives at `$HOME/.local/bin/uv`.
- **Runtime services:** the only long-lived service is the FastAPI monolith — `python -m uvicorn server:app --host 0.0.0.0 --port 8000` (port via `ED_CONSOLE_PORT`). It serves the static UI at `/`, JSON/SSE APIs under `/api/*`, plus `/governance` and `/ops`, and starts the background Collect logger on lifespan. SQLite (`data/ed_console.db`) is the only datastore — there is no Docker/Postgres/Redis.
- **Running without live Schwab credentials:** set `ED_CI_OFFLINE=1` and provide placeholder `SCHWAB_API_KEY` / `SCHWAB_APP_SECRET` so config startup passes. The server still boots and serves the UI; expect a red "Schwab token not found" banner, `STALE`/`—` quote fields, and `Active bundle blocked ... MANIFEST_MISSING` model warnings. This is the charter's fail-closed behavior (no fabricated data), not a broken environment. Live data additionally needs `schwab_token.json` (via `python reauth_schwab.py`).
- **Tests: run the full suite, not bare `pytest`.** Use `make test-all` (or `npm run test:all`), which runs Playwright E2E first (writing `.playwright_last_run_success`) and then `pytest`; `pytest` alone fails on `tests/test_playwright_must_run.py` until E2E has run. The Playwright `webServer` launches `python -m uvicorn server:app` on port 8765, so `.venv/bin` must be on `PATH` and the CI env must be exported: `CI=true ED_CI_OFFLINE=1 ED_CONSOLE_ALLOW_NONCANONICAL_DB=1 SCHWAB_API_KEY=... SCHWAB_APP_SECRET=...`. Full run is ~4–5 min.
- **Lint / hardening gates:** `ruff`, `bandit`, `pip-audit` are not in `requirements*.txt` (the Hardening CI installs them separately; the update script also installs them into `.venv`). The blocking correctness lint is `python -m ruff check . --select F401,F821,E9`; the hardening job also runs `python -m compileall` and the money-path gates under `tools/check_*.py` (see `.github/workflows/hardening.yml`).
