> **Classification:** Policy Specification | **Scope:** Technical documentation `docs/playwright.md`.

# Playwright E2E (Issue 40 & 46)

## Required full suite: `make test-all` or `npm run test:all`

```bash
make test-all
```

Cross-platform (no `make` required, e.g. Windows):

```bash
npm run test:all
```

(`test:all` runs `npm run test:e2e` then `node scripts/run-pytest-full.mjs`; same order as the Makefile.)

This runs, in order:

1. **`npm run test:e2e`** — validates Node/npm/deps, installs Chromium, runs `tests/e2e/*.spec.js`, starts the app via `playwright.config.mjs` `webServer`.
2. **`node scripts/run-pytest-full.mjs`** — runs `python -m pytest -n auto --dist loadfile --durations=20`.

If step 1 fails, step 2 does not run (Make stops). If step 2 fails, exit code is non-zero.
Each step's exit code is its proof. Required CI (`.github/workflows/pytest.yml`) runs both
directly and reports both.

### The retired marker (RC-542, UNIVERSAL_QUANTITATIVE_CLOSURE_V1, 2026-09-10)

Until 2026-09-10 the E2E runner wrote `.playwright_last_run_success` (a JSON stamp) and
`tests/test_playwright_must_run.py` failed pytest unless the stamp existed and was newer than
the E2E sources. That was a proxy for a run, not a run: the stamp was a tracked, hand-editable
file (its committed copy was dated 2026-05-25 while CI had executed E2E on every PR since), and
a timestamp compared to file mtimes proves nothing about what executed. Both are gone. What
survives is the runtime-isolation contract in `tests/test_playwright_runtime_isolation.py`
(the E2E server must never touch the production DB), which guards a real boundary.

### Output goes to a log file, never to the terminal pipe (RC-535)

Both steps hand their child (Playwright, and the uvicorn `webServer` output it relays; pytest and
its xdist workers) file descriptors on a log file under `logs/` (gitignored):
`logs/test_e2e_install_last.log`, `logs/test_e2e_last.log`, `logs/test_pytest_last.log`, each
overwritten by the next run. The terminal receives only a bounded echo — one start line per
step, a byte-budgeted tail of the log, and the exit code — under 4 KiB for the whole command.

MEASURED 2026-09-08: with pytest's output inherited from an agent terminal that stopped
draining, the xdist controller blocked in `terminalwriter.write_raw`, every worker idled
waiting for its next item, and the suite sat frozen for 72 minutes at 94% executed. A
process that never talks to the terminal cannot be stopped by it; the byte budget keeps even
the final echo inside the smallest pipe buffer, so the exit code arrives regardless.
`tests/test_full_suite_output_sink_v1.py` drives the runner with a reader that never reads
(and keeps the pre-repair path as a negative control that must still freeze).

### Execution entrypoints (census 2026-09-08)

Every path that runs the full suite goes through `runWithFileSink`: `npm run test:all`, `make test-all`,
and their E2E half (`npm run test:e2e` / `make test-e2e`). `.github/workflows/pytest.yml` runs its own
pinned `python -m pytest` whose reader is the GitHub Actions log collector, not a terminal. Every other
pytest invocation in the tree (`tools/check_encoder_cone_tests.py`, the `tools/_build_institutional_audit_phase3*`
builders, `tools/repo_exposure_audit.py` collect-only, `research/pilot_step3/pilot_runner.py`) is a named
subset with captured output. A bare `python -m pytest` is the pre-repair direct-pipe form: use it only for
narrow runs from a terminal you are watching, never as the full suite.

### Other commands

| Command | Purpose |
|---------|---------|
| `npm run test:e2e` | Playwright only |
| `make test-e2e` | Same as `npm run test:e2e` |
| `node scripts/run-pytest-full.mjs [pytest args]` | Python tests only, through the output sink (RC-535); extra args narrow the run (a test path, `-n 0`) |
| `python tests/playwright_ready.py` | Fail-fast env check (Node, npm, `@playwright/test`, optional chromium install) |

## Single command (Playwright only)

```bash
npm run test:e2e
```

This is the **only** supported entrypoint for Playwright. It always:

1. **Validates** (fail-fast): `node`, `npm`, `package.json`, `node_modules/@playwright/test`, `npx playwright --version`
2. **Installs** Chromium if needed: `npx playwright install chromium`
3. **Runs** `npx playwright test` in a run-private runtime root (`ED_RUNTIME_ROOT`), removed afterwards

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
- No `.playwright_last_run_success` marker and no marker test (RC-542).
