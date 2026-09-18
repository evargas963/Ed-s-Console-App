// @ts-check
// Isolated E2E process-boundary env. playwright.config.mjs and the Python
// isolation tests both import this module. It must not load the Playwright
// test package: that import from a pytest xdist worker timed out at 30s
// (test_e2e_boundary_rejects_poisoned_inherited_runtime_state).
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

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
