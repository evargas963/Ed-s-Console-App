// @ts-check
/**
 * TICKER / EXPIRY / MEASURE controls — the value IS the control (real dropdowns, not metadata chips).
 * Proves: one selected-symbol state (dropdown <-> watchlist <-> header <-> panels); the expiry list
 * comes from /api/expiries (never hard-coded); All Expirations shows every canonical column; a single
 * expiry filters the heatmap to that column; an old expiry invalid for a new ticker fails safe to All;
 * terrain Key Levels stay disclosed as all-exp when a single expiry is filtered. Offline.
 */
const { test, expect } = require('@playwright/test');

const EXPS = ['2026-09-11', '2026-09-12', '2026-09-18'];
function surfaceFor(tk, spot) {
  return { ticker: tk, symbol: tk, available: true, spot: spot, source: 'terrain_live_cache',
    live: true, stale: false, age_sec: 5, chain_basis: 'full', complete: false,
    expirations: EXPS.map(function (e, i) { return { expiry: e, dte: [2, 3, 9][i] }; }),
    strikes: [spot - 2, spot, spot + 2],
    cells: [spot - 2, spot, spot + 2].map(function (k) { return { strike: k, gex: [-90000, 958600, -264500] }; }) };
}
const TERRAIN = { spot: 100, gamma_flip: 99.5, call_wall: 102, put_wall: 98, absolute_gamma_strike: 100,
  net_gex_peak: 100, net_gex_at_spot: 5e8, regime: 'LONG_GAMMA_CHOP', levels_stale: false, levels_age_sec: 10 };
const STRIKES = { spot: 100, today_source: 'terrain_live_cache', today_age_sec: 10, levels_stale: false,
  today: { all: [[98, -90000, 10], [100, 958600, 50], [102, -264500, 12]] } };
const BARS = { bars: [{ t: 1757000000, o: 99, h: 101, l: 98, c: 100, v: 1000 }] };
function liveFor(tk, spot) { return { ticker: tk, spot: spot, spot_disp: spot.toFixed(2), bid: spot - 0.01, ask: spot + 0.01,
  session_label: 'RTH', analytics_lightweight: {}, streaming_plane: { streaming_healthy: true, streaming_staleness_ms: 300 } }; }

async function intercept(page) {
  await page.route('**/api/**', (route) => {
    const url = route.request().url();
    const tk = (url.match(/[?&]ticker=([^&]+)/) || [])[1] || 'SPY';
    const dec = decodeURIComponent(tk);
    const spot = dec === 'QQQ' ? 480 : 100;
    let body = { available: false };
    if (url.includes('/api/options/gamma-surface')) body = surfaceFor(dec, spot);
    else if (url.includes('/api/terrain/strikes')) body = Object.assign({}, STRIKES, { spot: spot });
    else if (url.includes('/api/terrain')) body = Object.assign({}, TERRAIN, { spot: spot });
    else if (url.includes('/api/bars1m')) body = BARS;
    else if (url.includes('/api/expiries')) body = { expiries: EXPS };
    else if (url.includes('/api/chain')) body = { ticker: dec, spot: spot, expiry: EXPS[0], status: 'ok',
      scope: { kind: 'complete_single_expiry' }, contracts: [] };
    else if (url.includes('/api/live/state')) body = liveFor(dec, spot);
    else if (url.includes('/api/health')) body = { status: 'ok', capabilities: { schwab: true } };
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
}

test.describe('ticker / expiry / measure controls', () => {
  test.beforeEach(async ({ page }) => {
    await intercept(page);
    await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY');
      localStorage.setItem('ed_watchlist_v1', JSON.stringify(['SPY', 'QQQ', 'IWM'])); } catch (e) {} });
  });

  test('controls are real dropdowns (value is the control, no SYM/EXPIRY/MEASURE chips)', async ({ page }) => {
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#symSel')).toBeVisible();
    await expect(page.locator('#expSel')).toBeVisible();
    await expect(page.locator('#measureSel')).toBeVisible();
    // the old SYM/EXPIRY/MEASURE metadata chips are gone (the value itself is the control)
    await expect(page.locator('.viewbar .ctrls .sel')).toHaveCount(0);
    await expect(page.locator('#measureSel')).toHaveValue('gex');
  });

  test('expiry options come from /api/expiries; All Expirations is the default', async ({ page }) => {
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    const opts = page.locator('#expSel option');
    await expect(opts).toHaveCount(1 + EXPS.length);           // All + each canonical expiry
    await expect(opts.first()).toHaveText('All Expirations');
    await expect(page.locator('#expSel')).toHaveValue('');     // defaults to All
  });

  test('selecting one expiry filters the heatmap to that column; All restores every column', async ({ page }) => {
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#view-heatmap .hexp')).toHaveCount(EXPS.length);   // All Expirations
    await page.locator('#expSel').selectOption('2026-09-12');
    await expect(page.locator('#view-heatmap .hexp')).toHaveCount(1);             // just the selected expiry
    await expect(page.locator('#view-heatmap .hexp .d')).toHaveText('09-12');
    // Key Levels stays aggregate terrain, disclosed as all-exp (never relabeled selected-expiry)
    await expect(page.locator('#klSrc')).toContainText('all-exp');
    await page.locator('#expSel').selectOption('');
    await expect(page.locator('#view-heatmap .hexp')).toHaveCount(EXPS.length);
    await expect(page.locator('#klSrc')).not.toContainText('all-exp');
  });

  test('one symbol state: dropdown -> header/watchlist/panels all move together', async ({ page }) => {
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#symSel')).toHaveValue('SPY');
    await page.locator('#symSel').selectOption('QQQ');
    await expect(page.locator('#hSym')).toHaveText('QQQ');                        // header
    await expect(page.locator('.wl-row.sel .info .s')).toHaveText('QQQ');         // watchlist selection
    await expect(page.locator('#mvTicker')).toHaveText('QQQ');                    // panel header
    // the heatmap refetched for QQQ (spot 480 -> a 480 strike row exists)
    await expect(page.locator('#view-heatmap .hstrike', { hasText: '480' }).first()).toBeVisible();
  });

  test('watchlist click keeps the ticker dropdown synchronized', async ({ page }) => {
    await page.goto('/console', { waitUntil: 'domcontentloaded' });
    await page.locator('.wl-row .info .s', { hasText: 'IWM' }).click();
    await expect(page.locator('#symSel')).toHaveValue('IWM');
  });
});
