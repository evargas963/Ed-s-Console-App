// The page's price socket (/ws, app/market_data/schwab/streaming/live_ui.py), stood in for: the
// e2e console runs no daemon, so its own /ws refuses a page. Like the daemon, it answers a subscribe with what each asked-for
// symbol is ({type:'symbols'}: requested, key, display), then sends `rows` 300 ms apart
// ({type:'quotes'}). Stand-in for instrument_identity: an index root is keyed with '$'
// (tests/test_live_ui_identity_v1.py holds the daemon's real answer).
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
// `later`: [{ afterMs, row }], rows sent that long after the subscribe (a push that resumes);
// `expiries`: the body sent for the selected ticker on each subscribe (none: no list is sent)
async function mockPriceSocket(page, rows = [], later = [], expiries = undefined) {
  await page.routeWebSocket(/\/ws$/, (ws) => {
    ws.onMessage((m) => {
      const req = JSON.parse(String(m));
      if (req.op !== 'subscribe' || !Array.isArray(req.symbols)) return;
      ws.send(JSON.stringify({ type: 'symbols', symbols: req.symbols.map(served) }));
      if (expiries && req.ticker) ws.send(expiriesFrame(req.ticker, expiries));
      rows.forEach((r, i) => setTimeout(() => ws.send(JSON.stringify({ type: 'quotes', rows: [r] })), 300 * i));
      later.forEach((l) => setTimeout(() => ws.send(JSON.stringify({ type: 'quotes', rows: [l.row] })), l.afterMs));
    });
  });
}
module.exports = { mockPriceSocket, priceRow, served, expiriesFrame };
