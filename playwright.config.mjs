// @ts-check
// Issue 40/46: Browser install is enforced by `npm run test:e2e` (scripts/run-playwright-e2e.mjs) before tests run.
import { defineConfig } from '@playwright/test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

// RC-515 + RC-534 reconciled: this is the one E2E process boundary. The web server
// receives no live runtime path, token, or credentials from its parent. RC-534 disabled the
// ambient ED_CONSOLE_DB / STREAM_CAPTURE_DB_PATH overrides (db.py raises on them), so
// isolation is ONE knob — ED_RUNTIME_ROOT — under which the console DB, stream DB and the
// DB-adjacent ticker/option signals all resolve canonically and process-private. Inherited
// production selectors are deleted first so a live parent value can never win.
export const e2eRuntimeRoot = fs.mkdtempSync(
  path.join(os.tmpdir(), 'ed-console-e2e-runtime-'),
);
export const e2eServerEnv = (() => {
  const env = { ...process.env };
  delete env.ED_CONSOLE_DB;
  delete env.ED_DB_PATH;
  delete env.STREAM_CAPTURE_DB_PATH;
  env.ED_RUNTIME_ROOT = e2eRuntimeRoot;
  env.ED_ARTIFACTS_ROOT = path.join(e2eRuntimeRoot, 'artifacts');
  env.ED_CONSOLE_ALLOW_NONCANONICAL_DB = '1';
  env.SCHWAB_TOKEN_PATH = path.join(e2eRuntimeRoot, 'missing_schwab_token.json');
  env.ED_CI_OFFLINE = '1';
  env.SCHWAB_API_KEY = 'ci-placeholder-api-key';
  env.SCHWAB_APP_SECRET = 'ci-placeholder-app-secret';
  env.SCHWAB_CALLBACK_URL = 'https://127.0.0.1:8182';
  env.ED_TERRAIN_QUARANTINE_LEDGER = path.join(
    e2eRuntimeRoot, 'terrain_quarantine_ledger.jsonl',
  );
  return env;
})();

export default defineConfig({
  testDir: 'tests/e2e',
  timeout: 120000,
  workers: 1,
  fullyParallel: false,
  expect: { timeout: 30000 },
  use: {
    baseURL: 'http://127.0.0.1:8765',
    trace: 'on-first-retry',
  },
  webServer: {
    command: 'python -m uvicorn server:app --host 127.0.0.1 --port 8765',
    url: 'http://127.0.0.1:8765/',
    timeout: 120000,
    reuseExistingServer: false,
    stdout: 'pipe',
    stderr: 'pipe',
    env: e2eServerEnv,
  },
});
