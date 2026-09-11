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

import { logDir, runWithFileSink } from "./run-pytest-full.mjs";

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
  // Shell commands are handed over as one string: Node 24 (DEP0190) warns on an args
  // array under `shell: true`, and that warning would land on the terminal (RC-535).
  r = spawnSync("npm --version", { encoding: "utf8", shell: true });
  if (r.status !== 0) {
    fail("npm not on PATH — Node.js install should include npm.");
  }
  const pwDir = path.join(root, "node_modules", "@playwright", "test");
  if (!fs.existsSync(pwDir)) {
    fail("Playwright not installed — run: npm install");
  }
  r = spawnSync("npx playwright --version", {
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
  // RC-535: a browser download prints unbounded progress; it goes to the log too.
  const installCode = runWithFileSink("playwright-install", "npx", ["playwright", "install", "chromium"], {
    logPath: path.join(logDir(), "test_e2e_install_last.log"),
    cwd: root,
    shell: true,
    tailBytes: 0,
  });
  if (installCode !== 0) {
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
// RC-535: the Playwright run (and the uvicorn webServer output it relays) goes to a log
// file, never to this process's terminal pipe — a reader that stops draining cannot
// block the run. Only the bounded tail is echoed.
let exitCode;
try {
  exitCode = runWithFileSink("test:e2e", "npx", ["playwright", "test"], {
    logPath: path.join(logDir(), "test_e2e_last.log"),
    cwd: root,
    shell: true,
    env: e2eEnv,
    tailBytes: 700,
  });
} finally {
  fs.rmSync(e2eRuntime, { recursive: true, force: true });
  console.log(`[test:e2e] removed isolated runtime: ${e2eRuntime}`);
}
if (exitCode !== 0) {
  process.exit(exitCode);
}
// UNIVERSAL_QUANTITATIVE_CLOSURE_V1 (RC-542): the `.playwright_last_run_success` marker this
// runner used to write (Issue 40/46) is retired. The run's exit code is its proof, and
// required CI executes this runner directly; a tracked, hand-editable stamp compared to
// spec mtimes was a proxy that could be edited into a pass (its tracked copy was dated
// 2026-05-25 while CI had run E2E daily). `npm run test:all` still runs E2E first.
