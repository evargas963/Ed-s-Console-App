// @ts-check
/**
 * D — Options/Gamma "Chain" subview. Renders the full vendor chain ladder from /api/chain (calls
 * left, puts right, strike centre) VERBATIM; computes nothing; discloses the chain scope. Proves the
 * subview swaps into the options canvas, the ladder renders, spot is marked, a strike click drives
 * the shared selection, and switching back restores the Gamma grid. Offline.
 */
const { test, expect } = require('@playwright/test');

function ct(side, strike, oi, vol, iv, delta) {
  return { putCall: side, strikePrice: strike, openInterest: oi, totalVolume: vol, volatility: iv, delta: delta,
    gamma: 0.01, expirationDate: '2026-09-11' };
}
const CHAIN = { ticker: 'SPY', spot: 100, expiry: '2026-09-11', status: 'ok',
  scope: { kind: 'complete_single_expiry', completeness_basis: 'strike_range=ALL' },
  contracts: [
    ct('CALL', 102, 1200, 300, 11.1, 0.35), ct('PUT', 102, 900, 250, 12.1, -0.65),
    ct('CALL', 100, 5400, 2100, 12.3, 0.52), ct('PUT', 100, 4100, 1800, 12.6, -0.48),
    ct('CALL', 98, 800, 150, 13.5, 0.68), ct('PUT', 98, 1500, 600, 14.0, -0.32),
  ] };

async function intercept(page) {
  await page.route('**/api/**', (route) => {
    const url = route.request().url();
    let body = { available: false };
    if (url.includes('/api/chain')) body = CHAIN;
    else if (url.includes('/api/options/gamma-surface')) body = { ticker: 'SPY', available: true, spot: 100,
      source: 'terrain_live_cache', live: true, stale: false, expirations: [{ expiry: '2026-09-11', dte: 2 }],
      strikes: [100], cells: [{ strike: 100, gex: [1] }] };
    else if (url.includes('/api/terrain/strikes')) body = { spot: 100, today_source: 'terrain_live_cache', today_age_sec: 5, levels_stale: false, today: { all: [[100, 1, 1]] } };
    else if (url.includes('/api/terrain')) body = { spot: 100, gamma_flip: 99.5, regime: 'LONG_GAMMA_CHOP', levels_stale: false };
    else if (url.includes('/api/expiries')) body = { expiries: ['2026-09-11'] };
    else if (url.includes('/api/live/state')) body = { ticker: 'SPY', spot: 100, spot_disp: '100.00', session_label: 'RTH', analytics_lightweight: {}, streaming_plane: { streaming_healthy: true, streaming_staleness_ms: 300 } };
    else if (url.includes('/api/health')) body = { status: 'ok', capabilities: { schwab: true } };
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
}

test.describe('D — Gamma Chain subview', () => {
  test.beforeEach(async ({ page }) => {
    await intercept(page);
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); } catch (e) {} });
  });

  test('Chain subview swaps in the ladder; Gamma restores on switch back', async ({ page }) => {
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.sub-pane[data-sub-pane="gamma"]')).toBeVisible();
    await page.locator('#subnav .tab', { hasText: 'Chain' }).click();
    await expect(page.locator('.sub-pane[data-sub-pane="chain"]')).toBeVisible();
    await expect(page.locator('.sub-pane[data-sub-pane="gamma"]')).toBeHidden();
    const chn = page.locator('#chainBody table.chn');
    await expect(chn).toBeVisible();
    await expect(chn.locator('tbody tr')).toHaveCount(3);                 // 3 strikes
    await expect(chn.locator('tbody tr').first().locator('td.k')).toHaveText('102');   // sorted desc
    await expect(chn.locator('tbody tr.spot td.k')).toHaveText('100');    // spot strike marked
    await expect(page.locator('#chSrc .asof')).toContainText('complete (ALL)');
    await page.setViewportSize({ width: 1672, height: 941 });
    await page.screenshot({ path: 'test-results/gamma-chain-1672x941.png', fullPage: false });
    // switch back to Gamma
    await page.locator('#subnav .tab', { hasText: 'Gamma' }).click();
    await expect(page.locator('.sub-pane[data-sub-pane="gamma"]')).toBeVisible();
    await expect(page.locator('.sub-pane[data-sub-pane="chain"]')).toBeHidden();
  });

  test('a chain strike click drives the shared strike selection', async ({ page }) => {
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    await page.locator('#subnav .tab', { hasText: 'Chain' }).click();
    await page.locator('#chainBody tr[data-strike="98"]').click();
    const sel = await page.evaluate(() => window.EdShell.getState().selStrike);
    expect(sel).toBe(98);
  });
});
