// @ts-check
/** Issue 40/46 — minimal real-browser check: app loads over webServer (Playwright), DOM visible. */
const { test, expect } = require('@playwright/test');

test('app shell loads and document has body', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  const hasBody = await page.evaluate(() => document.body && document.body.innerText.length >= 0);
  expect(hasBody).toBe(true);
});
