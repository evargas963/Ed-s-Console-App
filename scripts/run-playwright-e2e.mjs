/**
 * Single entrypoint for Playwright E2E (Issue 40 & 46):
 * 1) Fail-fast environment validation (Node, npm, deps, CLI, Chromium)
 * 2) npx playwright test
 *
 * Usage: npm run test:e2e
 */
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");

function fail(msg) {
  console.error("[test:e2e] " + msg);
  process.exit(1);
}

function ensurePlaywrightReady() {
  if (!fs.existsSync(path.join(root, "package.json"))) {
    fail("package.json not found — run from repo root.");
  }
  let r = spawnSync("node", ["--version"], { encoding: "utf8" });
  if (r.status !== 0) {
    fail("node not on PATH. Install Node.js LTS from https://nodejs.org/");
  }
  r = spawnSync("npm", ["--version"], { encoding: "utf8", shell: true });
  if (r.status !== 0) {
    fail("npm not on PATH — Node.js install should include npm.");
  }
  const pwDir = path.join(root, "node_modules", "@playwright", "test");
  if (!fs.existsSync(pwDir)) {
    fail("Playwright not installed — run: npm install");
  }
  r = spawnSync("npx", ["playwright", "--version"], {
    cwd: root,
    encoding: "utf8",
    shell: true,
  });
  if (r.status !== 0) {
    fail(
      "npx playwright --version failed.\n" +
        (r.stderr || r.stdout || "") +
        "\nFix: npm install in repo root."
    );
  }
  r = spawnSync("npx", ["playwright", "install", "chromium"], {
    cwd: root,
    stdio: "inherit",
    shell: true,
  });
  if (r.status !== 0) {
    fail(
      "playwright install chromium failed (browser binaries required).\n" +
        "Fix: check network; on Linux try: npx playwright install-deps chromium"
    );
  }
}

ensurePlaywrightReady();

const e2eRuntime = fs.mkdtempSync(path.join(os.tmpdir(), "ed-console-e2e-"));
const e2eEnv = {
  ...process.env,
  ED_RUNTIME_ROOT: e2eRuntime,
  ED_ARTIFACTS_ROOT: e2eRuntime,
};
delete e2eEnv.ED_CONSOLE_DB;
delete e2eEnv.ED_DB_PATH;
delete e2eEnv.STREAM_CAPTURE_DB_PATH;

console.log(`[test:e2e] isolated runtime: ${e2eRuntime}`);
let testRun;
try {
  testRun = spawnSync("npx", ["playwright", "test"], {
    cwd: root,
    stdio: "inherit",
    shell: true,
    env: e2eEnv,
  });
} finally {
  fs.rmSync(e2eRuntime, { recursive: true, force: true });
  console.log(`[test:e2e] removed isolated runtime: ${e2eRuntime}`);
}
if (testRun.status !== 0) {
  process.exit(testRun.status ?? 1);
}

// Issue 40/46 — unified enforcement: pytest requires this file after a successful E2E run.
const markerPath = path.join(root, ".playwright_last_run_success");
try {
  fs.writeFileSync(
    markerPath,
    JSON.stringify(
      {
        ok: true,
        finishedAt: new Date().toISOString(),
        runner: "scripts/run-playwright-e2e.mjs",
      },
      null,
      2
    ),
    "utf8"
  );
} catch (e) {
  console.error("[test:e2e] failed to write .playwright_last_run_success:", e);
  process.exit(1);
}
