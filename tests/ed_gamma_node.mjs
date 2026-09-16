/**
 * RC-UI-1 — node assertions for static/js/ed-gamma.js heatmap presentation helpers.
 * Run: node tests/ed_gamma_node.mjs
 *
 * Proves the operator's frontend invariants D (sign -> colour, no inversion) and E (the
 * displayed dollar text is FORMATTING-ONLY and equals the backend value). These CALL the real
 * functions (a source-text test cannot detect a wrong colour, only a missing one).
 */
import assert from 'assert';
import { readFileSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';
import vm from 'vm';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, '..');
vm.runInThisContext(readFileSync(join(ROOT, 'static/js/ed-gamma.js'), 'utf8'),
  { filename: 'ed-gamma.js' });

const G = globalThis.EdGamma;
assert(G && typeof G.formatUsd === 'function' && typeof G.cellStyle === 'function', 'EdGamma missing');

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
  const s = G.formatUsd(v);
  assert.strictEqual(s.startsWith('-'), v < 0, 'formatUsd changed sign for ' + v);
}

// ---- D: sign -> colour, no inversion (theme-aware solid fills, interpolated from heat tokens) ----
const HEAT = { pos: [35, 192, 107], neg: [229, 72, 77], zero: [18, 26, 37] };
function rgb(s) { const m = /rgb\((\d+),(\d+),(\d+)\)/.exec(s || ''); return m ? [+m[1], +m[2], +m[3]] : null; }

const pos = rgb(G.cellStyle(500000, 1000000, HEAT).bg);
const neg = rgb(G.cellStyle(-500000, 1000000, HEAT).bg);
assert.ok(pos[1] > pos[0] && pos[1] > pos[2], 'positive cell is not green-dominant');   // G channel wins
assert.ok(neg[0] > neg[1] && neg[0] > neg[2], 'negative cell is not red-dominant');     // R channel wins
assert.strictEqual(G.cellStyle(500000, 1000000, HEAT).sign, 1);
assert.strictEqual(G.cellStyle(-500000, 1000000, HEAT).sign, -1);

// larger |magnitude| -> stronger fill (monotone toward full green, same sign, no inversion)
const gLow = rgb(G.cellStyle(200000, 1000000, HEAT).bg)[1];
const gHigh = rgb(G.cellStyle(900000, 1000000, HEAT).bg)[1];
assert.ok(gHigh > gLow, 'shade intensity is not monotone in |value|');

// null -> empty; near-zero recedes to the theme's zero colour, never a signed fill
assert.strictEqual(G.cellStyle(null, 1000000, HEAT).empty, true);
assert.deepStrictEqual(rgb(G.cellStyle(0.4, 1000000, HEAT).bg), [18, 26, 37], 'near-zero cell is not the recede colour');

// a DIFFERENT theme palette must still map positive->its green and negative->its red (no inversion)
const LIGHT = { pos: [26, 158, 92], neg: [214, 59, 59], zero: [230, 235, 241] };
assert.ok(rgb(G.cellStyle(800000, 1000000, LIGHT).bg)[1] > rgb(G.cellStyle(800000, 1000000, LIGHT).bg)[0], 'light-theme positive not green-dominant');
assert.ok(rgb(G.cellStyle(-800000, 1000000, LIGHT).bg)[0] > rgb(G.cellStyle(-800000, 1000000, LIGHT).bg)[1], 'light-theme negative not red-dominant');

// nearestStrikeIndex is a pure locator (spot highlight), no math on values
assert.strictEqual(G.nearestStrikeIndex([90, 100, 110], 101), 1);
assert.strictEqual(G.nearestStrikeIndex([90, 100, 110], 104.9), 1);

// ---- F: heatmap rows render highest strike at the top, lowest at the bottom (operator
// finding, 2026-09-11) -- calls the REAL renderSurface against a minimal DOM/EdShell stub,
// so this proves actual row order and actual per-row strike/gex binding, not source text.
global.document = {
  documentElement: {},
  getElementById: () => null,
  querySelectorAll: () => [],
  addEventListener: () => {},
};
global.window = {};
global.getComputedStyle = () => ({ getPropertyValue: () => '' });

function makeHost() {
  return { innerHTML: '', querySelector: () => null, querySelectorAll: () => [] };
}

const strikes = [759, 760, 761, 762, 763, 764, 765, 766, 767, 768, 769]; // ascending, as the API serves them
const cells = strikes.map((k, i) => ({ strike: k, gex: [1000 * (i + 1)] }));
const surface = {
  available: true,
  spot: 764,
  strikes,
  cells,
  expirations: [{ expiry: '2026-09-11', dte: 0, expired: false }],
  live: true,
  stale: false,
};

const host1 = makeHost();
G.renderSurface(host1, surface);
const rowStrikes = [...host1.innerHTML.matchAll(/data-strike="(\d+)"/g)].map((m) => Number(m[1]));
// one data-strike per <td> per row (single expiry column here) -> one value per row, in
// render order
assert.deepStrictEqual(rowStrikes, [...strikes].reverse(),
  'heatmap rows must descend from the highest strike to the lowest');

// each row's own gex value travels with its own strike (no cross-row value shuffle from the
// reversal -- this is the "preserve identity" requirement, checked against the real cell text)
const rows = [...host1.innerHTML.matchAll(/data-strike="(\d+)"[^>]*data-gex="(-?\d+)"/g)];
for (const [, strikeStr, gexStr] of rows) {
  const strike = Number(strikeStr);
  const expectedGex = cells[strikes.indexOf(strike)].gex[0];
  assert.strictEqual(Number(gexStr), expectedGex, `strike ${strike} lost its own gex value under reversal`);
}

// the "all available" fallback path (no EdShell.scopeSelect) must ALSO descend -- this is the
// path a bare surface actually exercises when EdShell is absent, and it is the same path real
// scopeSelect output flows through, so this proves the render loop's own reversal, not a
// scopeSelect-specific behaviour.
const host2 = makeHost();
G.renderSurface(host2, { ...surface, strikes: [100, 200, 300], cells: [
  { strike: 100, gex: [1] }, { strike: 200, gex: [2] }, { strike: 300, gex: [3] },
] });
const rowStrikes2 = [...host2.innerHTML.matchAll(/data-strike="(\d+)"/g)].map((m) => Number(m[1]));
assert.deepStrictEqual(rowStrikes2, [300, 200, 100]);

console.log('ed_gamma: all assertions passed');
