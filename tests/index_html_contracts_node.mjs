/**
 * RC-308 / RC-310 — node assertions for the pure functions static/index.html exports.
 * Run: node tests/index_html_contracts_node.mjs
 *
 * Three tests in tests/test_issue18_ui_contract.py asserted the SPELLING of this function's
 * branches — `"if (!tradeable) nonActionable = true"`, `"if (tradeable && dir === 'LONG')"`.
 * RC-133 v27 rewrote those branches to be STRICTER (nonActionable now flags only a withheld
 * LONG/SHORT; the tradeable check moved to an else-if chain) and the tests went red on the
 * improvement, while a genuine regression would have looked identical. The function is
 * exported to `window.resolveHorizonCardVisualState`, so its contract can simply be run.
 */
import assert from 'assert';
import { readFileSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';
import vm from 'vm';

const __dirname = dirname(fileURLToPath(import.meta.url));
const html = readFileSync(join(__dirname, '..', 'static/index.html'), 'utf8');

const START = 'function resolveHorizonCardVisualState(';
const i = html.indexOf(START);
assert(i !== -1, 'resolveHorizonCardVisualState is gone from static/index.html');
const end = html.indexOf('\ntry { window.resolveHorizonCardVisualState', i);
assert(end !== -1, 'the window export of resolveHorizonCardVisualState is gone');
vm.runInThisContext(html.slice(i, end), { filename: 'index.html#resolveHorizonCardVisualState' });
const R = globalThis.resolveHorizonCardVisualState;
assert(typeof R === 'function');

// --- tradeable: direction paints, and the colour class is the direction's ---------------
const long = R('1c', 'LONG', true, 80);
assert.strictEqual(long.state, 'up', 'a tradeable LONG does not paint up');
assert.strictEqual(long.sigDir, 'long');
assert.strictEqual(long.dirText, 'LONG');
assert.strictEqual(long.nonActionable, false);

const short = R('5c', 'SHORT', true, 50);
assert.strictEqual(short.state, 'down');
assert.strictEqual(short.sigDir, 'short');

// --- NOT tradeable: RC-133 v27 — no slug emits ANY directional vocabulary ---------------
for (const slug of ['1c', '5c', '15c', '60c', 'consolidated']) {
  const v = R(slug, 'LONG', false, 90);
  assert.strictEqual(v.state, 'dim', `${slug} painted a direction under !tradeable`);
  assert.strictEqual(v.sigDir, 'neutral', `${slug} leaked a directional attribute`);
  assert.strictEqual(v.glow, '', `${slug} kept its glow under !tradeable`);
  assert.strictEqual(v.nonActionable, true,
    `${slug} lost the flag that lets the card explain WHY it is dim`);
  assert.ok(!/LONG|SHORT/.test(v.dirText), `${slug} printed ${v.dirText} under !tradeable`);
  assert.ok(!/LONG|SHORT/.test(v.dirAttr), `${slug} styled on ${v.dirAttr} under !tradeable`);
}
// The consolidated pill reads NEUTRAL; the per-horizon pills read as withheld.
assert.strictEqual(R('consolidated', 'LONG', false, 90).dirText, 'NEUTRAL');
assert.strictEqual(R('1c', 'LONG', false, 90).dirText, '—');

// A withheld FLAT is not "non-actionable direction" — nothing was withheld.
assert.strictEqual(R('1c', 'FLAT', false, 50).nonActionable, false);

// --- UNAVAILABLE is its own state, never neutral ----------------------------------------
const un = R('1c', 'UNAVAILABLE', true, 70);
assert.strictEqual(un.sigDir, 'unavailable');
assert.strictEqual(un.dirText, 'UNAVAILABLE');
assert.strictEqual(un.dirAttr, 'UNAVAILABLE');

// --- glow tiers follow confidence, and only on a painted direction ----------------------
assert.strictEqual(R('1c', 'LONG', true, 76).glow, 'tf-glow-3');
assert.strictEqual(R('1c', 'LONG', true, 75).glow, 'tf-glow-2');
assert.strictEqual(R('1c', 'LONG', true, 61).glow, 'tf-glow-2');
assert.strictEqual(R('1c', 'LONG', true, 60).glow, 'tf-glow-1');
assert.strictEqual(R('1c', 'LONG', true, null).glow, 'tf-glow-1');
assert.strictEqual(R('1c', 'FLAT', true, 90).glow, '', 'a FLAT card glowed');

// ========================================================================================
// RC-310 — rUnitsText: the Call card's size fallback.
//
// The slot used to pass a NUMERIC `s.r_units` straight to `fstr()`, which returns the first
// non-empty STRING, so the fallback could not fire for any value and the operator saw an
// em-dash where a real size existed. `r_units = 0` is a real size, not an absence.
// ========================================================================================
const rStart = html.indexOf('function rUnitsText(');
assert(rStart !== -1, 'rUnitsText is gone from static/index.html');
const rEnd = html.indexOf('try { window.rUnitsText', rStart);
assert(rEnd !== -1, 'the window export of rUnitsText is gone');
vm.runInThisContext(html.slice(rStart, rEnd), { filename: 'index.html#rUnitsText' });
const rU = globalThis.rUnitsText;
assert(typeof rU === 'function');

assert.strictEqual(rU(0), '0.00 R', 'zero risk units rendered as absence — 0 R is a real size');
assert.strictEqual(rU(2.5), '2.50 R');
assert.strictEqual(rU(-1.25), '-1.25 R');
for (const bad of [null, undefined, NaN, Infinity, -Infinity, '2.5', {}]) {
  assert.strictEqual(rU(bad), null, `a non-number (${String(bad)}) produced a size`);
}

// The slot itself: prose cues win, the number is the fallback, and nothing numeric reaches
// fstr() any more.
const slotIdx = html.indexOf("T('cv2-c-size'");
assert(slotIdx !== -1, "the Call card's size slot is gone");
const slot = html.slice(slotIdx, slotIdx + 200);
assert(slot.includes('rUnitsText(s.r_units)'), 'the size slot no longer renders risk units');
assert(!/fstr\([^)]*r_units/.test(slot),
  'r_units is back inside fstr(), where a number can never render');

console.log('index_html_contracts: all assertions passed');
