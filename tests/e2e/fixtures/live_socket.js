// The console's push to the page (/api/live, server.live_values), with each panel's value from the
// spec's own stubs. The page's view ({op:'view'}) goes to the real test server, which answers as
// the console does: which panels are on screen ({type:'view', seq, moved, shown}) and each one's
// answer by name ({type:'panel', panel, seq, source, kinds, ...}). Each answer is replaced by what
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

// The console pushes a change of `kind` for the page's ticker: every panel on screen that it
// moves, answered again (through the spec's stubs).
async function pushChange(page, kind) {
  const p = _push.get(page);
  if (p) await p(kind);
}

async function installLive(page) {
  await page.routeWebSocket(/\/api\/live$/, (ws) => {
    //: each panel on screen -> the console's newest message for it (its source and kinds)
    const shown = new Map();
    //: each route's answer from the stubs while it is being read: one read per route, however
    //: many panels show it, as the console computes each route once (server._answers)
    const reading = new Map();
    //: the console's answers under a view older than the page's newest: held until the console
    //: takes the newest, then read or dropped as the page draws or drops them
    let held = [];
    let seq = null, pageSeq = null, ticker = null, closed = false;
    const send = (m) => { if (!closed) { try { ws.send(JSON.stringify(m)); } catch (e) { closed = true; } } };
    ws.onClose(() => { closed = true; });
    function read(source) {
      if (!reading.has(source)) {
        reading.set(source, answer(page, source).finally(() => reading.delete(source)));
      }
      return reading.get(source);
    }
    // a panel's answer from the stubs, sent if it is still the newest for that panel
    async function reply(msg) {
      const a = await read(msg.source);
      if (shown.get(msg.panel) !== msg) return;
      send(Object.assign({}, msg, a, { seq: seq }));
    }
    // a change moves the panels of the view the console holds; one that comes while the page's
    // newer view is on its way moves that view's panels, once the console has taken it
    let waiting = [];
    async function moved(kind) {
      if (pageSeq !== null && seq !== pageSeq) {
        await new Promise((resolve) => waiting.push(() => moved(kind).then(resolve)));
        return;
      }
      await Promise.all([...shown.values()].filter((m) => m.kinds.includes(kind)).map(reply));
    }
    _push.set(page, moved);
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
          if (ev === 'session') { send({ type: 'session', label: data }); continue; }
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
          now.filter((h) => !msg.moved.includes(h.panel) && shown.get(h.panel) === h).forEach(reply);
          const changes = waiting; waiting = [];
          changes.forEach((run) => run());
        }
        return;
      }
      if (msg.type === 'panel') {
        shown.set(msg.panel, msg);
        if (pageSeq !== null && msg.seq < pageSeq) held.push(msg); else reply(msg);
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

module.exports = { test, expect: base.expect, pushChange };
