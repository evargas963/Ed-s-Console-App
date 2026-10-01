// The capture daemon's price socket (app/market_data/schwab/streaming/live_ui.py), stood in for.
// The console tells the page port 1 under e2e (playwright.config ED_LIVE_UI_PORT), so the page
// never reaches a real daemon. Like the daemon, it sends the board on connect ({type:'board'}),
// answers a board edit with the symbol's key ({type:'board_edit'}: requested, key, display) and
// the new board, and sends `rows` 300 ms apart ({type:'quotes'}). Stand-in for
// instrument_identity: an index root is keyed with '$' (tests/test_live_ui_identity_v1.py holds
// the daemon's real answer).
const INDEX_ROOTS = new Set(['SPX', 'NDX', 'VIX', 'DJI', 'COMPX', 'RUT']);
function keyOf(s) {
  const u = String(s).toUpperCase();
  return u.startsWith('$') || !INDEX_ROOTS.has(u) ? u : '$' + u;
}
function entry(key) { return { key: key, display: key.replace(/^\$/, '') }; }
function priceRow(ticker, spot, extra) {
  return Object.assign({ ticker: ticker, spot: spot, spot_disp: spot.toFixed(2), spot_state: 'live',
    feed_live: true, spot_source: 'streaming_plane', server_ts: Date.now() / 1000,
    trade_age_sec: 1 }, extra || {});
}
const DEFAULT_BOARD = ['SPY', 'QQQ', 'IWM', 'NVDA', 'TSLA'];
// Returns { ops }: every board edit the page sent, in order. opts.beat: like the daemon, a feed
// beat every second carrying every board ticker's last row (without it the socket goes silent
// after the rows, which the real daemon never does).
async function mockPriceSocket(page, rows, board, opts) {
  const held = (board || DEFAULT_BOARD).slice();
  const ops = [];
  await page.routeWebSocket(/:1\/$/, (ws) => {
    const sendBoard = () => ws.send(JSON.stringify({ type: 'board', board: held.map(entry) }));
    sendBoard();
    (rows || []).forEach((r, i) => setTimeout(() => ws.send(JSON.stringify({ type: 'quotes', rows: [r] })), 300 * (i + 1)));
    if (opts && opts.beat) {
      const beat = setInterval(() => {
        try {
          ws.send(JSON.stringify({ type: 'feed', feed: { ts: Date.now() / 1000, schwab_socket_open: true },
            rows: held.map((k) => priceRow(k, 100)) }));
        } catch (e) { clearInterval(beat); }
      }, 1000);
    }
    ws.onMessage((m) => {
      let req; try { req = JSON.parse(String(m)); } catch (e) { return; }
      if (!req || (req.op !== 'board_add' && req.op !== 'board_remove')) return;
      ops.push({ op: req.op, symbol: req.symbol });
      const key = keyOf(req.symbol);
      const at = held.indexOf(key);
      const changes = (req.op === 'board_add') === (at === -1);
      if (req.op === 'board_add' && changes) held.push(key);
      if (req.op === 'board_remove' && changes) held.splice(at, 1);
      if (changes) sendBoard();                    // like the daemon: a changed board first, to every page
      ws.send(JSON.stringify(Object.assign({ type: 'board_edit', op: req.op, requested: req.symbol, error: null }, entry(key))));
    });
  });
  return { ops };
}
module.exports = { mockPriceSocket, priceRow };
