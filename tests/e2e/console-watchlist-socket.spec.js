// @ts-check
// The watchlist rail reads the list the program's socket carries on every beat (/ws `feed`: the
// daemon's status, its `watchlist`; live_ui.LiveUiServer.beat_loop), and asks the console for no
// list. STAND-INS: the program's socket, its beats carrying the watchlist alone (no rows), and the
// console's watchlist routes (fixtures/watchlist.js).
const { test, expect } = require('@playwright/test');
const { routeWatchlist } = require('./fixtures/watchlist');

// one beat as the program sends it, the daemon's status reduced to its watchlist (null: none)
function feed(list) {
  return JSON.stringify({ type: 'feed', feed: list === null ? null : { watchlist: list } });
}

test('the rail fills from the first beat on the socket, and nothing asks for the list', async ({ page }) => {
  const gets = [];
  page.on('request', (r) => { if (r.url().includes('/api/watchlist') && r.method() === 'GET') gets.push(r.url()); });
  await page.routeWebSocket(/\/ws$/, (ws) => ws.send(feed(['SPY', 'QQQ'])));
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.wl-row .wl-sym')).toHaveText(['SPY', 'QQQ']);
  await page.waitForTimeout(1500);
  expect(gets).toEqual([]);
});

test('before a beat has carried a list, the rail reads "-", never an empty list', async ({ page }) => {
  await page.routeWebSocket(/\/ws$/, () => {});          // open, no beat yet
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.wl-empty')).toHaveText('-');
  await page.waitForTimeout(1500);
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
  await page.routeWebSocket(/\/ws$/, (ws) => {
    ws.send(feed(['SPY', 'QQQ']));
    const timer = setInterval(() => ws.send(feed(['SPY', 'QQQ'])), 200);
    timer.unref();
    ws.onClose(() => clearInterval(timer));
  });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.wl-row .wl-sym')).toHaveText(['SPY', 'QQQ']);
  await page.evaluate(() => { document.querySelector('.wl-row').dataset.drawn = 'first'; });
  await page.waitForTimeout(1500);                        // seven beats of the same list
  await expect(page.locator('.wl-row').first()).toHaveAttribute('data-drawn', 'first');
});
