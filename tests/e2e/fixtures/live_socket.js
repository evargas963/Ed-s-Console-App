// The console's push to the page (/api/live, server.live_values), stood in for in every spec: the
// page asks each route a panel shows ({op:'route', url}); this answers it with what the spec's own
// stubs serve for that URL (page.route), as the console answers it with its route's own answer.
// A spec that pushes a change does it as the console's stream of change kinds did
// (page.route('**/api/changes**', ... text/event-stream)): each `event: <kind>` it serves is
// pushed as the console pushes it -- every route the page asked for answered again, then
// {type:'changed', kind}; `event: session` is the session label. The console's own /api/live is
// proven against the real server in tests/test_live_values_push_v1.py.
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

// The console pushes a change of `kind` for the page's ticker: every route the page asked for
// answered again (through the spec's stubs), then the kind.
async function pushChange(page, kind) {
  const p = _push.get(page);
  if (p) await p(kind);
}

async function installLive(page) {
  await page.routeWebSocket(/\/api\/live$/, (ws) => {
    //: each route the page asked for -> the kinds that move it, as the console answers them (null until it has)
    const asked = new Map();
    let ticker = null, closed = false;
    const send = (m) => { if (!closed) { try { ws.send(JSON.stringify(m)); } catch (e) { closed = true; } } };
    ws.onClose(() => { closed = true; });
    async function reply(url) { send(Object.assign({ type: 'route', url: url }, await answer(page, url))); }
    async function moved(kind) {
      for (const [url, kinds] of asked) if (!kinds || kinds.includes(kind)) await reply(url);
    }
    _push.set(page, async (kind) => {
      await moved(kind);
      send({ type: 'changed', kind: kind });
    });
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
          send({ type: 'changed', kind: ev });
        }
      }
    }
    // the test server's own push: its session label and its changes (a route's answer is the
    // spec's, through its stubs)
    const server = ws.connectToServer();
    server.onMessage(async (m) => {
      let msg; try { msg = JSON.parse(String(m)); } catch (e) { return; }
      if (!msg) return;
      if (msg.type === 'route') { if (asked.has(msg.url)) asked.set(msg.url, msg.kinds || []); return; }
      if (msg.type === 'changed') await moved(msg.kind);
      send(msg);
    });
    const toServer = (m) => { try { server.send(String(m)); } catch (e) { /* the test server's push is gone */ } };
    ws.onMessage(async (m) => {
      let req; try { req = JSON.parse(String(m)); } catch (e) { return; }
      if (!req) return;
      if (req.op === 'ticker') { ticker = req.ticker; asked.clear(); toServer(m); changes(ticker); }
      else if (req.op === 'route' && typeof req.url === 'string') {
        asked.delete(req.url);              // the newest asked last: a push answers in the page's order
        asked.set(req.url, null); await reply(req.url); toServer(m);
      } else if (req.op === 'drop' && typeof req.url === 'string') { asked.delete(req.url); toServer(m); }
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
