// The page's price socket (/ws, app/market_data/schwab/streaming/live_ui.py), stood in for: the
// e2e console runs no daemon, so its own /ws refuses a page. Like the daemon, it answers a subscribe with what each asked-for
// symbol is ({type:'symbols'}: requested, key, display), then sends `rows` 300 ms apart
// ({type:'quotes'}). Stand-in for instrument_identity: an index root is keyed with '$'
// (tests/test_live_ui_identity_v1.py holds the daemon's real answer). Its beat carries the
// watchlist routeWatchlist keeps for the page (fixtures/watchlist.js), as the program's does.
const { beat, socketed } = require('./watchlist');
const INDEX_ROOTS = new Set(['SPX', 'NDX', 'VIX', 'DJI', 'COMPX', 'RUT']);
function served(s) {
  const u = String(s).toUpperCase();
  const key = u.startsWith('$') || !INDEX_ROOTS.has(u) ? u : '$' + u;
  return { requested: s, key: key, display: key.replace(/^\$/, '') };
}
function priceRow(ticker, spot, extra = {}) {
  return Object.assign({ ticker: ticker, spot: spot, spot_disp: spot.toFixed(2), spot_state: 'live',
    feed_live: true, feed_label: 'LIVE', spot_source: 'streaming_plane', server_ts: Date.now() / 1000,
    trade_age_text: '1s' }, extra);
}
// The selected ticker's expiry list as the program sends it after the subscribe's `symbols` frame
// ({type:'expiries', ticker: key, ...server.expiries' body}).
function expiriesFrame(ticker, body) {
  return JSON.stringify(Object.assign({ type: 'expiries', ticker: served(ticker).key }, body));
}
// A panel as the program sends it ({type: the reader's panel name, ticker: key, ...its body}).
function panelFrame(name, ticker, body) {
  return JSON.stringify(Object.assign({}, body, { type: name, ticker: served(ticker).key }));
}
// `later`: [{ afterMs, row }], rows sent that long after the subscribe (a push that resumes);
// `expiries`: the body sent for the selected ticker on each subscribe (none: no list is sent);
// `panels`: the program's panel producers, stood in for (server.PAGE_PANELS): {kind: a body, or
// (ticker key, the panel's parameters, its name) => a body (undefined: none sent)}, read at each
// send. Each panel a subscribe names ("<kind>" or "<kind>:<reader>") whose kind is here is sent
// for the selected ticker on the subscribe, as live_ui does. Returns `changed(kind)`: the
// program marking a kind changed, each page showing it sent its panels again; and `subscribes`,
// every subscribe the page sent.
async function mockPriceSocket(page, rows = [], later = [], expiries = undefined, panels = {}) {
  socketed.add(page);
  const open = new Set();   // [ws, its last subscribe]
  const subscribes = [];
  function sendPanels(ws, req, kind) {
    Object.keys(req.ticker && req.panels ? req.panels : {}).forEach((name) => {
      const k = name.split(':')[0];
      if (!(k in panels) || (kind && k !== kind)) return;
      const p = panels[k];
      const body = typeof p === 'function' ? p(served(req.ticker).key, req.panels[name], name) : p;
      if (body !== undefined) ws.send(panelFrame(name, req.ticker, body));
    });
  }
  await page.routeWebSocket(/\/ws$/, (ws) => {
    const conn = [ws, null];
    open.add(conn);
    ws.onClose(() => open.delete(conn));
    beat(page, ws);
    ws.onMessage((m) => {
      const req = JSON.parse(String(m));
      if (req.op !== 'subscribe' || !Array.isArray(req.symbols)) return;
      conn[1] = req;
      subscribes.push(req);
      ws.send(JSON.stringify({ type: 'symbols', symbols: req.symbols.map(served) }));
      if (expiries && req.ticker) ws.send(expiriesFrame(req.ticker, expiries));
      sendPanels(ws, req);
      rows.forEach((r, i) => setTimeout(() => ws.send(JSON.stringify({ type: 'quotes', rows: [r] })), 300 * i));
      later.forEach((l) => setTimeout(() => ws.send(JSON.stringify({ type: 'quotes', rows: [l.row] })), l.afterMs));
    });
  });
  return { changed: (kind) => open.forEach((c) => { if (c[1]) sendPanels(c[0], c[1], kind); }), subscribes };
}
module.exports = { mockPriceSocket, priceRow, served, expiriesFrame, panelFrame };
