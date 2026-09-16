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
import { fileURLToPath, pathToFileURL } from "node:url";

import { logDir, runWithFileSink } from "./run-pytest-full.mjs";

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");

// Independent-review finding (2026-09-12), REPRODUCED and partially fixed, then found
// STILL BROKEN by a second independent review (2026-09-13): this runner used to hardcode
// ["playwright", "test"] regardless of any CLI arguments it was itself invoked with,
// silently running the FULL, unfiltered suite. The 2026-09-12 fix forwarded the caller's
// argv but still routed it through `npx` via `runWithFileSink(..., shell: true)`, which
// joins `["npx", "playwright", "test", ...args]` into ONE STRING and hands it to a shell
// to re-parse (`/bin/sh -c` on POSIX, `cmd.exe /c` on this repo's actual Windows host).
// The `shellQuoteArg` helper that used to live here only wrapped a value in double quotes
// and backslash-escaped an embedded `"` -- POSIX double quotes do not suppress
// `$(...)`/backtick command substitution, and cmd.exe does not even use backslash-escaped
// double quotes as its escaping convention, so a forwarded argument containing either
// could still be reinterpreted rather than forwarded verbatim.
//
// ROOT FIX (2026-09-13): stop going through a shell (or npx) at all. `npx playwright` is
// itself just a wrapper -- this repo's own node_modules/.bin/playwright.cmd (read
// directly) resolves to `node "<repo>/node_modules/@playwright/test/cli.js" %*`. Spawning
// that same cli.js with `process.execPath` (this exact Node binary) and a real argv array
// under runWithFileSink's shell:false branch (`spawnSync(cmd, args, {stdio})`, no shell at
// all) hands every forwarded argument to the child as one opaque array element -- nothing
// ever re-parses it, on any platform, regardless of what characters it contains. No
// quoting function is needed any more; this DELETES shellQuoteArg rather than repairing it
// again, since the safety property it was hand-rolling is what array-based shell:false
// spawning already guarantees natively -- "check existing canonical/native capabilities
// before adding custom machinery."
const PLAYWRIGHT_CLI = path.join(root, "node_modules", "@playwright", "test", "cli.js");

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

function main() {
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
  const forwardedArgs = process.argv.slice(2);
  if (forwardedArgs.length) {
    console.log(`[test:e2e] forwarding native selection arguments: ${forwardedArgs.join(" ")}`);
  }
  // RC-535: the Playwright run (and the uvicorn webServer output it relays) goes to a log
  // file, never to this process's terminal pipe — a reader that stops draining cannot
  // block the run. Only the bounded tail is echoed.
  //
  // shell:false here is load-bearing (2026-09-13, see PLAYWRIGHT_CLI comment above): a
  // forwarded argument reaches the Playwright CLI as one exact argv element, never
  // re-parsed by any shell.
  let exitCode;
  try {
    exitCode = runWithFileSink("test:e2e", process.execPath, [PLAYWRIGHT_CLI, "test", ...forwardedArgs], {
      logPath: path.join(logDir(), "test_e2e_last.log"),
      cwd: root,
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
}

// Run only when invoked directly (`node scripts/run-playwright-e2e.mjs ...`), never as a
// side effect of another module importing this file.
const isMainModule = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;
if (isMainModule) {
  main();
}
