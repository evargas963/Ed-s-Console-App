> **Classification:** Policy Specification | **Scope:** Technical documentation `docs/playwright.md`.

# Playwright E2E (Issue 40 & 46)

## Required full suite: `make test-all` or `npm run test:all`

**`python -m pytest` alone is not sufficient** for a green full check. After a clean clone, pytest will **fail** until Playwright E2E has completed successfully at least once (see `.playwright_last_run_success` below).

```bash
make test-all
```

Cross-platform (no `make` required, e.g. Windows):

```bash
npm run test:all
```

(`test:all` runs `npm run test:e2e` then `python -m pytest`; same order as the Makefile.)

This runs, in order:

1. **`npm run test:e2e`** — validates Node/npm/deps, installs Chromium, runs `tests/e2e/*.spec.js`, starts the app via `playwright.config.mjs` `webServer`.
2. On **success**, writes **`.playwright_last_run_success`** at the repo root (JSON with `ok`, `finishedAt`, `runner`). This file is **gitignored**.
3. **`python -m pytest`** — includes `tests/test_playwright_must_run.py`, which **asserts the marker exists** and that E2E sources/config are not newer than the last successful run.

If step 1 fails, step 2 does not run (Make stops). If step 3 fails, exit code is non-zero.

### Why E2E runs before pytest

The marker file is created only after Playwright exits successfully. Pytest tests that require the marker must run **after** E2E, not before.

### Other commands

| Command | Purpose |
|---------|---------|
| `npm run test:e2e` | Playwright only (also writes the marker on success) |
| `make test-e2e` | Same as `npm run test:e2e` |
| `python -m pytest` | Python tests — **fails** without a valid `.playwright_last_run_success` |
| `python tests/playwright_ready.py` | Fail-fast env check (Node, npm, `@playwright/test`, optional chromium install) |

## Marker enforcement (tests)

- **`tests/test_playwright_must_run.py`**
  - `test_playwright_was_executed` — marker file must exist with `ok: true` and valid `finishedAt`.
  - `test_playwright_marker_newer_than_e2e_sources` — if `tests/e2e/*`, `playwright.config.mjs`, or `scripts/run-playwright-e2e.mjs` are **newer** than `finishedAt`, the suite fails until you re-run `make test-all`.

## Single command (Playwright only)

```bash
npm run test:e2e
```

This is the **only** supported entrypoint for Playwright. It always:

1. **Validates** (fail-fast): `node`, `npm`, `package.json`, `node_modules/@playwright/test`, `npx playwright --version`
2. **Installs** Chromium if needed: `npx playwright install chromium`
3. **Runs** `npx playwright test`
4. **Writes** `.playwright_last_run_success` on success

If step 1 or 2 fails, the process exits **non-zero** — no silent skip.

## Python validation (tooling only)

`ensure_playwright_ready()` in `tests/playwright_ready.py` mirrors Node checks. It **raises AssertionError** if anything is missing — never `pytest.skip`.

- `pytest tests/test_playwright_enforcement.py` uses `ensure_playwright_ready(install_browsers=False)` for a **fast** CLI check.
- `python tests/playwright_ready.py` runs the **full** check including `playwright install chromium`.

## What you must have installed

| Requirement | Check |
|-------------|--------|
| Node.js LTS | `node --version` |
| npm | `npm --version` |
| JS deps | `npm install` once at repo root |
| Browsers | Installed automatically by `npm run test:e2e` |

## Removed behavior

- No `RUN_PLAYWRIGHT=1` gate and no `pytest.skip` for optional Playwright-from-pytest.
