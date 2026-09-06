// @ts-check
// Issue 40/46: Browser install is enforced by `npm run test:e2e` (scripts/run-playwright-e2e.mjs) before tests run.
import { defineConfig } from '@playwright/test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

// RC-515: this is the one E2E process boundary. The web server receives no live
// runtime path, token, or credentials from its parent. Ticker/option signals stay
// canonical — DB-adjacent through stream_spine — but the DB is process-private.
export const e2eRuntimeRoot = fs.mkdtempSync(
  path.join(os.tmpdir(), 'ed-console-e2e-runtime-'),
);
const e2eConsoleDb = path.join(e2eRuntimeRoot, 'ed_console.db');
fs.closeSync(fs.openSync(e2eConsoleDb, 'wx'));
export const e2eServerEnv = {
  ...process.env,
  ED_CONSOLE_ALLOW_NONCANONICAL_DB: '1',
  ED_CONSOLE_DB: e2eConsoleDb,
  STREAM_CAPTURE_DB_PATH: path.join(e2eRuntimeRoot, 'stream_capture.db'),
  SCHWAB_TOKEN_PATH: path.join(e2eRuntimeRoot, 'missing_schwab_token.json'),
  ED_CI_OFFLINE: '1',
  SCHWAB_API_KEY: 'ci-placeholder-api-key',
  SCHWAB_APP_SECRET: 'ci-placeholder-app-secret',
  SCHWAB_CALLBACK_URL: 'https://127.0.0.1:8182',
  ED_TERRAIN_QUARANTINE_LEDGER: path.join(
    e2eRuntimeRoot, 'terrain_quarantine_ledger.jsonl',
  ),
};

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
