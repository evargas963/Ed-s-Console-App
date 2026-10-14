// The console's push to the page (/api/live, server.live_values), with each panel's value from the
// spec's own stubs. The page's view ({op:'view'}) goes to the real test server, which answers as
// the console does (Schwab's own values come from the daemon's socket instead,
// tests/e2e/fixtures/price_socket.js): which panels are on screen ({type:'view', seq, moved, shown}), each one's answer by name
// ({type:'panels', seq, panels: [{panel, source, kinds, ...}]}) and the beat ({type:'feed'}).
// Each answer is replaced by what
// the spec's stubs serve for its `source` (page.route), as the console serves its route's own
// answer, and stamped with the view the console holds when it is sent, as the console stamps it.
// A spec that pushes a change does it as the console's stream of change kinds did
// (page.route('**/api/changes**', ... text/event-stream)): each `event: <kind>` it serves is
// pushed as the console pushes it -- every panel on screen that the kind moves, answered again;
// `event: session` is the session label. The console's own push is proven against the real server
// in tests/test_live_values_push_v1.py.
const base = require('@playwright/test');

async function answer(page, url) {
  return page.evaluate(async (u) => {
    try {
      const r = await fetch(u, { cache: 'no-store' });
      let body = null;
      try { body = await r.json(); } catch (e) { body = null; }
      return { status: r.status, body: body };
    } catch (e) { return { status: 0, body: null }; }
  }, url).catch(() => ({ status: 0, body: null }));   // the page navigated or the test ended
}

//: each page's open push, for pushChange
const _push = new WeakMap();
//: each page's open push, for pushBeat
const _beat = new WeakMap();

// The console's beat with each shown panel's instants' ages ({kind: label}), as server.live_values
// serves it every second (STAND-IN: the ages are the spec's).
function pushBeat(page, asOfAges) {
  const b = _beat.get(page);
  if (b) b(asOfAges);
}

// The console pushes a change of `kind` for the page's ticker: every panel on screen that it
// moves, answered again (through the spec's stubs).
async function pushChange(page, kind) {
  const p = _push.get(page);
  if (p) await p(kind);
}

//: each page's stand-in outages: panel -> the console's not_live reasons for it
const _notLive = new WeakMap();

// The console marks `panel` not live with `reason` (STAND-IN: the test server has no Schwab feed
// to go down): its answers from now on carry it, as the console's `not_live` (its reasons).
function setNotLive(page, panel, reason) {
  if (!_notLive.has(page)) _notLive.set(page, {});
  _notLive.get(page)[panel] = [reason];
}

//: each page's open push, for pushDown; the pages whose console push is down
const _socket = new WeakMap();
const _down = new WeakSet();

// The console's push to `page` goes down and stays down: the open socket closes and every
// reconnect is closed at once, as when the console has stopped.
function pushDown(page) {
  _down.add(page);
  const ws = _socket.get(page);
  if (ws) ws.close();
}

async function installLive(page) {
  await page.routeWebSocket(/\/api\/live$/, (ws) => {
    if (_down.has(page)) { ws.close(); return; }
    _socket.set(page, ws);
    //: each panel on screen -> the console's newest message for it (its source and kinds)
    const shown = new Map();
    //: each route's answer from the stubs while it is being read, by change: one read per route
    //: and change, however many panels show it, as the console computes each route once per
    //: change (server._answers); a new change reads afresh, never the old change's read
    const reading = new Map();
    let change = 0;
    //: the console's answers under a view older than the page's newest: held until the console
    //: takes the newest, then read or dropped as the page draws or drops them
    let held = [];
    let seq = null, pageSeq = null, ticker = null, closed = false, session = null;
    const send = (m) => { if (!closed) { try { ws.send(JSON.stringify(m)); } catch (e) { closed = true; } } };
    ws.onClose(() => { closed = true; });
    function read(source) {
      const key = change + ' ' + source;
      if (!reading.has(key)) {
        reading.set(key, answer(page, source).finally(() => reading.delete(key)));
      }
      return reading.get(key);
    }
    // panels' answers from the stubs, sent together (as the console sends one change's), each
    // that is still the newest for its panel
    async function reply(msgs) {
      const got = await Promise.all(msgs.map((m) => read(m.source)));
      const outages = _notLive.get(page) || {};
      // the test server's age labels are of its own answers, not the stubs': the spec's beat
      // (pushBeat) labels the stubs' instants
      const out = msgs.map((m, i) => Object.assign({}, m, got[i], { ages: {} },
        m.panel in outages ? { not_live: outages[m.panel] } : {}))
        .filter((m, i) => shown.get(msgs[i].panel) === msgs[i]);
      if (out.length) send({ type: 'panels', seq: seq, panels: out });
    }
    // a change moves the panels of the view the console holds; one that comes while the page's
    // newer view is on its way moves that view's panels, once the console has taken it
    let waiting = [];
    async function moved(kind) {
      if (pageSeq !== null && seq !== pageSeq) {
        await new Promise((resolve) => waiting.push(() => moved(kind).then(resolve)));
        return;
      }
      change += 1;
      await reply([...shown.values()].filter((m) => m.kinds.includes(kind)));
    }
    _push.set(page, moved);
    _beat.set(page, (asOfAges) => send({ type: 'feed', session: session, as_of_ages: asOfAges || {} }));
    // the spec's change stream for the ticker, read as the console's push of each kind
    async function changes(tk) {
      while (!closed && tk === ticker) {
        const r = await page.evaluate(async (t) => {
          try {
            const res = await fetch('/api/changes?ticker=' + encodeURIComponent(t), { cache: 'no-store' });
            const stream = /text\/event-stream/.test(res.headers.get('content-type') || '');
            return { ok: res.ok && stream, text: await res.text() };
          } catch (e) { return { ok: false, text: '' }; }
        }, tk).catch(() => ({ ok: false, text: '' }));
        if (!r.ok) return;                        // no change stream stubbed: nothing is pushed
        for (const block of r.text.split('\n\n')) {
          const ev = (block.match(/^event: (.+)$/m) || [])[1], data = (block.match(/^data: (.*)$/m) || [])[1];
          if (!ev) continue;
          if (ev === 'session') { session = data; send({ type: 'feed', session: data, as_of_ages: {} }); continue; }
          await moved(ev);
        }
      }
    }
    const server = ws.connectToServer();
    server.onMessage((m) => {
      let msg; try { msg = JSON.parse(String(m)); } catch (e) { return; }
      if (!msg) return;
      if (msg.type === 'view') {
        seq = msg.seq;
        for (const n of [...shown.keys()]) if (!msg.shown.includes(n)) shown.delete(n);
        send(msg);
        if (seq === pageSeq) {                  // the page's newest view: what it would draw, read
          const now = held; held = [];
          reply(now.filter((h) => !msg.moved.includes(h.panel) && shown.get(h.panel) === h));
          const changes = waiting; waiting = [];
          changes.forEach((run) => run());
        }
        return;
      }
      if (msg.type === 'feed') {
        session = msg.session;
        msg = Object.assign({}, msg, { as_of_ages: {} });   // its labels are of its own answers, not the stubs'
      }
      if (msg.type === 'panels') {
        const each = msg.panels.map((p) => Object.assign({ seq: msg.seq }, p));
        each.forEach((p) => shown.set(p.panel, p));
        if (pageSeq !== null && msg.seq < pageSeq) held.push(...each); else reply(each);
        return;
      }
      send(msg);
    });
    ws.onMessage((m) => {
      let req; try { req = JSON.parse(String(m)); } catch (e) { return; }
      if (!req || req.op !== 'view') return;
      pageSeq = req.view.seq;
      try { server.send(String(m)); } catch (e) { /* the test server's push is gone */ }
      if (req.view.ticker && req.view.ticker !== ticker) { ticker = req.view.ticker; changes(ticker); }
    });
  });
}

const test = base.test.extend({
  page: async ({ page }, use) => {
    await installLive(page);
    await use(page);
  },
});

module.exports = { test, expect: base.expect, pushBeat, pushChange, pushDown, setNotLive };
