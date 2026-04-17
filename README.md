# Ed Web Console

Python FastAPI backend + static UI for trading analytics.

## Browser E2E (L1 SSE / Playwright)

End-to-end tests live in `tests/e2e/` and start `uvicorn server:app` via `playwright.config.mjs`.

**Authoritative docs:** [docs/playwright.md](docs/playwright.md) (fail-fast validation, marker enforcement, `make test-all`).

**Full validation (required for CI / before merge):** Playwright E2E then Python tests — `pytest` alone is not sufficient (see `tests/test_playwright_must_run.py`).

```bash
make test-all
# or (Windows / no make): npm run test:all
```

**One-time:** `npm install` at repo root.

**Run E2E only** (validates Node/npm/deps, installs Chromium if needed, then runs tests):

```bash
npm run test:e2e
```

Same as `make test-e2e`. Requires Python deps so `uvicorn server:app` can start (used by Playwright `webServer`).

**Python-side environment check** (raises AssertionError if misconfigured — used by `pytest tests/test_playwright_enforcement.py`):

```bash
python tests/playwright_ready.py
# or: npm run test:e2e:verify
```
