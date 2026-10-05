/*
 * The capture daemon's bar backfill reaches the screen: /api/bars1m serves it as one finished line
 * (server.backfill_line, from the daemon's heartbeat, its time in Central Time) and every chart
 * prints that line as served, beside its last completed bar. A refusal from Schwab is on the
 * screen, not only in the record. The bar is the captured SPY 2026-10-05 08:44 CT bar
 * (tests/fixtures/real_daemon_bars_spy_2026_10_05.json); the line is the console's words for a
 * 429 refusal (stand-in: no 429 of Schwab's is captured).
 */
const { test, expect } = require('@playwright/test');
const path = require('path');

const ROW = require(path.join(__dirname, '..', 'fixtures', 'real_daemon_bars_spy_2026_10_05.json')).rows
  .find((r) => r.bar_start_ms === 1791207840000);
const LINE = 'BAR BACKFILL STOPPED Mon 10/05 11:30 AM CT: Schwab refused (QQQ: HTTP 429), no retry; '
  + '1 of 80 price-history requests sent, 0 bars written';
const BARS = { ticker: 'SPY', tf: '1', n: 1, backfill: LINE,
  bars: [{ t: ROW.bar_start_ms / 1000, o: ROW.open, h: ROW.high, l: ROW.low, c: ROW.close, v: ROW.volume, chg: null, chg_pct: null }],
  last_bar: { t: ROW.bar_start_ms / 1000, label: 'Mon 10/05 08:44 AM CT' } };

test('every chart prints the served bar-backfill line', async ({ page }) => {
  // every other route answers unavailable: this test is about the bars' line only
  await page.route('**/api/**', (route) => route.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify(route.request().url().includes('/api/bars1m') ? BARS : { available: false }) }));
  for (const [ws, sub, view, host] of [['trade-desk', 'desk', '', '#tdmChart'], ['options', 'gamma', 'chart', '#chartBody'],
    ['liquidity', 'map', '', '#liqmBody']]) {
    await page.addInitScript(([w, s, v]) => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', w);
      localStorage.setItem('ed_sub', s); if (v) localStorage.setItem('ed_view', v); } catch (e) {} }, [ws, sub, view]);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator(host + ' .tvc-backfill'), ws + '/' + sub).toHaveText(LINE);
  }
});
