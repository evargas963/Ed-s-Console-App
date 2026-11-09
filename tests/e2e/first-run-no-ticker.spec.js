// Universality (operator 2026-09-23): no built-in ticker or watchlist. A first run with
// nothing chosen asks for a symbol and asks the server for nothing about any ticker.
const { test, expect } = require('@playwright/test');
const { watchRequests } = require('./fixtures/settled');

test.use({ storageState: { cookies: [], origins: [] } });

test('first run: no ticker is assumed, no ticker data is requested', async ({ page }) => {
  const tickerCalls = [];
  page.on('request', (req) => {
    const u = req.url();
    if (/[?&]ticker=/.test(u)) tickerCalls.push(u);
  });
  const requests = watchRequests(page);
  await page.clock.install();                          // the page's timers run when the test moves its time
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#hPx')).toHaveText('CHOOSE A SYMBOL');
  await expect(page.locator('#hFeed')).toHaveText('NO SYMBOL');
  // no panel header names a ticker nobody chose (eleven read "SPX": register P-05)
  expect(await page.locator('.hticker').allTextContents()).toEqual(
    Array(await page.locator('.hticker').count()).fill('-'));
  await requests.settled();                            // the load's own reads have landed
  await page.clock.runFor(3500);                       // every page timer due in 3.5 s has run
  await requests.settled();                            // and every read those made
  expect(tickerCalls, 'nothing may be fetched for an unchosen ticker').toEqual([]);
  expect(await page.evaluate(() => window.EdShell.getState().ticker)).toBe('');
});

test('no symbol chosen: no view asks for a ticker on a view change, a resize, a theme change or its own controls', async ({ page }) => {
  const tickerCalls = [], asked = [];
  page.on('request', (req) => { if (/[?&]ticker=/.test(req.url())) tickerCalls.push(req.url()); });
  const requests = watchRequests(page);
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#hPx')).toHaveText('CHOOSE A SYMBOL');
  for (const ws of await page.locator('.navitem[data-ws]').evaluateAll((ns) => ns.map((n) => n.dataset.ws))) {
    await page.locator(`.navitem[data-ws="${ws}"]`).click();
    for (const sub of await page.locator('#subnav button[data-sub]:not(.na)').evaluateAll((bs) => bs.map((b) => b.dataset.sub))) {
      await page.locator(`#subnav button[data-sub="${sub}"]`).click();
      const views = await page.locator('#viewbar .vtab:not(.na)').evaluateAll((bs) => bs.map((b) => b.dataset.view));
      for (const view of views.length ? views : [null]) {
        if (view) await page.locator(`#viewbar .vtab[data-view="${view}"]`).click();
        await page.setViewportSize({ width: 1500, height: 900 });
        await page.setViewportSize({ width: 1280, height: 800 });
        await page.evaluate(() => { window.EdShell.setTheme('dark'); window.EdShell.setTheme('light'); });
        for (const control of await page.locator('.cmode:visible, .scbtn:visible').all()) await control.click();
        await requests.settled();                      // every read those made has gone out and landed
        if (tickerCalls.length) asked.push(`${ws} > ${sub} > ${view}: ${tickerCalls.splice(0).join(', ')}`);
      }
    }
  }
  expect(asked, 'nothing may be fetched for an unchosen ticker').toEqual([]);
});
