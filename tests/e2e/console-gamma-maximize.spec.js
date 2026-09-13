// @ts-check
/**
 * #8 PANEL MAXIMIZE — maximize/restore the Gamma main analytical panel (Heatmap/Chart). Presentation
 * only: it hides the Key Levels rail + bottom strip and lets the heatmap fill the workspace, WITHOUT
 * touching the shared ticker / strike / expiry / scope state — so Restore returns to the exact same
 * context. Esc restores; the choice persists. Offline.
 */
const { test, expect } = require('@playwright/test');

const SURFACE = { ticker: 'SPY', symbol: 'SPY', available: true, spot: 100, source: 'terrain_live_cache',
  live: true, stale: false, age_sec: 5, chain_basis: 'full', complete: false,
  expirations: [{ expiry: '2026-09-11', dte: 2 }, { expiry: '2026-09-18', dte: 9 }],
  strikes: [98, 100, 102], cells: [98, 100, 102].map(function (k) { return { strike: k, gex: [-90000, 120000] }; }) };
const TERRAIN = { spot: 100, gamma_flip: 99.5, call_wall: 102, put_wall: 98, absolute_gamma_strike: 100,
  net_gex_peak: 100, net_gex_at_spot: 5e8, regime: 'LONG_GAMMA_CHOP', levels_stale: false, levels_age_sec: 10 };
const STRIKES = { spot: 100, today_source: 'terrain_live_cache', today_age_sec: 10, levels_stale: false,
  today: { all: [[98, -90000, 10], [100, 958600, 50], [102, -264500, 12]] } };
const CHAIN = { spot: 100, expiry: '2026-09-11', status: 'ok', scope: { kind: 'complete_single_expiry' },
  contracts: [{ putCall: 'CALL', strikePrice: 100, openInterest: 1200, totalVolume: 540, gamma: 0.021, delta: 0.5, volatility: 12, expirationDate: '2026-09-11' },
    { putCall: 'PUT', strikePrice: 100, openInterest: 980, totalVolume: 410, gamma: 0.019, delta: -0.5, volatility: 12, expirationDate: '2026-09-11' }] };
const LIVE = { ticker: 'SPY', spot: 100, spot_disp: '100.00', bid: 99.99, ask: 100.01, session_label: 'RTH',
  analytics_lightweight: {}, streaming_plane: { streaming_healthy: true, streaming_staleness_ms: 300 } };

async function intercept(page) {
  await page.route('**/api/**', (route) => {
    const url = route.request().url();
    let body = { available: false };
    if (url.includes('/api/options/gamma-surface')) body = SURFACE;
    else if (url.includes('/api/terrain/strikes')) body = STRIKES;
    else if (url.includes('/api/terrain')) body = TERRAIN;
    else if (url.includes('/api/bars1m')) body = { bars: [{ t: 1757000000, o: 99, h: 101, l: 98, c: 100, v: 1 }] };
    else if (url.includes('/api/expiries')) body = { expiries: ['2026-09-11', '2026-09-18'] };
    else if (url.includes('/api/chain')) body = CHAIN;
    else if (url.includes('/api/live/state')) body = LIVE;
    else if (url.includes('/api/health')) body = { status: 'ok', capabilities: { schwab: true } };
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
}

test.describe('#8 Gamma panel maximize', () => {
  test.beforeEach(async ({ page }) => {
    await intercept(page);
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); } catch (e) {} });
  });

  test('maximize hides the rail + bottom and lets the heatmap fill; Esc restores', async ({ page }) => {
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#maxBtn')).toBeVisible();
    await expect(page.locator('.p-levels')).toBeVisible();
    await expect(page.locator('.p-bottom')).toBeVisible();
    await page.locator('#maxBtn').click();
    await expect(page.locator('.gamma-grid.maxed')).toHaveCount(1);
    await expect(page.locator('.p-levels')).toBeHidden();
    await expect(page.locator('.p-bottom')).toBeHidden();
    await expect(page.locator('#view-heatmap .hcell').first()).toBeVisible();   // heatmap still there, filling
    await page.setViewportSize({ width: 1672, height: 941 });
    await page.screenshot({ path: 'test-results/gamma-maximized-1672x941.png', fullPage: false });
    await page.keyboard.press('Escape');
    await expect(page.locator('.gamma-grid.maxed')).toHaveCount(0);
    await expect(page.locator('.p-levels')).toBeVisible();
    await expect(page.locator('.p-bottom')).toBeVisible();
  });

  test('maximize preserves the shared ticker / strike / expiry context', async ({ page }) => {
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    await page.locator('#expSel').selectOption('2026-09-18');                    // pick a single expiry
    await page.locator('#view-heatmap .hcell[data-strike="102"]').first().click(); // pick a strike
    const before = await page.evaluate(() => window.EdShell.getState());
    await page.locator('#maxBtn').click();
    await page.locator('#maxBtn').click();                                        // maximize then restore
    const after = await page.evaluate(() => window.EdShell.getState());
    expect(after.ticker).toBe(before.ticker);
    expect(after.selStrike).toBe(102);
    expect(after.expiryFilter).toBe('2026-09-18');
    await expect(page.locator('#expSel')).toHaveValue('2026-09-18');
    await expect(page.locator('#sdCtx')).toContainText('102');                    // Strike Detail context intact
  });

  test('the maximize choice persists across reload', async ({ page }) => {
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    await page.locator('#maxBtn').click();
    await expect(page.locator('.gamma-grid.maxed')).toHaveCount(1);
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.locator('.gamma-grid.maxed')).toHaveCount(1);
    await expect(page.locator('.p-bottom')).toBeHidden();
  });
});
