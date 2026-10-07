// The console's watchlist routes (server.py get_watchlist, post_watchlist, delete_watchlist), stood
// in for: the capture daemon keeps the one list, and each add or removal is answered with its record
// ({ok, op, ticker, tickers, status, answer}). STAND-IN: Schwab quotes every ticker added except one
// in `invalid`, which is answered as Schwab answered ZQZQZ on 2026-10-07
// (tests/fixtures/real_schwab_quotes_watchlist_check_2026_10_07.json: {"errors": {"invalidSymbols": [T]}}).
// Returns the list it keeps, so a test can read what the daemon would hold.
async function routeWatchlist(page, tickers, invalid) {
  const list = (tickers || []).slice();
  const bad = new Set(invalid || []);
  await page.route('**/api/watchlist**', (route) => {
    const req = route.request();
    const answer = (body) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    if (req.method() === 'GET') return answer({ tickers: list.slice() });
    if (req.method() === 'POST') {
      const t = String(req.postDataJSON().ticker).toUpperCase();
      if (bad.has(t)) {
        return answer({ ok: false, op: 'invalid', ticker: t, tickers: list.slice(), status: 200,
          answer: { errors: { invalidSymbols: [t] } } });
      }
      list.push(t);
      return answer({ ok: true, op: 'added', ticker: t, tickers: list.slice(), status: 200, answer: {} });
    }
    const t = decodeURIComponent(req.url().split('/api/watchlist/')[1]).toUpperCase();
    list.splice(list.indexOf(t), 1);
    return answer({ ok: true, op: 'removed', ticker: t, tickers: list.slice(), status: null, answer: null });
  });
  return list;
}
module.exports = { routeWatchlist };
