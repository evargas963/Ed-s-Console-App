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
  await page.waitForTimeout(3500);                     // a full scheduler tick
  expect(tickerCalls, 'nothing may be fetched for an unchosen ticker').toEqual([]);
  expect(await page.evaluate(() => window.EdShell.getState().ticker)).toBe('');
});
