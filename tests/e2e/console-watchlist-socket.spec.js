// @ts-check
// The watchlist rail reads the list the program's socket carries on every beat (/ws `feed`: the
// daemon's status, its `watchlist`; live_ui.LiveUiServer.beat_loop), and asks the console for no
// list. STAND-INS: the program's socket, its beats carrying the watchlist alone (no rows), and the
// console's watchlist routes (fixtures/watchlist.js).
const { test, expect } = require('@playwright/test');
const { routeWatchlist } = require('./fixtures/watchlist');
const { watchRequests } = require('./fixtures/settled');

// one beat as the program sends it, the daemon's status reduced to its time, its watchlist and
// the session (Unknown: Schwab's /markets answer not held) (null: no status); `ts` on the
// program's clock, now unless given
function feed(list, ts = Date.now() / 1000, session = 'Unknown') {
  return JSON.stringify({ type: 'feed', feed: list === null ? null : { ts: ts, watchlist: list, session: session } });
}

// The page's clock held from before the page loads: its timers run only when the test moves its
// time (`install` alone leaves the clock running).
async function holdClock(page) {
  await page.clock.install();
  await page.clock.pauseAt(Date.now());
}

// Every frame sent on `socket` before this one has been taken by the page: a beat with no status,
// sent last, is answered on the page by its notice (the page's clock held, so no timer of the
// page replaces or clears it).
async function taken(page, socket) {
  socket.send(feed(null));
  await expect(page.locator('#wlMsg')).toHaveText('the capture daemon is not reporting');
}

test('the rail fills from the first beat on the socket, and nothing asks for the list', async ({ page }) => {
  const requests = watchRequests(page);
  const gets = [];
  page.on('request', (r) => { if (r.url().includes('/api/watchlist') && r.method() === 'GET') gets.push(r.url()); });
  await page.routeWebSocket(/\/ws$/, (ws) => ws.send(feed(['SPY', 'QQQ'])));
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.wl-row .wl-sym')).toHaveText(['SPY', 'QQQ']);
  await requests.settled();
  expect(gets).toEqual([]);
});

test('the header session follows each beat, while quotes keep arriving between them', async ({ page }) => {
  let socket;
  await page.routeWebSocket(/\/ws$/, (ws) => { socket = ws; ws.send(feed(['SPY'], 1000, 'Closed')); });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#hSession')).toHaveText('CLOSED');
  for (let i = 0; i < 5; i++) socket.send(JSON.stringify({ type: 'quotes', rows: [] }));
  socket.send(feed(['SPY'], 1001, 'Pre-Market'));         // Schwab's pre-market window opened
  await expect(page.locator('#hSession')).toHaveText('PRE');
  await expect(page.locator('#hSession')).toHaveClass(/pre/);
  socket.send(feed(['SPY'], 1002, 'RTH'));
  await expect(page.locator('#hSession')).toHaveText('RTH');
});

test('before a beat has carried a list, the rail reads "-", never an empty list', async ({ page }) => {
  await holdClock(page);
  await page.routeWebSocket(/\/ws$/, () => {});          // open, no beat yet
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.wl-empty')).toHaveText('-');
  await page.clock.runFor(3000);                          // every page timer due in 3 s has run
  await expect(page.locator('.wl-empty')).toHaveText('-');
  await expect(page.locator('.wl-row')).toHaveCount(0);
});

test('a change the daemon makes reaches the rail with the next beat; an add here draws from its answer', async ({ page }) => {
  const list = await routeWatchlist(page, ['SPY']);
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.wl-row .wl-sym')).toHaveText(['SPY']);
  list.push('AMD');                                       // added on another page: the daemon's list
  await expect(page.locator('.wl-row .wl-sym')).toHaveText(['SPY', 'AMD'], { timeout: 2500 });
  list.splice(0, 1);                                      // SPY removed on another page
  await expect(page.locator('.wl-row .wl-sym')).toHaveText(['AMD'], { timeout: 2500 });
  await page.evaluate(() => window.EdShell.addSymbol('MU'));
  await expect(page.locator('.wl-row .wl-sym')).toHaveText(['AMD', 'MU']);
});

test('a beat built before an add, arriving after its answer, does not take the added ticker away', async ({ page }) => {
  // the program's clock: the add's record at 1002; a beat built at 1001 still carries the old list
  let socket;
  await holdClock(page);
  await page.routeWebSocket(/\/ws$/, (ws) => { socket = ws; ws.send(feed(['SPY'], 1000)); });
  await page.route('**/api/watchlist', (route) => route.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify({ ok: true, op: 'added', ticker: 'AMD', tickers: ['SPY', 'AMD'], ts: 1002, status: 200, answer: {} }) }));
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.wl-row .wl-sym')).toHaveText(['SPY']);
  await page.evaluate(() => window.EdShell.addSymbol('AMD'));
  await expect(page.locator('.wl-row .wl-sym')).toHaveText(['SPY', 'AMD']);
  socket.send(feed(['SPY'], 1001));                       // late: built before the add
  await taken(page, socket);
  await expect(page.locator('.wl-row .wl-sym')).toHaveText(['SPY', 'AMD']);
  socket.send(feed(['SPY', 'AMD', 'MU'], 1003));          // built after it: taken
  await expect(page.locator('.wl-row .wl-sym')).toHaveText(['SPY', 'AMD', 'MU']);
});

test('a beat with no status keeps the list drawn and says the daemon is not reporting', async ({ page }) => {
  await page.routeWebSocket(/\/ws$/, (ws) => {
    ws.send(feed(['SPY', 'QQQ']));
    const timer = setInterval(() => ws.send(feed(null)), 1000);   // every beat while the status fails
    timer.unref();
    ws.onClose(() => clearInterval(timer));
  });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#wlMsg')).toHaveText('the capture daemon is not reporting');
  await expect(page.locator('.wl-row .wl-sym')).toHaveText(['SPY', 'QQQ']);
});

test('the socket drops: the rail stands marked; it returns: the new connection\'s beat redraws it', async ({ page }) => {
  let connections = 0;
  await page.routeWebSocket(/\/ws$/, (ws) => {
    connections += 1;
    if (connections === 1) {
      ws.send(feed(['SPY', 'QQQ']));
      setTimeout(() => ws.close(), 500);                  // the program goes away
    } else {
      setTimeout(() => ws.send(feed(['SPY', 'IWM'])), 4000);   // back, its first beat later
    }
  });
  await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.wl-row .wl-sym')).toHaveText(['SPY', 'QQQ']);
  await expect.poll(() => connections).toBe(2);
  await expect(page.locator('#watchlist')).toHaveClass(/wl-degraded/);
  await expect(page.locator('.wl-row .wl-sym')).toHaveText(['SPY', 'QQQ']);
  await expect(page.locator('.wl-row .wl-sym')).toHaveText(['SPY', 'IWM'], { timeout: 6000 });
});

test('the same list on every beat leaves the rail as drawn (no redraw, no flicker)', async ({ page }) => {
  let socket;
  await holdClock(page);
  await page.routeWebSocket(/\/ws$/, (ws) => { socket = ws; ws.send(feed(['SPY', 'QQQ'])); });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.wl-row .wl-sym')).toHaveText(['SPY', 'QQQ']);
  await page.evaluate(() => { document.querySelector('.wl-row').dataset.drawn = 'first'; });
  for (let beat = 0; beat < 7; beat += 1) socket.send(feed(['SPY', 'QQQ']));   // seven beats, the same list
  await taken(page, socket);
  await expect(page.locator('.wl-row').first()).toHaveAttribute('data-drawn', 'first');
});
