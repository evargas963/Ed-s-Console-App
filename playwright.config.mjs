// @ts-check
// Issue 40/46: Browser install is enforced by `npm run test:e2e` (scripts/run-playwright-e2e.mjs) before tests run.
import { defineConfig } from '@playwright/test';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { projectPython } from './scripts/project-python.mjs';

const configDir = path.dirname(fileURLToPath(import.meta.url));

// Each run serves the console on its own free port, so runs from two checkouts at once never
// reach each other's server. Playwright's workers load this file again and inherit the port the
// main process picked.
async function freePort() {
  const server = net.createServer();
  await new Promise((resolve, reject) => server.once('error', reject).listen(0, '127.0.0.1', resolve));
  const { port } = /** @type {import('node:net').AddressInfo} */ (server.address());
  await new Promise((resolve) => server.close(resolve));
  return port;
}
process.env.ED_E2E_PORT ||= String(await freePort());
export const e2eBaseURL = `http://127.0.0.1:${process.env.ED_E2E_PORT}`;

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
  // never connect to the real capture daemon's live push (see tests/conftest.py)
  env.ED_LIVE_PUSH_PORT = '1';
  // pages are told this dead port for the daemon's price socket; specs mock it (routeWebSocket)
  env.ED_LIVE_UI_PORT = '1';
  env.SCHWAB_API_KEY = 'ci-placeholder-api-key';
  env.SCHWAB_APP_SECRET = 'ci-placeholder-app-secret';
  env.SCHWAB_CALLBACK_URL = 'https://127.0.0.1:8182';
  return env;
})();

export default defineConfig({
  testDir: 'tests/e2e',
  timeout: 120000,
  // spec files run side by side; the tests within a file run in order. Every spec mocks its
  // routes per page, so files share only the read-only console server.
  workers: 4,
  fullyParallel: false,
  expect: { timeout: 30000 },
  use: {
    baseURL: e2eBaseURL,
    trace: 'retain-on-failure',
    // The console has no built-in ticker (universality, operator 2026-09-23); these specs play
    // an operator who already chose SPY and a watchlist. A spec testing the first run clears it.
    storageState: {
      cookies: [],
      origins: [{
        origin: e2eBaseURL,
        localStorage: JSON.parse(fs.readFileSync(
          path.join(configDir, 'tests/e2e/fixtures/operator_chose_spy.local_storage.json'), 'utf8')),
      }],
    },
  },
  webServer: {
    command: `"${projectPython(configDir)}" -m uvicorn server:app --host 127.0.0.1 --port ${process.env.ED_E2E_PORT}`,
    url: `${e2eBaseURL}/`,
    timeout: 120000,
    reuseExistingServer: false,
    stdout: 'pipe',
    stderr: 'pipe',
    env: e2eServerEnv,
  },
});
