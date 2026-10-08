/**
 * RC-UI-1 — node assertions for static/js/ed-gamma.js.
 * Run: node tests/ed_gamma_node.mjs
 *
 * E: the displayed dollar text is FORMATTING-ONLY and equals the backend value.
 * Sign -> colour (D) and row order (F) are proven in the browser (console-gamma-heatmap.spec.js).
 */
import assert from 'assert';
import { readFileSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';
import vm from 'vm';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, '..');

const ctx = {
  document: {
    documentElement: {},
    getElementById: () => null,
    querySelectorAll: () => [],
    // the page's served metas: the streaming-state words
    querySelector: () => ({ getAttribute: () => '{"cell": {}, "column": {}}' }),
    addEventListener: () => {},
  },
  getComputedStyle: () => ({ getPropertyValue: () => '' }),
  AbortController, Promise, JSON, Math, Number, String, Object, Array, Date, isNaN, URL, console,
};
ctx.window = ctx;
ctx.globalThis = ctx;
// the shell (ed-core.js) as the heatmap uses it: no pan, no expiry selected
ctx.EdShell = {
  getState: () => ({}), getMeasure: () => 'gex', getExpiry: () => null, setStrike: () => {},
  newPan: () => ({ centre: null, shift: 0, served: null }), panServed: (pan, c) => { pan.served = c; },
  windowQuery: () => '&scope=auto', wireStrikeAxis: () => {},
};
vm.createContext(ctx);
vm.runInContext(readFileSync(join(ROOT, 'static/js/l1_sse_guards.js'), 'utf8'), ctx, { filename: 'l1_sse_guards.js' });
vm.runInContext(readFileSync(join(ROOT, 'static/js/ed-gamma.js'), 'utf8'), ctx, { filename: 'ed-gamma.js' });

const G = ctx.EdGamma;
assert(G && typeof G.formatUsd === 'function', 'EdGamma.formatUsd missing');

// ---- E: value formatting is formatting-only and equals the backend number ----
assert.strictEqual(G.formatUsd(958600), '$958.6K');
assert.strictEqual(G.formatUsd(-264500), '-$264.5K');
assert.strictEqual(G.formatUsd(7600000), '$7.6M');
assert.strictEqual(G.formatUsd(2140000000), '$2.1B');
assert.strictEqual(G.formatUsd(807500), '$807.5K');
assert.strictEqual(G.formatUsd(0), '$0');
assert.strictEqual(G.formatUsd(null), '');
assert.strictEqual(G.formatUsd(undefined), '');
// formatting must not change sign or magnitude scale
for (const v of [958600, -264500, 7600000, -1, 42, -999999]) {
  assert.strictEqual(G.formatUsd(v).startsWith('-'), v < 0, 'formatUsd changed sign for ' + v);
}

console.log('ed_gamma: all assertions passed');
