// @ts-check
// Issue 40/46: Browser install is enforced by `npm run test:e2e` (scripts/run-playwright-e2e.mjs) before tests run.
import { defineConfig } from '@playwright/test';

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
    reuseExistingServer: !process.env.CI,
    stdout: 'pipe',
    stderr: 'pipe',
  },
});
