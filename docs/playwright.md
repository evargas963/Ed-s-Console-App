# Running the tests

## The full suite: `npm run test:all` (or `make test-all`)

1. `npm run test:e2e` — validates Node, npm and `@playwright/test` (fail-fast, never a skip),
   installs Chromium if needed, and runs `tests/e2e/*.spec.js` against `uvicorn server:app`
   (`playwright.config.mjs` `webServer`) in a run-private runtime root (`ED_RUNTIME_ROOT`),
   removed afterwards: the test server never touches the production database. What it proves:
   the page draws what it is served. Every spec but `first-run-no-ticker` replaces `/api/**`
   and the daemon's price socket with fixture data, so it proves nothing about what the server
   or the daemon serves.
2. `node scripts/run-pytest-full.mjs [pytest args]` — `python -m pytest -n auto --dist loadfile
   --durations=20`; extra args narrow the run (a test path, `-n 0`).

If step 1 fails, step 2 does not run. Each step's exit code is its proof. CI
(`.github/workflows/pytest.yml`) runs both.

## Output goes to a log file

Both steps give their child processes file descriptors on a log under `logs/` (gitignored):
`logs/test_e2e_install_last.log`, `logs/test_e2e_last.log`, `logs/test_pytest_last.log`, each
overwritten by the next run (`runWithFileSink`). The terminal receives only a start line, a
bounded tail of the log and the exit code, so a terminal that stops reading cannot stall a run
(`tests/test_full_suite_output_sink_v1.py`). A bare `python -m pytest` writes to the terminal:
use it only for narrow runs you are watching.

## Checks

| Command | Purpose |
|---------|---------|
| `npm run test:e2e` / `make test-e2e` | Playwright only |
| `python tests/playwright_ready.py` (`npm run test:e2e:verify`) | Node, npm, `@playwright/test` and Chromium present (`ensure_playwright_ready`; raises, never skips) |

Requirements: Node.js LTS, npm, `npm install` once at the repo root; the browsers are installed by
`npm run test:e2e`.
