/*
 * Every spec's `test` and `expect`: Playwright's own, with each page recording which lines of the
 * page's scripts (static/js) run, by Chromium's V8 block coverage (Playwright's page.coverage),
 * when the run names a folder for it in ED_PAGE_COVERAGE. Each worker holds the lines its tests ran
 * and writes them once, as it ends; the census counts the lines no browser test runs.
 */
const base = require("@playwright/test");
const fs = require("node:fs");
const path = require("node:path");

const FOLDER = process.env.ED_PAGE_COVERAGE;

// a script's lines holding a character V8 ran: the innermost range over a character says whether
// it ran, so the ranges are laid down outer first (an earlier start, then a later end)
function linesRun(entry) {
  const ran = new Uint8Array(entry.source.length);
  const ranges = entry.functions.flatMap((f) => f.ranges);
  ranges.sort((a, b) => a.startOffset - b.startOffset || b.endOffset - a.endOffset);
  for (const r of ranges) ran.fill(r.count > 0 ? 1 : 0, r.startOffset, r.endOffset);
  const lines = [];
  let line = 1;
  for (let i = 0; i < entry.source.length; i += 1) {
    if (entry.source[i] === "\n") line += 1;
    else if (ran[i] && lines[lines.length - 1] !== line) lines.push(line);
  }
  return lines;
}

const test = base.test.extend({
  // script path -> the lines this worker's tests ran
  linesRanByWorker: [
    async ({ browserName }, use, workerInfo) => {
      const held = new Map();
      await use(held);
      if (FOLDER !== undefined && browserName === "chromium") {
        fs.mkdirSync(FOLDER, { recursive: true });
        const file = path.join(FOLDER, `worker-${workerInfo.workerIndex}-${process.pid}.json`);
        const out = Object.fromEntries([...held].map(([p, lines]) => [p, [...lines]]));
        fs.writeFileSync(file, JSON.stringify(out));
      }
    },
    { scope: "worker" },
  ],
  page: async ({ page, browserName, linesRanByWorker }, use) => {
    const covering = FOLDER !== undefined && browserName === "chromium";
    if (covering) await page.coverage.startJSCoverage({ resetOnNavigation: false });
    await use(page);
    if (!covering) return;
    for (const entry of await page.coverage.stopJSCoverage()) {
      if (!entry.url.startsWith("http")) continue; // a script with no address of its own
      const at = new URL(entry.url).pathname.slice(1);
      if (!at.startsWith("static/js/")) continue;
      if (!linesRanByWorker.has(at)) linesRanByWorker.set(at, new Set());
      for (const n of linesRun(entry)) linesRanByWorker.get(at).add(n);
    }
  },
});

module.exports = { test, expect: base.expect };
