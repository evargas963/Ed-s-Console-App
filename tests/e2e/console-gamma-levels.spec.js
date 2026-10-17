// @ts-check
/**
 * D — Options/Gamma "Levels" view. Serializes the canonical /api/levels contract (per-level
 * price/family/evidence_tier/provenance/staleness + carried VWAP) verbatim; computes nothing.
 * Proves the table renders the contract, discloses VWAP/absent/degraded honestly, marks no
 * proximity, and a level click drives the shared strike selection. Offline.
 */
const { test, expect } = require('@playwright/test');
const { routeWatchlist } = require('./fixtures/watchlist');

const LEVELS = {
  ticker: 'SPY', schema_version: 1, served_ts_utc: 1757000100, spot: 100.0, spot_source: 'schwab_quote_last',
  generation: 7, snapshot_as_of_ts_utc: 1757000000, bar_source: 'price_bars_1m',
  // served in ladder order (price, highest first) with distance (server.py get_levels)
  levels: [
    { id: 'PDH', price: 101.5, family: 'session', label: 'Prior Day High', evidence_tier: 'MEASURED', distance: 1.5,
      provenance: { producer: 'session_levels' }, staleness: { as_of_ts_utc: 1757000000, age_sec: 12, stale: false } },
    { id: 'VWAP', price: 100.02, family: 'vwap', label: 'VWAP', evidence_tier: 'MEASURED', distance: 0.02,
      provenance: { producer: 'liquidity_value_engine' }, staleness: { as_of_ts_utc: 1757000000, age_sec: 12, stale: false } },
    { id: 'POC', price: 99.4, family: 'value', label: 'Point of Control', evidence_tier: 'DERIVED', distance: -0.6,
      provenance: { producer: 'value_area' }, staleness: { as_of_ts_utc: 1757000000, age_sec: 12, stale: false } },
  ],
  by_distance: ['VWAP', 'POC', 'PDH'],
  vwap_series: [[1757000000, 100.0, 100.5, 99.5, 101.0, 99.0]],
  families_absent: [{ family: 'gamma', reason: 'served by /api/terrain' }],
  degraded: [],
};

async function intercept(page) {
  await page.route('**/api/**', (route) => {
    const url = route.request().url();
    let body = { available: false };
    if (url.includes('/api/levels')) body = LEVELS;
    else if (url.includes('/api/options/gamma-surface')) body = { ticker: 'SPY', available: true, spot: 100,
      source: 'terrain_live_cache', live: true, stale: false, expirations: [{ expiry: '2026-09-11', dte: 2 }],
      strikes: [100], cells: [{ strike: 100, gex: [1] }],
      view: { centre: 100, scope: 'auto', coverage: null, max_abs: { gex: 1 }, missing_expiry: null } };
    else if (url.includes('/api/terrain/strikes')) body = { spot: 100, today_source: 'terrain_live_cache', today_age_sec: 5, levels_stale: false, today: { all: [[100, 1, 1]] },
      views: { all: { centre: 100, note: null, max_abs: 1 } } };
    else if (url.includes('/api/terrain')) body = { spot: 100, gamma_flip: 99.5, regime: 'LONG_GAMMA_CHOP', levels_stale: false };
    else if (url.includes('/api/expiries')) body = { expiries: ['2026-09-11'] };    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
  await routeWatchlist(page, ['SPY']);
}

test.describe('D — Gamma Levels view', () => {
  test.beforeEach(async ({ page }) => {
    await intercept(page);
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_view', 'levels'); } catch (e) {} });
  });

  test('the levels spot keeps its last trade time', async ({ page }) => {
    await page.route('**/api/levels**', (route) => route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify(Object.assign({}, LEVELS, { spot_time_ct: 'Fri 10/02 10:00 AM CT' })) }));
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#levelsBody .lv-spot')).toHaveText('spot 100.00 · schwab_quote_last · last trade Fri 10/02 10:00 AM CT');
  });

  test('the As-of column keeps the level time', async ({ page }) => {
    const LEVEL_TIME = 'Fri 09/25 06:59 PM CT';
    const levels = JSON.parse(JSON.stringify(LEVELS));
    levels.levels.forEach(function (r) { r.staleness.as_of_time_ct = LEVEL_TIME; });
    await page.route('**/api/levels**', (route) => route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify(levels) }));
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#levelsBody .lv-row', { hasText: 'Prior Day High' }).locator('.lv-px')).toHaveText('101.50');
    await expect(page.locator('#levelsBody .lv-row', { hasText: 'Prior Day High' }).locator('.lv-age')).toHaveText(LEVEL_TIME + ' · 12s');
  });

  test('renders the canonical /api/levels contract as a table', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const lv = page.locator('#levelsBody');
    await expect(lv.locator('table.lv')).toBeVisible();
    await expect(lv.locator('.lv-row')).toHaveCount(3);
    // the served ladder order: PDH (101.5) first
    await expect(lv.locator('.lv-row').first()).toContainText('Prior Day High');
    await expect(lv.locator('.lv-row').first().locator('.lv-px')).toHaveText('101.50');
    await expect(lv.locator('.lv-row', { hasText: 'VWAP' }).locator('.lv-src')).toContainText('liquidity_value_engine');
    // no proximity marking (operator 2026-09-29); absence disclosed honestly
    await expect(lv.locator('.lv-row.near-spot')).toHaveCount(0);
    await expect(lv.locator('.lv-foot')).toContainText('VWAP curve');
    await expect(lv.locator('.lv-foot .lv-absent')).toContainText('gamma');
    await page.setViewportSize({ width: 1672, height: 941 });
    await page.screenshot({ path: 'test-results/gamma-levels-1672x941.png', fullPage: false });
  });

  test('a level click highlights locally but NEVER writes selStrike (a level price is not a strike)', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const before = await page.evaluate(() => window.EdShell.getState().selStrike);
    await page.locator('#levelsBody .lv-row', { hasText: 'Prior Day High' }).click();  // price 101.5
    await expect(page.locator('#levelsBody .lv-row.lv-sel')).toHaveCount(1);            // local highlight only
    const after = await page.evaluate(() => window.EdShell.getState().selStrike);
    expect(after).toBe(before);                                                          // selStrike unchanged
    expect(after).not.toBe(101.5);                                                       // never the level price
  });

  test('the 0DTE table shows the served same-day price beside the level it reprices', async ({ page }) => {
    await page.route('**/api/levels**', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(Object.assign({}, LEVELS, {
        zero_dte: [{ id: 'call_wall', label: 'Call wall', carried: 600, price: 580 }],
      })),
    }));
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const row = page.locator('#levelsBody .zd-row', { hasText: 'Call wall' });
    await expect(row.locator('.lv-px').nth(0)).toHaveText('600.00');
    await expect(row.locator('.lv-px').nth(1)).toHaveText('580.00');
  });
});
