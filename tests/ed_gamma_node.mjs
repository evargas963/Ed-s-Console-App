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

// ---- D: sign -> colour, no inversion ----
const pos = G.cellStyle(500000, 1000000);
const neg = G.cellStyle(-500000, 1000000);
assert.ok(pos.bg.includes('35,192,107'), 'positive GEX is not green');
assert.ok(neg.bg.includes('229,72,77'), 'negative GEX is not red');
assert.ok(!pos.bg.includes('229,72,77'), 'positive rendered with red (sign inversion)');
assert.ok(!neg.bg.includes('35,192,107'), 'negative rendered with green (sign inversion)');

// larger magnitude -> stronger fill (monotone intensity, same sign)
const a1 = parseFloat(G.cellStyle(200000, 1000000).bg.match(/,([0-9.]+)\)/)[1]);
const a2 = parseFloat(G.cellStyle(900000, 1000000).bg.match(/,([0-9.]+)\)/)[1]);
assert.ok(a2 > a1, 'shade intensity is not monotone in |value|');

// null / near-zero recede, never coloured
assert.strictEqual(G.cellStyle(null, 1000000).empty, true);
assert.ok(!G.cellStyle(0.4, 1000000).bg.includes('35,192,107'), 'a ~zero cell was painted as signed');

// nearestStrikeIndex is a pure locator (spot highlight), no math on values
assert.strictEqual(G.nearestStrikeIndex([90, 100, 110], 101), 1);
assert.strictEqual(G.nearestStrikeIndex([90, 100, 110], 104.9), 1);

console.log('ed_gamma: all assertions passed');
