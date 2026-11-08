// @ts-check
// The price socket's frames are the daemon's JSON. A frame the page cannot parse is the daemon's
// defect; the page raises it as an error, never drops it in silence (AGENTS.md rule 1, no patches).
const { test, expect } = require('@playwright/test');

test('a price-socket frame that is not JSON is an error on the page, never dropped in silence', async ({ page }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.routeWebSocket(/:1\/$/, (ws) => { ws.onMessage(() => ws.send('not json')); });
  await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect.poll(() => errors.length).toBeGreaterThan(0);
  expect(errors.join('\n')).toMatch(/JSON/);
});
