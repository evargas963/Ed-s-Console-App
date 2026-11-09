// The console's watchlist routes (server.py post_watchlist, delete_watchlist) and the beat that
// carries the list to the page, stood in for: the capture daemon keeps the one list, each add or
// removal is answered with its record ({ok, op, ticker, tickers, status, answer}), and the
// program's socket (/ws, live_ui.LiveUiServer.beat_loop) sends the daemon's status, its
// `watchlist`, every second as a `feed` frame. STAND-INS: Schwab quotes every ticker added except
// one in `invalid`, which is answered as Schwab answered ZQZQZ on 2026-10-07
// (tests/fixtures/real_schwab_quotes_watchlist_check_2026_10_07.json: {"errors": {"invalidSymbols": [T]}});
// the beat carries the watchlist alone and no rows, so a test's price silence stays its own, and
// this socket answers no subscribe (mockPriceSocket, registered after it, does, with the same beat).
// Returns the list it keeps, so a test can read what the daemon holds or change it as the daemon
// would for another page.
const lists = new WeakMap();

// the program's beat to the page on `ws`: at once, then every second, the list kept for `page`
function beat(page, ws) {
  const send = () => {
    const list = lists.get(page);
    if (list) ws.send(JSON.stringify({ type: 'feed', feed: { watchlist: list.slice() } }));
  };
  send();
  const timer = setInterval(send, 1000);
  timer.unref();
  ws.onClose(() => clearInterval(timer));
}

async function routeWatchlist(page, tickers = [], invalid = []) {
  const list = tickers.slice();
  const bad = new Set(invalid);
  lists.set(page, list);
  await page.routeWebSocket(/\/ws$/, (ws) => beat(page, ws));
  await page.route('**/api/watchlist**', (route) => {
    const req = route.request();
    const answer = (body) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    if (req.method() === 'POST') {
      const t = String(req.postDataJSON().ticker).toUpperCase();
      if (bad.has(t)) {
        return answer({ ok: false, op: 'invalid', ticker: t, tickers: list.slice(), status: 200,
          answer: { errors: { invalidSymbols: [t] } } });
      }
      list.push(t);
      return answer({ ok: true, op: 'added', ticker: t, tickers: list.slice(), status: 200, answer: {} });
    }
    if (req.method() !== 'DELETE') {   // the program serves no GET of the list: 405, as FastAPI answers
      return route.fulfill({ status: 405, contentType: 'application/json', body: '{"detail":"Method Not Allowed"}' });
    }
    const t = decodeURIComponent(req.url().split('/api/watchlist/')[1]).toUpperCase();
    list.splice(list.indexOf(t), 1);
    return answer({ ok: true, op: 'removed', ticker: t, tickers: list.slice(), status: null, answer: null });
  });
  return list;
}
module.exports = { routeWatchlist, beat };
