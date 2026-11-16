/*
 * Order Flow heatmap draws the served book history and computes nothing (P1-3, PR C, 2026-09-27):
 * the default price window (display_lo/hi), each cell's dominant side and the colour scale's top
 * (max_size) are served; the page places each served cell at its own price and bucket. The payload
 * is the real producer's output over real TSLA book rows (tests/e2e/fixtures/book_heatmap_payload.json,
 * generated from tests/fixtures/real_tsla_book_rows.json). Any page error fails the test.
 */
const { test, expect } = require('@playwright/test');
const path = require('path');
const { routeWatchlist } = require('./fixtures/watchlist');
const { mockPriceSocket } = require('./fixtures/price_socket');

const HEAT = require(path.join(__dirname, 'fixtures', 'book_heatmap_payload.json'));

test('the heatmap paints the served cells, and a click pins a readout, without a page error', async ({ page }) => {
  const errs = [];
  page.on('pageerror', (e) => errs.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error' && !/WebSocket|EventSource|Failed to load resource/.test(m.text())) errs.push(m.text()); });
  await routeWatchlist(page, ['TSLA']);
  await mockPriceSocket(page, [], [], undefined, { bookmap: HEAT });
  // the payload is the producer's for NASDAQ_BOOK: the page shows the venue it asked, so it asks that one
  await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'TSLA'); localStorage.setItem('ed_ws', 'order-flow'); localStorage.setItem('ed_sub', 'heatmap'); localStorage.setItem('ed_book_venue', 'NASDAQ_BOOK'); });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  // drawn on the one shared chart (ed-tv-chart.js), every served cell handed to it
  const plot = page.locator('#ofhBody .ofh-plot');
  await expect(plot.locator('canvas').first()).toBeVisible();
  // the window as served (history.book_heatmap_for_ticker's time_et.ct_label of each end)
  await expect(page.locator('#ofhBody .ofh-foot')).toContainText('Fri 09/25 06:55 PM CT – Fri 09/25 07:00 PM CT');
  await expect.poll(() => page.evaluate(() => window.EdBookHeatmap.state()?.heatCells)).toBe(HEAT.cells.length);
  // the time axis and the crosshair read each bucket's served labels; the page formats no time
  expect(await page.evaluate(() => window.EdBookHeatmap.state().firstTime)).toEqual({
    day: HEAT.bucket_ticks[0][2],
    crosshair: HEAT.bucket_ct[0],
  });
  expect(HEAT.bucket_ticks[0][2]).toBe('Sep 25');
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
  // pinned on a served cell, the readout is that cell's: its bucket's served time
  // (history.book_heatmap_for_ticker's bucket_ct) and its served size. The cell is hit in pixels:
  // a book's levels sit a cent apart in a window dollars wide, each drawn at least a pixel tall
  const st = await page.evaluate(() => window.EdBookHeatmap.state());
  const t = Math.round((st.pinned.time - HEAT.since_ts) / HEAT.bucket_sec);
  const mid = (st.priceTop + st.priceBottom) / 2;
  const cell = HEAT.cells
    .filter((c) => c.t === t && c.bid != null && c.price < st.priceTop && c.price > st.priceBottom)
    .sort((a, b) => Math.abs(a.price - mid) - Math.abs(b.price - mid))[0];
  const h = await plot.locator('.tvc-plot').evaluate((p) => p.clientHeight);
  const y = ((st.priceTop - cell.price) / (st.priceTop - st.priceBottom)) * Math.max(1, h - 30);
  await page.mouse.click(box.x + box.width * 0.5, box.y + box.height * 0.5); // a click un-pins
  await page.mouse.click(box.x + box.width * 0.5, box.y + y);
  await expect(plot.locator('.tvc-pin .tvc-pin-h span')).toHaveText(HEAT.bucket_ct[t]);
  await expect(plot.locator('.tvc-pin')).toContainText('Bid size' + cell.bid);
  expect(errs).toEqual([]);
});

test('the Book panel names a failed read, never tells it as a book Schwab did not send', async ({ page }) => {
  const words = 'the program could not produce this panel: OSError: book read failed';
  await openBook(page, { failed: words });
  await expect(page.locator('#obBody')).toContainText(words);
  await expect(page.locator('#obBody')).not.toContainText('Schwab has sent no book');
});

test('the Book panel shows each served wall candidate size', async ({ page }) => {
  // the program's own answer on Schwab's captured SPY book (CLOSED_BOOK): each wall candidate
  // (engine._book_wall_candidates: side, price, volume, median_mult) reads its served size; the
  // page once printed w.size, never served
  await openBook(page, CLOSED_BOOK);
  expect(CLOSED_BOOK.wall_candidates.length).toBeGreaterThan(0);
  for (const w of CLOSED_BOOK.wall_candidates) {
    await expect(page.locator('#obBody')).toContainText(w.side + ' @ ' + Number(w.price).toFixed(2));
    await expect(page.locator('#obBody')).toContainText(String(Math.round(w.volume)));
  }
});

// the program's own answers for SPY's real book and quotes at 22:00 ET, the daemon's connection up
// and ended (tests/test_order_flow_book_payload_v1.py)
const CLOSED_BOOK = require(path.join(__dirname, 'fixtures', 'order_flow_book_closed_payload.json'));
const OFFLINE_BOOK = require(path.join(__dirname, 'fixtures', 'order_flow_book_offline_payload.json'));

// the Book view opened with `book` as the book panel the page's socket sends
async function openBook(page, book) {
  await routeWatchlist(page, ['SPY']);
  await mockPriceSocket(page, [], [], undefined, { book: book });
  await page.addInitScript(() => { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'order-flow'); localStorage.setItem('ed_sub', 'book'); });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
}

test('a feed down keeps the last bid and the panel says OFFLINE', async ({ page }) => {
  await openBook(page, OFFLINE_BOOK);
  await expect(page.locator('#obBody')).toContainText(OFFLINE_BOOK.top_of_book.bid.toFixed(2));
  await expect(page.locator('#obBody')).toContainText('Top of book · OFFLINE');
  await expect(page.locator('#obBody .fl-badge')).toHaveText('OFFLINE');
  await expect(page.locator('#obBody')).not.toContainText('feed down');
});

test('a closed market keeps the last bid and the panel says NOT LIVE, not OFFLINE', async ({ page }) => {
  await openBook(page, CLOSED_BOOK);
  await expect(page.locator('#obBody')).toContainText(CLOSED_BOOK.top_of_book.bid.toFixed(2));
  await expect(page.locator('#obBody')).toContainText('Top of book · NOT LIVE');
  await expect(page.locator('#obBody .fl-badge')).toHaveText('NOT LIVE');      // the book's served word
  await expect(page.locator('#obBody')).not.toContainText('OFFLINE');
  await expect(page.locator('#obBody')).not.toContainText('STALE');
});

test('an offline book keeps Schwab\'s quote time and book time', async ({ page }) => {
  await openBook(page, OFFLINE_BOOK);
  await expect(page.locator('#obBody')).toContainText(OFFLINE_BOOK.top_of_book.bid.toFixed(2));
  await expect(page.locator('#obBody')).toContainText('OFFLINE');
  // each time with its age, as served (server._when_age, the one age formatter)
  await expect(page.locator('#obBody')).toContainText(OFFLINE_BOOK.quote_when_age_text);
  await expect(page.locator('#obBody')).toContainText(OFFLINE_BOOK.book_when_age_text);
});
