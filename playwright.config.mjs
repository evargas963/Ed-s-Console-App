// @ts-check
// Issue 40/46: Browser install is enforced by `npm run test:e2e` (scripts/run-playwright-e2e.mjs) before tests run.
import { defineConfig } from '@playwright/test';
import os from 'node:os';
import path from 'node:path';

// Isolate the one stream-signal authority from any inherited live STREAM_CAPTURE_DB_PATH.
// Same resolver, disposable DB — not a second runtime-state authority.
const e2eStreamDb = path.join(os.tmpdir(), 'ed-console-e2e-stream-capture.db');

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
    env: {
      ...process.env,
      STREAM_CAPTURE_DB_PATH: e2eStreamDb,
    },
  },
});
