// Per-view option-contract demand (2026-09-24) -- runs the REAL static/js/ed-stream.js
// against a stubbed fetch. MEASURED that day: one last-writer-wins server slot let two views
// replace each other's contracts on every render, and a view confirmed its demand against
// the server's budgeted union, which never matches a demand over the 200-contract budget --
// so every render re-posted. Both drove the capture daemon to swap ~200 subscriptions on the
// shared Schwab socket every few seconds until the socket died.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const src = fs.readFileSync(path.join(root, 'static', 'js', 'ed-stream.js'), 'utf8');

function load(respond) {
  const posts = [];
  const listeners = {};
  const intervals = [];
  const window = {
    crypto: { randomUUID: () => 'view-under-test' },
    addEventListener: (ev, fn) => { listeners[ev] = fn; },
  };
  const ctx = {
    window,
    setInterval: (fn, ms) => { intervals.push({ fn, ms }); return intervals.length; },
    fetch: (url, init) => {
      const body = JSON.parse(init.body);
      posts.push({ url, body, keepalive: init.keepalive });
      const { status, json } = respond(body);
      return Promise.resolve({ status, json: () => Promise.resolve(json) });
    },
    Promise, JSON, String, Object, Array, Math, Date,
  };
  vm.createContext(ctx);
  vm.runInContext(src, ctx);
  return { S: window.EdStream, posts, listeners, intervals };
}

// The real server's acknowledgement: this view's recorded demand, and a budgeted union.
const BUDGET = 2;
const serverAck = (body) => ({ status: 200, json: {
  ok: true, client_id: body.client_id, seq: body.seq,
  requested: [...body.contracts].sort(), contracts: [...body.contracts].sort().slice(0, BUDGET) } });

// 1. Every declaration carries this view's id and an increasing seq.
{
  const { S, posts } = load(serverAck);
  await S.setAdditionalContracts(['A'], 'heatmap:SPY');
  await S.setAdditionalContracts(['A', 'B'], 'heatmap:SPY');
  assert.deepEqual(posts.map((p) => p.body.client_id), ['view-under-test', 'view-under-test']);
  assert.deepEqual(posts.map((p) => p.body.seq), [1, 2]);
}

// 2. A demand OVER the budget is confirmed against `requested`, and re-rendering the same
//    demand sends nothing (it used to re-post on every render).
{
  const { S, posts } = load(serverAck);
  const res = await S.setAdditionalContracts(['A', 'B', 'C', 'D'], 'heatmap:SPY');
  assert.equal(res.accepted, true, 'an over-budget demand the server recorded is confirmed');
  const again = await S.setAdditionalContracts(['D', 'C', 'B', 'A'], 'heatmap:SPY');
  assert.equal(again.unchanged, true);
  assert.equal(posts.length, 1, 're-rendering an unchanged demand must not re-post');
}

// 3. An acknowledgement for another view, or another seq, is not this view's confirmation.
for (const tamper of [{ client_id: 'other-view' }, { seq: 99 }, { requested: ['A'] }]) {
  const { S } = load((body) => { const a = serverAck(body); Object.assign(a.json, tamper); return a; });
  const res = await S.setAdditionalContracts(['A', 'B'], 'heatmap:SPY');
  assert.equal(res.accepted, false, 'tampered ack accepted: ' + JSON.stringify(tamper));
}

// 4. A live view refreshes its lease; an empty or unconfirmed one does not.
{
  const { S, posts, intervals } = load(serverAck);
  assert.equal(intervals.length, 1);
  assert.ok(intervals[0].ms <= 45000, 'refresh well inside the server lease (90 s)');
  intervals[0].fn();
  assert.equal(posts.length, 0, 'nothing declared, nothing to refresh');
  await S.setAdditionalContracts(['A', 'B', 'C'], 'heatmap:SPY');
  intervals[0].fn();
  assert.equal(posts.length, 2);
  assert.deepEqual(posts[1].body.contracts, ['A', 'B', 'C']);
  assert.ok(posts[1].body.seq > posts[0].body.seq);
}

// 5. Leaving the page releases this view's demand with a keepalive request.
{
  const { S, posts, listeners } = load(serverAck);
  await S.setAdditionalContracts(['A'], 'heatmap:SPY');
  listeners.pagehide();
  const last = posts[posts.length - 1];
  assert.deepEqual(last.body.contracts, []);
  assert.equal(last.keepalive, true);
  assert.equal(last.body.client_id, 'view-under-test');
}

console.log('ed_stream_demand_node: all assertions passed');
