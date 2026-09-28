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
assert(G, 'EdL1SseGuards missing');

// makeCoalescedLoader: triggers faster than the round trip never freeze or pile up
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

// makeCoalescedLoader ROUND 8 (2026-09-13) — context-change abort. Independent-review
// finding, REPRODUCED: the round-7 loader coalesced EVERY trigger into the SAME in-flight
// slot regardless of context, so a held/slow request for an ABANDONED ticker (or contract,
// or strike) blocked the newly-selected one from ever loading -- e.g. switch ticker while
// the previous ticker's fetch is artificially delayed, and the new ticker's panel never
// loads until the old one finally settles (or never, if it hangs). Fixed with a keyed
// trigger(key): same key as the in-flight request still coalesces (unchanged), a
// DIFFERENT key aborts the in-flight request and starts the new one immediately.
{
  let calls = 0;
  const runs = [];   // { key, signal }
  function run(signal) {
    const rec = { key: runs.length, signal };
    runs.push(rec);
    calls++;
    return new Promise((res, rej) => { rec.res = res; rec.rej = rej; });
  }
  const loader = G.makeCoalescedLoader(run);

  loader.trigger('A');
  assert.strictEqual(calls, 1, 'first trigger for context A starts immediately');
  assert.strictEqual(runs[0].signal.aborted, false, 'a fresh request is not pre-aborted');

  // The exact defect: a DIFFERENT context (B) is requested while A is still in flight.
  // The old coalescing behavior would have silently merged this into "run once more when
  // A finishes" -- B must never wait for A.
  loader.trigger('B');
  assert.strictEqual(calls, 2, 'a context change must start the new context immediately, not wait for the old one');
  assert.strictEqual(runs[0].signal.aborted, true, "the abandoned context A's in-flight request must be aborted");
  assert.strictEqual(runs[1].signal.aborted, false, 'the new context B request is not itself aborted');

  // A's aborted request settling LATE (its real-world equivalent: fetch's AbortError
  // rejection, which arrives asynchronously) must not corrupt B's now-current state.
  runs[0].rej(Object.assign(new Error('aborted'), { name: 'AbortError' }));
  await Promise.resolve(); await Promise.resolve();
  assert.strictEqual(calls, 2, "A's stale settle must not spawn a spurious third call");

  // A same-key trigger while B is in flight still coalesces (round-7 behavior preserved).
  loader.trigger('B');
  assert.strictEqual(calls, 2, 'same-key trigger mid-flight coalesces, does not abort/restart');
  assert.strictEqual(runs[1].signal.aborted, false, 'coalescing a same-key trigger must not abort the in-flight request');

  runs[1].res({ ok: true });
  await Promise.resolve(); await Promise.resolve();
  assert.strictEqual(calls, 3, 'the coalesced same-key trigger fires its one trailing call once B settles');
  assert.strictEqual(runs[2].key, 2);

  runs[2].res({ ok: true });
  await Promise.resolve(); await Promise.resolve();
  assert.strictEqual(calls, 3, 'fully settled with nothing pending -> idle, no phantom fourth call');

  // reset() aborts whatever is currently in flight.
  loader.trigger('C');
  assert.strictEqual(calls, 4);
  assert.strictEqual(runs[3].signal.aborted, false);
  loader.reset();
  assert.strictEqual(runs[3].signal.aborted, true, 'reset() must abort the in-flight request');
  runs[3].rej(Object.assign(new Error('aborted'), { name: 'AbortError' }));
  await Promise.resolve(); await Promise.resolve();
  loader.trigger('D');
  assert.strictEqual(calls, 5, 'the loader is usable again immediately after reset()');
}

console.log('l1_sse_guards_node: ok');
