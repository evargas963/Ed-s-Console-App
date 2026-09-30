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
// the page loads options_subscription.js before ed-stream.js
const subSrc = fs.readFileSync(path.join(root, 'static', 'js', 'options_subscription.js'), 'utf8');

function load(respond) {
  const posts = [];
  const listeners = {};
  const intervals = [];
  // ed-core.js (loaded first) owns the view's id and announces a push connection opening
  // after the view was without one
  const window = { EdShell: { viewId: 'view-under-test' } };
  const ctx = {
    window,
    document: { addEventListener: (ev, fn) => { listeners[ev] = fn; } },
    setInterval: (fn, ms) => { intervals.push({ fn, ms }); return intervals.length; },
    fetch: (url, init) => {
      const body = JSON.parse(init.body);
      posts.push({ url, body });
      const { status, json } = respond(body);
      return Promise.resolve({ status, json: () => Promise.resolve(json) });
    },
    Promise, JSON, String, Object, Array, Math, Date,
  };
  vm.createContext(ctx);
  vm.runInContext(subSrc, ctx);
  window.EdOptionsSubscription = ctx.EdOptionsSubscription;
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

// 4. The push connection holds the demand: no timer re-posts it, and when a connection opens
//    after the view was without one (`ed:push_open`) the view declares it again (the server
//    released it when the last one closed).
{
  const { S, posts, listeners, intervals } = load(serverAck);
  assert.equal(intervals.length, 0, 'no timer keeps the demand alive');
  listeners['ed:push_open']();
  assert.equal(posts.length, 0, 'nothing declared, nothing to declare again');
  await S.setAdditionalContracts(['A', 'B', 'C'], 'heatmap:SPY');
  listeners['ed:push_open']();
  assert.equal(posts.length, 2);
  assert.deepEqual(posts[1].body.contracts, ['A', 'B', 'C']);
  assert.ok(posts[1].body.seq > posts[0].body.seq);
}

// 5. A declaration the server refused because the connection was not open yet is declared
//    again when it opens, and only then counts as confirmed.
{
  let connected = false;
  const { S, posts, listeners } = load((body) => connected ? serverAck(body)
    : { status: 409, json: { ok: false, not_connected: true, client_id: body.client_id, seq: body.seq } });
  const refused = await S.setAdditionalContracts(['A'], 'heatmap:SPY');
  assert.equal(refused.accepted, false);
  connected = true;
  listeners['ed:push_open']();
  await new Promise((r) => setTimeout(r, 0));
  assert.deepEqual(posts.map((p) => p.body.contracts), [['A'], ['A']]);
  const again = await S.setAdditionalContracts(['A'], 'heatmap:SPY');
  assert.equal(again.unchanged, true, 'confirmed by the declaration made on open');
}

console.log('ed_stream_demand_node: all assertions passed');
