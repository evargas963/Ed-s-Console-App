// @ts-check
/**
 * Options/Gamma "Chart" subview (Price + GEX Profile / GEX Dot Map). /api/terrain/strikes is a
 * genuine all-expiry aggregate -- no single mark has one real expiry to attribute. But clicking a
 * mark is still a deliberate strike selection, and every OTHER view that calls EdShell.setStrike
 * (heatmap: the column's real expiry; Chain: the one displayed expiry) always supplies a real
 * expiry so Strike Detail can resolve one. Chart's click handler used to pass NO expiry at all,
 * unconditionally clobbering state.selExpiry to null (ed-core.js setStrike) even when the operator
 * had a specific expiry filter selected in the workspace -- silently discarding that context and
 * sending Strike Detail's /api/chain request to the server's own default-expiry resolution instead.
 *
 * Independent-review finding (2026-09-13), REPRODUCED. Fixed: the click now carries through
 * whatever workspace expiry filter (EdShell.getExpiry()) is currently set, matching the
 * established convention, while still passing null when the filter itself is null (Chart has no
 * per-mark expiry to invent in that case either).
 */
const { test, expect } = require('@playwright/test');

const STRIKES = { spot: 100, today_source: 'terrain_live_cache', today_age_sec: 5, levels_stale: false,
  today: { all: [[98, -90000, 10], [100, 958600, 50], [102, -264500, 12]] } };
const TERRAIN = { spot: 100, gamma_flip: 99.5, call_wall: 102, put_wall: 98, regime: 'LONG_GAMMA_CHOP', levels_stale: false };
const BARS = { bars: [{ t: 1757000000, o: 99, h: 101, l: 98, c: 100, v: 1 }] };
const CHAIN = { spot: 100, expiry: '2026-09-18', status: 'ok', scope: { kind: 'complete_single_expiry' },
  contracts: [{ putCall: 'CALL', strikePrice: 102, openInterest: 1200, totalVolume: 540, gamma: 0.021, delta: 0.5, volatility: 12 }] };

async function intercept(page) {
  const chainRequests = [];
  await page.route('**/api/**', (route) => {
    const url = route.request().url();
    let body = { available: false };
    if (url.includes('/api/terrain/strikes')) body = STRIKES;
    else if (url.includes('/api/terrain')) body = TERRAIN;
    else if (url.includes('/api/bars1m')) body = BARS;
    else if (url.includes('/api/expiries')) body = { expiries: ['2026-09-11', '2026-09-18'] };
    else if (url.includes('/api/chain')) {
      const u = new URL(url); chainRequests.push(u.searchParams.get('expiry'));
      body = CHAIN;
    }
    else if (url.includes('/api/live/state')) body = { ticker: 'SPY', spot: 100, spot_disp: '100.00', session_label: 'RTH', analytics_lightweight: {}, streaming_plane: { streaming_healthy: true, streaming_staleness_ms: 300 } };
    else if (url.includes('/api/health')) body = { status: 'ok', capabilities: { schwab: true } };
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
  return chainRequests;
}

test.describe('Options/Gamma Chart subview', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); } catch (e) {} });
  });

  test('clicking a Chart mark carries through the workspace expiry filter to Strike Detail (state-authority review)', async ({ page }) => {
    const chainRequests = await intercept(page);
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    await page.locator('.vtab[data-view="chart"]').click();
    await page.locator('#expSel').selectOption('2026-09-18');
    await expect(page.locator('#chartBody .gmark').first()).toBeVisible();

    chainRequests.length = 0;   // only count requests issued AFTER the click below
    // The profile bars are ~2 real pixels tall (a 6-unit rect in a 540-unit viewBox scaled to a
    // small panel), so Playwright's coordinate-based click can miss the exact shape and hit an
    // overlapping neighbour or the SVG background. Dispatch the click directly on the target
    // node instead -- this test verifies the click HANDLER's identity-carrying logic, not
    // pixel-precise pointer hit-testing (real click delivery is unremarkable browser behaviour).
    await page.locator('#chartBody .gmark[data-strike="102"]').first()
      .evaluate((el) => el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true })));

    const state = await page.evaluate(() => window.EdShell.getState());
    expect(state.selStrike).toBe(102);
    expect(state.selExpiry).toBe('2026-09-18');   // NOT null -- the workspace filter, carried through
    await expect.poll(() => chainRequests.length).toBeGreaterThan(0);
    expect(chainRequests.every((e) => e === '2026-09-18')).toBeTruthy();
  });

  test('with no expiry filter set, a Chart click leaves selExpiry null (no invented expiry)', async ({ page }) => {
    await intercept(page);
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    await page.locator('.vtab[data-view="chart"]').click();
    await expect(page.locator('#expSel')).toHaveValue('');
    await expect(page.locator('#chartBody .gmark').first()).toBeVisible();

    // The profile bars are ~2 real pixels tall (a 6-unit rect in a 540-unit viewBox scaled to a
    // small panel), so Playwright's coordinate-based click can miss the exact shape and hit an
    // overlapping neighbour or the SVG background. Dispatch the click directly on the target
    // node instead -- this test verifies the click HANDLER's identity-carrying logic, not
    // pixel-precise pointer hit-testing (real click delivery is unremarkable browser behaviour).
    await page.locator('#chartBody .gmark[data-strike="102"]').first()
      .evaluate((el) => el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true })));
    const state = await page.evaluate(() => window.EdShell.getState());
    expect(state.selStrike).toBe(102);
    expect(state.selExpiry).toBeNull();
  });
});
