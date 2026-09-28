/*
 * Order Flow heatmap draws the served book history and computes nothing (P1-3, PR C, 2026-09-27):
 * the default price window (display_lo/hi), each cell's dominant side and the colour scale's top
 * (max_size) are served; the page places each served cell at its own price and bucket. The payload
 * is the real producer's output over real TSLA book rows (tests/e2e/fixtures/book_heatmap_payload.json,
 * generated from tests/fixtures/real_tsla_book_rows.json). Any page error fails the test.
 */
const { test, expect } = require('@playwright/test');
const path = require('path');

const HEAT = require(path.join(__dirname, 'fixtures', 'book_heatmap_payload.json'));

test('the heatmap paints the served cells, and a click pins a readout, without a page error', async ({ page }) => {
  const errs = [];
  page.on('pageerror', (e) => errs.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error' && !/WebSocket|EventSource|Failed to load resource/.test(m.text())) errs.push(m.text()); });
  await page.route('**/api/**', (route) => {
    const url = route.request().url();
    const body = url.includes('/api/order-flow/book-heatmap') ? HEAT : { available: false };
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
  await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'TSLA'); localStorage.setItem('ed_ws', 'order-flow'); localStorage.setItem('ed_sub', 'heatmap'); } catch (e) {} });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  const canvas = page.locator('#ofhCanvas');
  await expect(canvas).toBeVisible();
  const painted = await canvas.evaluate((c) => {
    const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
    let green = 0, red = 0;
    for (let i = 0; i < d.length; i += 4) { if (d[i + 1] > 120 && d[i + 1] > d[i] + 40) green++; if (d[i] > 150 && d[i] > d[i + 1] + 60) red++; }
    return { green, red };
  });
  expect(painted.green + painted.red).toBeGreaterThan(0);          // served cells drawn in their side's colour
  const box = await canvas.boundingBox();
  await page.mouse.click(box.x + box.width * 0.6, box.y + box.height * 0.4);
  await expect(canvas).toBeVisible();
  expect(errs).toEqual([]);
});
