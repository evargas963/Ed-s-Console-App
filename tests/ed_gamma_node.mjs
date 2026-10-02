/**
 * RC-UI-1 — node assertions for static/js/ed-gamma.js.
 * Run: node tests/ed_gamma_node.mjs
 *
 * E: the displayed dollar text is FORMATTING-ONLY and equals the backend value.
 * G: the heatmap's streamed-contract demand is keyed per ticker, driven through the module's
 *    own load path (its ed:view / ed:ticker listeners, a served surface, its render).
 * Sign -> colour (D) and row order (F) are proven in the browser (console-gamma-heatmap.spec.js).
 */
import assert from 'assert';
import { readFileSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';
import vm from 'vm';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, '..');

const listeners = {};
const host = { innerHTML: '', setAttribute: () => {}, removeAttribute: () => {}, querySelector: () => null, querySelectorAll: () => [] };
const state = { workspace: 'options', subview: 'gamma', view: 'heatmap', ticker: 'SPY' };
const served = {};
const demandCalls = [];
const ctx = {
  document: {
    documentElement: {},
    getElementById: (id) => (id === 'heatBody' ? host : null),
    querySelectorAll: () => [],
    // the page's served metas: the streaming-state words
    querySelector: () => ({ getAttribute: () => '{"cell": {}, "column": {}}' }),
    addEventListener: (ev, fn) => { (listeners[ev] = listeners[ev] || []).push(fn); },
  },
  getComputedStyle: () => ({ getPropertyValue: () => '' }),
  fetch: (url) => {
    const tk = new URL(url, 'http://x').searchParams.get('ticker');
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(served[tk]) });
  },
  AbortController, Promise, JSON, Math, Number, String, Object, Array, Date, isNaN, URL, console,
};
ctx.window = ctx;
ctx.globalThis = ctx;
// the shell (ed-core.js) as the heatmap uses it: no pan, no expiry selected
ctx.EdShell = {
  getState: () => state, getMeasure: () => 'gex', getExpiry: () => null, setStrike: () => {},
  newPan: () => ({ centre: null, shift: 0, served: null }), panServed: (pan, c) => { pan.served = c; },
  windowQuery: () => '&scope=auto', wireStrikeAxis: () => {},
};
ctx.EdStream = {
  setAdditionalContracts: (symbols, ownerKey) => {
    demandCalls.push({ symbols: symbols.slice(), ownerKey });
    return Promise.resolve({ accepted: true, contracts: symbols });
  },
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

// ---- G: heatmap streamed-contract demand is keyed per ticker, never one shared 'heatmap'
// slot. Viewing META's heatmap must not take over SPY's demand key: EdStream unions the
// demand by ownerKey, so two tickers sharing one key would evict each other.
const strikes = [763, 764, 765];
function surface(ticker) {
  return { available: true, ticker, spot: 764, strikes, live: true, stale: false,
    expirations: [{ expiry: '2026-09-11', dte: 0, expired: false }],
    cells: strikes.map((k) => ({ strike: k, gex: [1000], spot: k === 764, changed: { gex: [false] },
      contracts: [{ call: ticker + 'C' + k, put: ticker + 'P' + k }] })),
    view: { centre: 764, scope: 'auto', note: null, coverage: null, max_abs: { gex: 1000 }, missing_expiry: null,
      demand: strikes.flatMap((k) => [ticker + 'C' + k, ticker + 'P' + k]) } };
}
const settle = () => new Promise((r) => setTimeout(r, 20));
const fire = (ev) => (listeners[ev] || []).forEach((fn) => fn({ detail: {} }));

served.SPY = surface('SPY');
served.META = surface('META');
fire('ed:view');
await settle();
state.ticker = 'META';
fire('ed:ticker');
await settle();
const ownerKeys = demandCalls.map((c) => c.ownerKey);
assert.ok(ownerKeys.includes('heatmap:SPY'), 'SPY render never demanded under heatmap:SPY: ' + JSON.stringify(ownerKeys));
assert.ok(ownerKeys.includes('heatmap:META'), 'META render never demanded under heatmap:META: ' + JSON.stringify(ownerKeys));

// an unavailable result for one ticker clears ONLY that ticker's own slot
demandCalls.length = 0;
served.SPY = { available: false, ticker: 'SPY' };
state.ticker = 'SPY';
fire('ed:ticker');
await settle();
assert.ok(demandCalls.some((c) => c.ownerKey === 'heatmap:SPY' && c.symbols.length === 0),
  'an unavailable SPY surface must clear heatmap:SPY: ' + JSON.stringify(demandCalls));
assert.ok(demandCalls.every((c) => c.ownerKey === 'heatmap:SPY' || c.ownerKey === 'heatmap:META'),
  'no shared/other key is touched: ' + JSON.stringify(demandCalls));

console.log('ed_gamma: all assertions passed');
