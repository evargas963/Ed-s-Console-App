// The capture daemon's price socket (app/market_data/schwab/streaming/live_ui.py), stood in for.
// The console tells the page port 1 under e2e (playwright.config ED_LIVE_UI_PORT), so the page
// never reaches a real daemon. Like the daemon, it answers a subscribe with what each asked-for
// symbol is ({type:'symbols'}: requested, key, display), then sends `rows` 300 ms apart
// ({type:'quotes'}). Stand-in for instrument_identity: an index root is keyed with '$'
// (tests/test_live_ui_identity_v1.py holds the daemon's real answer). The returned handle's
// send(frame) pushes any daemon frame later (e.g. {type:'bars'}), once the page has subscribed;
// `subscribes` is every subscribe the page sent, and `ws` the connection it is on.
const INDEX_ROOTS = new Set(['SPX', 'NDX', 'VIX', 'DJI', 'COMPX', 'RUT']);
function served(s) {
  const u = String(s).toUpperCase();
  const key = u.startsWith('$') || !INDEX_ROOTS.has(u) ? u : '$' + u;
  return { requested: s, key: key, display: key.replace(/^\$/, '') };
}
function priceRow(ticker, spot, extra) {
  return Object.assign({ ticker: ticker, spot: spot, spot_disp: spot.toFixed(2), spot_state: 'live',
    feed_live: true, spot_source: 'streaming_plane', server_ts: Date.now() / 1000,
    trade_age_sec: 1 }, extra || {});
}
async function mockPriceSocket(page, rows) {
  const handle = { ws: null, subscribes: [], send(frame) { this.ws.send(JSON.stringify(frame)); } };
  await page.routeWebSocket(/:1\/$/, (ws) => {
    ws.onMessage((m) => {
      let req; try { req = JSON.parse(String(m)); } catch (e) { return; }
      if (!req || req.op !== 'subscribe' || !Array.isArray(req.symbols)) return;
      handle.ws = ws;
      handle.subscribes.push(req);
      ws.send(JSON.stringify({ type: 'symbols', symbols: req.symbols.map(served) }));
      (rows || []).forEach((r, i) => setTimeout(() => ws.send(JSON.stringify({ type: 'quotes', rows: [r] })), 300 * i));
    });
  });
  return handle;
}
module.exports = { mockPriceSocket, priceRow };
