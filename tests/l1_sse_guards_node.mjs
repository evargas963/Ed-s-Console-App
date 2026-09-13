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

// l1PayloadMatchesActiveScope — L1-SSE-AUTO-ACCEPT (2026-07-22)
// THE live defect case: auto mode (activeExpiry null) + payload carrying the
// RESOLVED expiry must be ACCEPTED (old strict equality rejected 100% of
// delivered payloads: rejectedTierBRender=2076 / accepted=0 on a live tab).
assert.strictEqual(
  G.l1PayloadMatchesActiveScope('SPY', '2026-07-22', 'SPY', null),
  true,
  'auto mode must accept the resolved-expiry payload',
);
assert.strictEqual(
  G.l1PayloadMatchesActiveScope('SPY', null, 'SPY', null),
  true,
  'auto mode accepts unresolved payloads too',
);
assert.strictEqual(
  G.l1PayloadMatchesActiveScope('QQQ', '2026-07-22', 'SPY', null),
  false,
  'wrong ticker never accepted',
);
assert.strictEqual(
  G.l1PayloadMatchesActiveScope('SPY', '2026-07-22', 'SPY', '2026-07-22'),
  true,
  'pinned expiry accepts matching payload',
);
assert.strictEqual(
  G.l1PayloadMatchesActiveScope('SPY', '2026-07-25', 'SPY', '2026-07-22'),
  false,
  'pinned expiry stays strict — mismatched payload rejected',
);
assert.strictEqual(
  G.l1PayloadMatchesActiveScope('', '2026-07-22', 'SPY', null),
  false,
  'missing payload ticker rejected',
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

// makeCoalescedLoader (RC-UI-1 round 7, 2026-09-13) — the fix for a controlled, measured
// production failure: server.py's gamma_surface_seq SSE push fires on every streamed
// publish, dispatched client-side as the SAME `ed:refresh{slow}` event the 12s poll tick
// uses. Every gamma view module's load() bumped a per-call generation counter and only
// applied a response whose generation still matched on arrival — correct for invalidating
// a stale context, but once triggers arrive faster than the round trip, NO response's
// generation ever survives, so the display freezes until traffic stops. Reproduced with real
// numbers: 500ms triggers against a 750ms round trip left the heatmap showing $1,000 while
// incoming values had already advanced past $7,000, updating only once the pushes stopped.
assert(typeof G.makeCoalescedLoader === 'function', 'makeCoalescedLoader missing');
{
  let calls = 0;
  let resolvers = [];
  function run() { calls++; return new Promise((res) => { resolvers.push(res); }); }
  const loader = G.makeCoalescedLoader(run);

  loader.trigger();
  assert.strictEqual(calls, 1, 'first trigger starts a call immediately');

  // The exact defect: a burst of triggers arrives while the one call is still in flight
  // (this is what "notifications every 500ms, response takes 750ms" looks like). A naive
  // per-trigger fetch would start 3 more overlapping calls here (and orphan the first).
  loader.trigger();
  loader.trigger();
  loader.trigger();
  assert.strictEqual(calls, 1, 'triggers arriving mid-flight must not start overlapping calls');

  // Settling the in-flight call must apply immediately AND fire exactly one trailing call —
  // the burst is coalesced to one, never dropped (freeze) and never replayed per-trigger
  // (pile-up).
  resolvers[0]();
  await Promise.resolve(); await Promise.resolve();
  assert.strictEqual(calls, 2, 'a coalesced burst must fire exactly one trailing call, not zero (freeze) and not three (pile-up)');

  resolvers[1]();
  await Promise.resolve(); await Promise.resolve();
  assert.strictEqual(calls, 2, 'no trigger arrived mid-flight this time -> settling must not spawn a third call');

  // Once fully idle, a fresh trigger starts immediately — nothing is left permanently stuck.
  loader.trigger();
  assert.strictEqual(calls, 3, 'idle loader answers the next trigger immediately');
  resolvers[2]();
  await Promise.resolve();
}
{
  // Direct reproduction of the measured scenario: 6 triggers fired back-to-back (modelling
  // pushes ~500ms apart) against one slow (~750ms) load. The failure this fixes made EVERY
  // one of these triggers' responses arrive too late to apply — this must instead make
  // exactly ONE call, then exactly one trailing call, then go idle: bounded work, nothing
  // dropped, no permanent freeze.
  let calls = 0;
  let resolvers = [];
  function run() { calls++; return new Promise((res) => { resolvers.push(res); }); }
  const loader = G.makeCoalescedLoader(run);
  for (let i = 0; i < 6; i++) loader.trigger();
  assert.strictEqual(calls, 1, 'a burst of triggers only ever starts ONE call');
  resolvers[0]();
  await Promise.resolve(); await Promise.resolve();
  assert.strictEqual(calls, 2, 'the burst coalesces to exactly one trailing call once the first settles');
  resolvers[1]();
  await Promise.resolve(); await Promise.resolve();
  assert.strictEqual(calls, 2, 'traffic stopped -> the loader goes idle instead of chasing a phantom third call');
}
{
  // A run() that throws synchronously must still settle (and honor a coalesced trailing
  // trigger) rather than wedging the loader in "in flight" forever.
  let calls = 0;
  function run() { calls++; if (calls === 1) throw new Error('boom'); return null; }
  const loader = G.makeCoalescedLoader(run);
  assert.throws(() => loader.trigger(), /boom/);
  loader.trigger();
  assert.strictEqual(calls, 2, 'a synchronous throw must still settle the loader, not wedge it in-flight forever');
}

console.log('l1_sse_guards_node: ok');
