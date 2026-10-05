/*
 * The capture daemon's bar backfill reaches the screen: /api/bars1m serves it as one finished line
 * (server.backfill_line, from the daemon's heartbeat, its time in Central Time) and every chart
 * prints that line as served, beside its last completed bar. A refusal from Schwab is on the
 * screen, not only in the record. The answer drawn is a captured /api/bars1m answer
 * (fixtures/bars1m_backfill_refused.json: the real backfill against a 429 stand-in, the console's
 * real route, SPY's recorded 2026-10-05 08:44 CT bar); tests/test_data_path_bar_backfill_v1.py
 * checks its line is still what the console serves for its heartbeat.
 */
const { test, expect } = require('@playwright/test');
const path = require('path');

const BARS = require(path.join(__dirname, 'fixtures', 'bars1m_backfill_refused.json')).response;

test('every chart prints the served bar-backfill line', async ({ page }) => {
  // every other route answers unavailable: this test is about the bars' line only
  await page.route('**/api/**', (route) => route.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify(route.request().url().includes('/api/bars1m') ? BARS : { available: false }) }));
  for (const [ws, sub, view, host] of [['trade-desk', 'desk', '', '#tdmChart'], ['options', 'gamma', 'chart', '#chartBody'],
    ['liquidity', 'map', '', '#liqmBody']]) {
    await page.addInitScript(([w, s, v]) => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', w);
      localStorage.setItem('ed_sub', s); if (v) localStorage.setItem('ed_view', v); } catch (e) {} }, [ws, sub, view]);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator(host + ' .tvc-backfill'), ws + '/' + sub).toHaveText(BARS.backfill);
  }
});
