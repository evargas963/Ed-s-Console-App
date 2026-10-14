/*
 * Order Flow heatmap draws the served book history and computes nothing (P1-3, PR C, 2026-09-27):
 * the default price window (display_lo/hi), each cell's dominant side and the colour scale's top
 * (max_size) are served; the page places each served cell at its own price and bucket. The payload
 * is the real producer's output over real TSLA book rows (tests/e2e/fixtures/book_heatmap_payload.json,
 * generated from tests/fixtures/real_tsla_book_rows.json). Any page error fails the test.
 */
const { test, expect } = require('./fixtures/live_socket');
const { expiriesAnswer } = require('./fixtures/expiries');
const path = require('path');
const { routeWatchlist } = require('./fixtures/watchlist');

const { mockPriceSocket, schwabQuote, schwabBook } = require('./fixtures/price_socket');

const HEAT = require(path.join(__dirname, 'fixtures', 'book_heatmap_payload.json'));
const BOOKS = require(path.join(__dirname, '..', 'fixtures', 'real_tsla_book_rows.json')).rows;

test('the heatmap paints the served cells, and a click pins a readout, without a page error', async ({ page }) => {
  const errs = [];
  page.on('pageerror', (e) => errs.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error' && !/WebSocket|EventSource|Failed to load resource/.test(m.text())) errs.push(m.text()); });
  await page.route('**/api/**', (route) => {
    const url = route.request().url();
    const body = url.includes('/api/order-flow/book-heatmap') ? HEAT
      : url.includes('/api/expiries') ? expiriesAnswer([]) : { available: false };
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
  await routeWatchlist(page, ['TSLA']);
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
  // read from TSLA's NYSE_BOOK, which the test console has no feed of: marked by that feed's judgment
  await expect(page.locator('#ofhBody')).toHaveAttribute('data-not-live', /NYSE_BOOK/);
  expect(errs).toEqual([]);
});

test('the Book panel shows each served wall candidate size', async ({ page }) => {
  // stand-in wall in the engine's own shape (engine._book_wall_candidates: side, price, volume,
  // median_mult); the page printed w.size, which the engine never serves, so every wall read "—"
  const BOOK = { status: 'ok', top_of_book: {}, depth: {}, ages: {}, as_of: { book: null, quote: null }, classification: {},
    depth_pressure: {}, wall_candidates: [{ side: 'bid', price: 440.5, volume: 12500, median_mult: 6.2 }] };
  await page.route('**/api/**', (route) => {
    const url = route.request().url();
    const body = url.includes('/api/order-flow/microstructure') ? BOOK
      : url.includes('/api/expiries') ? expiriesAnswer([]) : { available: false };
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
  await routeWatchlist(page, ['TSLA']);
  await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'TSLA'); localStorage.setItem('ed_ws', 'order-flow'); localStorage.setItem('ed_sub', 'book'); } catch (e) {} });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#obBody')).toContainText('bid @ 440.50');
  await expect(page.locator('#obBody')).toContainText('12500');
});

test('the Book ladder is each level of Schwab\'s book as sent, from the daemon, the newest book replacing the last', async ({ page }) => {
  // Real data: TSLA's NASDAQ_BOOK messages as Schwab sent them 2026-09-25 (tests/fixtures/real_tsla_book_rows.json)
  const books = BOOKS.filter((r) => r[1] === 'NASDAQ_BOOK').slice(0, 2);
  const errs = [];
  page.on('pageerror', (e) => errs.push(e.message));
  await page.route('**/api/**', (route) => {
    const url = route.request().url();
    const body = url.includes('/api/expiries') ? expiriesAnswer([]) : { available: false };
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
  await routeWatchlist(page, ['TSLA']);
  await mockPriceSocket(page, books.map((r) => schwabBook('NASDAQ_BOOK', 'TSLA', r[2], Number(r[0]), 'book ' + r[2].BOOK_TIME)));
  await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'TSLA'); localStorage.setItem('ed_ws', 'order-flow'); localStorage.setItem('ed_sub', 'book'); localStorage.setItem('ed_book_venue', 'NASDAQ_BOOK'); } catch (e) {} });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  const last = books[books.length - 1][2];
  await expect(page.locator('#obBody')).toContainText('NASDAQ_BOOK · book ' + last.BOOK_TIME);
  const want = last.ASKS.slice().reverse().map((l) => [l.ASK_PRICE.toFixed(2), String(l.TOTAL_VOLUME)])
    .concat(last.BIDS.map((l) => [l.BID_PRICE.toFixed(2), String(l.TOTAL_VOLUME)]));
  const shown = await page.locator('#obBody .dom-row').evaluateAll((rows) => rows.map((r) =>
    [r.querySelector('.dom-px').textContent, r.querySelector('.dom-sz').textContent]));
  expect(shown).toEqual(want);
  await expect(page.locator('#obBody .fl-badge').first()).toHaveText('LIVE');
  expect(errs).toEqual([]);
});

test('a Schwab outage: the Book panel keeps Schwab\'s last top of book, marked NOT LIVE with the reason', async ({ page }) => {
  // operator 2026-10-14: "the last values stand, marked not live". Schwab's last top of book as the
  // daemon pushes it, with the daemon's verdict on LEVELONE_EQUITIES (STAND-IN: SPY's last top of
  // book from tests/test_data_path_rules_v1.py's real capture, the outage's words). Before, the
  // page drew the reason in place of the bid and ask.
  const BOOK = { status: 'ok', depth: {}, ages: {}, as_of: { book: null, quote: null }, classification: {}, wall_candidates: [] };
  await mockPriceSocket(page, [Object.assign(schwabQuote('TSLA', 767.39, { BID_PRICE: 767.38, ASK_PRICE: 767.4, BID_SIZE: 300, ASK_SIZE: 200 }),
    { feed_live: false, outage: 'Schwab LEVELONE_EQUITIES feed down during RTH' })]);
  await page.route('**/api/**', (route) => {
    const url = route.request().url();
    const body = url.includes('/api/order-flow/microstructure') ? BOOK
      : url.includes('/api/expiries') ? expiriesAnswer([]) : { available: false };
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
  await routeWatchlist(page, ['TSLA']);
  await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'TSLA'); localStorage.setItem('ed_ws', 'order-flow'); localStorage.setItem('ed_sub', 'book'); } catch (e) {} });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#obBody')).toContainText('767.38 × 300');
  await expect(page.locator('#obBody')).toContainText('767.40 × 200');
  await expect(page.locator('#obBody')).toContainText('NOT LIVE · Schwab LEVELONE_EQUITIES feed down during RTH');
  await expect(page.locator('#obBody')).toHaveClass(/not-live/);
});
