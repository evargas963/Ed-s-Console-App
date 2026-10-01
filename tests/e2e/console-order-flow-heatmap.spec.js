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
  // drawn on the one shared chart (ed-tv-chart.js), every served cell handed to it
  const plot = page.locator('#ofhBody .ofh-plot');
  await expect(plot.locator('canvas').first()).toBeVisible();
  await expect.poll(() => page.evaluate(() => (window.EdBookHeatmap.state() || {}).heatCells)).toBe(HEAT.cells.length);
  await expect.poll(() => plot.evaluate((p) => {
    let green = 0, red = 0;
    p.querySelectorAll('canvas').forEach((c) => {
      const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
      for (let i = 0; i < d.length; i += 4) { if (d[i + 1] > 120 && d[i + 1] > d[i] + 40) green++; if (d[i] > 150 && d[i] > d[i + 1] + 60) red++; }
    });
    return green + red;
  })).toBeGreaterThan(0);                                            // served cells drawn in their side's colour
  // a click pins the chart's readout (the TradingView standard every chart shares): price, bid, ask
  const box = await plot.boundingBox();
  await page.mouse.click(box.x + box.width * 0.5, box.y + box.height * 0.5);
  await expect(plot.locator('.tvc-pin')).toBeVisible();
  await expect(plot.locator('.tvc-pin')).toContainText('Bid size');
  expect(errs).toEqual([]);
});

test('the Book panel shows each served wall candidate size', async ({ page }) => {
  // stand-in wall in the engine's own shape (engine._book_wall_candidates: side, price, volume,
  // median_mult); the page printed w.size, which the engine never serves, so every wall read "—"
  const BOOK = { status: 'ok', top_of_book: {}, depth: {}, ages: {}, classification: {}, depth_pressure: {},
    wall_candidates: [{ side: 'bid', price: 440.5, volume: 12500, median_mult: 6.2 }] };
  await page.route('**/api/**', (route) => {
    const url = route.request().url();
    const body = url.includes('/api/order-flow/microstructure') ? BOOK : { available: false };
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
  await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'TSLA'); localStorage.setItem('ed_ws', 'order-flow'); localStorage.setItem('ed_sub', 'book'); } catch (e) {} });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#obBody')).toContainText('bid @ 440.50');
  await expect(page.locator('#obBody')).toContainText('12500');
});

test('the Book panel prints the book-shape values and the wall rule the server serves', async ({ page }) => {
  // the engine computed the book's slope, the share at the touch, top-book pressure, the crossed
  // flag and the wall rule on every request, and no screen read them. The payload is the real
  // producer's (tests/e2e/fixtures/options_microstructure_payload.json, held to the route by
  // test_flow_e2e_fixture_is_the_route_contract): both book routes serve this one shape.
  const BOOK = require(path.join(__dirname, 'fixtures', 'options_microstructure_payload.json'));
  await page.route('**/api/**', (route) => {
    const url = route.request().url();
    const body = url.includes('/api/order-flow/microstructure') ? BOOK : { available: false };
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
  await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'TSLA'); localStorage.setItem('ed_ws', 'order-flow'); localStorage.setItem('ed_sub', 'book'); } catch (e) {} });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  const ob = page.locator('#obBody');
  const row = (k) => ob.locator('.fl-row', { hasText: k }).locator('.v');
  await expect(row('Slope bid / ask')).toHaveText(Math.round(BOOK.book_slope.bid) + ' / ' + Math.round(BOOK.book_slope.ask));
  await expect(row('At the touch bid / ask')).toHaveText(BOOK.liquidity_concentration.bid.toFixed(2) + ' / ' + BOOK.liquidity_concentration.ask.toFixed(2));
  await expect(row('Top-book pressure')).toHaveText(BOOK.top_book_pressure.toFixed(3));
  await expect(row('Crossed')).toHaveText('no');
  await expect(row('Levels bid / ask')).toHaveText(BOOK.provenance.n_bid_levels + ' / ' + BOOK.provenance.n_ask_levels);
  await expect(ob).toContainText('Wall candidates — ' + BOOK.wall_method.basis);
});
