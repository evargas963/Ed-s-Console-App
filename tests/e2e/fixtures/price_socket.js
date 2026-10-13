// The capture daemon's Schwab socket (app/market_data/schwab/streaming/live_ui.py), stood in for.
// The console tells the page port 1 under e2e (playwright.config ED_LIVE_UI_PORT), so the page
// never reaches a real daemon. Like the daemon, it answers a subscribe with the feed state of each
// asked-for symbol ({type:'feed'}: live, no outage; a beat), what each is ({type:'symbols'}:
// requested, key, display), then sends each LEVELONE_EQUITIES message 300 ms apart ({type:'schwab'}: the
// fields Schwab sent, by Schwab's names). Stand-in for instrument_identity: an index root is keyed
// with '$' (tests/test_live_ui_daemon_to_browser_v1.py holds the daemon's real answer).
const INDEX_ROOTS = new Set(['SPX', 'NDX', 'VIX', 'DJI', 'COMPX', 'RUT']);
function served(s) {
  const u = String(s).toUpperCase();
  const key = u.startsWith('$') || !INDEX_ROOTS.has(u) ? u : '$' + u;
  return { requested: s, key: key, display: key.replace(/^\$/, '') };
}
// One LEVELONE_EQUITIES message: LAST_PRICE and its trade time, and any other fields Schwab sent
// (`fields`, by Schwab's names).
function schwabQuote(key, last, fields) {
  return { service: 'LEVELONE_EQUITIES', key: key, schwab_ts: Date.now(), ts_recv: Date.now() / 1000,
    content: Object.assign({ key: key, LAST_PRICE: last, TRADE_TIME_MILLIS: Date.now() - 1000 }, fields || {}) };
}
async function mockPriceSocket(page, messages) {
  await page.routeWebSocket(/:1\/$/, (ws) => {
    ws.onMessage((m) => {
      let req; try { req = JSON.parse(String(m)); } catch (e) { return; }
      if (!req || req.op !== 'subscribe' || !Array.isArray(req.symbols)) return;
      const symbols = req.symbols.map(served);
      // the beat's feed state first, then the answer the page waits for: a test that acts once
      // the symbols are answered acts after the beat, never before it
      const state = {};
      symbols.forEach((s) => { state[s.key] = { LEVELONE_EQUITIES: { live: true, outage: null } }; });
      ws.send(JSON.stringify({ type: 'feed', feed: null, state: state }));
      ws.send(JSON.stringify({ type: 'symbols', symbols: symbols }));
      (messages || []).forEach((q, i) => setTimeout(() => ws.send(JSON.stringify({ type: 'schwab', messages: [q] })), 300 * i));
    });
  });
}
module.exports = { mockPriceSocket, schwabQuote };
