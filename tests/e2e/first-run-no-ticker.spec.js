// Universality (operator 2026-09-23): no built-in ticker or watchlist. A first run with
// nothing chosen asks for a symbol and asks the server for nothing about any ticker.
const { test, expect } = require('@playwright/test');

test.use({ storageState: { cookies: [], origins: [] } });

test('first run: no ticker is assumed, no ticker data is requested', async ({ page }) => {
  const tickerCalls = [];
  page.on('request', (req) => {
    const u = req.url();
    if (/[?&]ticker=/.test(u) || /\/api\/(chain|terrain|levels|options\/gamma-surface)/.test(u)) tickerCalls.push(u);
  });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#hPx')).toHaveText('CHOOSE A SYMBOL');
  await expect(page.locator('#hFeed')).toHaveText('NO SYMBOL');
  // no panel header names a ticker nobody chose (eleven read "SPX": register P-05)
  expect(await page.locator('.hticker').allTextContents()).toEqual(
    Array(await page.locator('.hticker').count()).fill('—'));
  await page.waitForTimeout(3500);                     // a full scheduler tick
  expect(tickerCalls, 'nothing may be fetched for an unchosen ticker').toEqual([]);
  expect(await page.evaluate(() => window.EdShell.getState().ticker)).toBe('');
});

test('no symbol chosen: no view asks for a ticker on a view change, a resize or a theme change', async ({ page }) => {
  // Seen 2026-10-24 on production: Options > Gamma > Heatmap with no symbol asked
  // /api/options/gamma-surface?ticker= (400) on a window resize, then read "no console serving".
  const tickerCalls = [];
  page.on('request', (req) => { if (/[?&]ticker=/.test(req.url())) tickerCalls.push(req.url()); });
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
        await page.waitForTimeout(100);
        expect(tickerCalls, `${ws} > ${sub} > ${view}: nothing may be fetched for an unchosen ticker`).toEqual([]);
      }
    }
  }
});
