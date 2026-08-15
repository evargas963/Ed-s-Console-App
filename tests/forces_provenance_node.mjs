/**
 * RC-304 — node assertions for static/js/forces_provenance.js (vm load — no bundler).
 * Run: node tests/forces_provenance_node.mjs
 *
 * These CALL the real function (RC-298: a test that reads source text cannot detect a wrong
 * label, only a missing one). /api/forces sums ΔOI across two banked captures and DEX/CHARM
 * across the newer one alone, so the older date must never reach the DEX or CHARM label.
 */
import assert from 'assert';
import { readFileSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';
import vm from 'vm';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, '..');
vm.runInThisContext(readFileSync(join(ROOT, 'static/js/forces_provenance.js'), 'utf8'),
  { filename: 'forces_provenance.js' });

const P = globalThis.EdForcesProvenance;
assert(P && typeof P.forcesRowSource === 'function', 'EdForcesProvenance missing');
const src = P.forcesRowSource;

const FULL = {
  available: true,
  older_et_date: '2026-08-05', newer_et_date: '2026-08-06',
  charm_below: -1200.5, charm_above: 880.25,
  charm_book_scope: 'full_chain_banked',
  charm_error: null,
};

// ΔOI is the ONE row that differences two captures, so it keeps the span.
assert.strictEqual(src(FULL, 'doi'), 'banked 2026-08-05→2026-08-06');

// DEX and CHARM are summed on the newer capture alone. The defect was the older date here.
assert.ok(!src(FULL, 'dex').includes('2026-08-05'),
  'DEX still advertises the older capture it never summed');
assert.ok(!src(FULL, 'charm').includes('2026-08-05'),
  'CHARM still advertises the older capture it never summed');
assert.ok(src(FULL, 'dex').includes('2026-08-06'), 'DEX lost the capture it did sum');

// The book scope rides the charm label — the whole point of RC-288.
assert.ok(src(FULL, 'charm').includes('full_chain_banked'),
  'charm label does not state which book it covered');

// A one-expiry charm must be distinguishable from a whole-book charm.
const ONE = { ...FULL, charm_book_scope: 'single_expiry_banked:2026-08-14' };
assert.ok(src(ONE, 'charm').includes('single_expiry_banked:2026-08-14'));
assert.notStrictEqual(src(ONE, 'charm'), src(FULL, 'charm'),
  'one expiry and the whole book render identically');

// A FAILED charm says so instead of hiding behind a confident banked label (RC-274).
const ERR = { ...FULL, charm_below: null, charm_above: null,
  charm_error: 'charm_by_strike empty on newer banked chain' };
assert.ok(src(ERR, 'charm').toLowerCase().includes('charm failed'),
  'a failed charm renders like one that is merely loading');

// Served but empty, with no error: still not silence.
const NONE = { ...FULL, charm_below: null, charm_above: null, charm_error: null };
assert.ok(src(NONE, 'charm').includes('charm not served'));

// Absence stays absence — no fabricated span from a missing date (RC-301).
assert.strictEqual(src({ available: true, newer_et_date: '2026-08-06' }, 'doi'),
  'banked pair — date unknown');
assert.strictEqual(src({ available: true, older_et_date: '2026-08-05' }, 'dex'),
  'banked — date unknown');
const NOSCOPE = { available: true, newer_et_date: '2026-08-06', charm_below: 1.0 };
assert.ok(src(NOSCOPE, 'charm').includes('book scope unknown'),
  'a charm with no served scope claims a scope');

// Unavailable payload: the server's reason, never an invented label.
assert.strictEqual(src({ available: false, reason: 'forces read failed: no rows' }, 'charm'),
  'forces read failed: no rows');
assert.strictEqual(src(null, 'dex'), 'banked chains — loading');

console.log('forces_provenance: all assertions passed');
