/**
 * Node assertions for static/js/l1_sse_guards.js (vm load — no bundler).
 * Run: node tests/l1_sse_guards_node.mjs
 */
import assert from 'assert';
import { readFileSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';
import vm from 'vm';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, '..');
const code = readFileSync(join(ROOT, 'static/js/l1_sse_guards.js'), 'utf8');
vm.runInThisContext(code, { filename: 'l1_sse_guards.js' });

const G = globalThis.EdL1SseGuards;
assert(G && typeof G.normL1ExpiryKey === 'function', 'EdL1SseGuards missing');

// normL1ExpiryKey
assert.strictEqual(G.normL1ExpiryKey(null), '__auto__');
assert.strictEqual(G.normL1ExpiryKey(''), '__auto__');
assert.strictEqual(G.normL1ExpiryKey('2026-04-09'), '2026-04-09');
assert.strictEqual(G.normL1ExpiryKey('2026-04-09T00:00:00'), '2026-04-09');

// l1EnvelopeScopeMatches — cross-scope / inactive ticker
assert.strictEqual(
  G.l1EnvelopeScopeMatches({ ticker: 'SPY', expiry: '__auto__' }, 'SPY', null),
  true,
);
assert.strictEqual(
  G.l1EnvelopeScopeMatches({ ticker: 'QQQ', expiry: '__auto__' }, 'SPY', null),
  false,
);
assert.strictEqual(
  G.l1EnvelopeScopeMatches({ ticker: 'SPY', expiry: '2026-04-10' }, 'SPY', '2026-04-10'),
  true,
);
assert.strictEqual(
  G.l1EnvelopeScopeMatches({ ticker: 'SPY', expiry: '2026-04-11' }, 'SPY', '2026-04-10'),
  false,
);

// Monotonic generation — same rule as renderTierBLight / HTTP+SSE coherence
const store = {};
const sk = 'SPY|';
assert.strictEqual(G.l1ApplyTierBLightMonotonic(sk, 5, store, NaN, {}), true);
assert.strictEqual(store[sk], 5);
assert.strictEqual(G.l1ApplyTierBLightMonotonic(sk, 7, store, NaN, {}), true);
assert.strictEqual(store[sk], 7);
assert.strictEqual(G.l1ApplyTierBLightMonotonic(sk, 6, store, NaN, {}), false);
assert.strictEqual(store[sk], 7, 'stale SSE/HTTP must not downgrade generation');
assert.strictEqual(G.l1ApplyTierBLightMonotonic(sk, 7, store, NaN, {}), true);
assert.strictEqual(store[sk], 7);

// Newer HTTP after SSE: gen 10 already in store; HTTP with gen 9 rejected
const store2 = { [sk]: 10 };
assert.strictEqual(G.l1ApplyTierBLightMonotonic(sk, 9, store2, NaN, {}), false);

// Newer SSE after HTTP: gen 8 in store; SSE gen 9 accepted
const store3 = { [sk]: 8 };
assert.strictEqual(G.l1ApplyTierBLightMonotonic(sk, 9, store3, NaN, {}), true);
assert.strictEqual(store3[sk], 9);

// Same generation + older _server_build_ts rejected (reordered HTTP vs SSE)
const gen4 = {};
const ts4 = {};
assert.strictEqual(G.l1ApplyTierBLightMonotonic(sk, 5, gen4, 200, ts4), true);
assert.strictEqual(G.l1ApplyTierBLightMonotonic(sk, 5, gen4, 100, ts4), false);
assert.strictEqual(gen4[sk], 5);
assert.strictEqual(ts4[sk], 200);

// Same generation + same or newer ts accepted
const gen5 = {};
const ts5 = {};
assert.strictEqual(G.l1ApplyTierBLightMonotonic(sk, 5, gen5, 200, ts5), true);
assert.strictEqual(G.l1ApplyTierBLightMonotonic(sk, 5, gen5, 200, ts5), true);
assert.strictEqual(G.l1ApplyTierBLightMonotonic(sk, 5, gen5, 201, ts5), true);
assert.strictEqual(ts5[sk], 201);

console.log('l1_sse_guards_node: ok');
